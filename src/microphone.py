from __future__ import annotations
import argparse
import json
import logging
import queue
import signal
import sys
import threading
import time
import sounddevice as sd
from whisper_live.client import StreamingTranscriptionClient
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import numpy as np
import math
import zmq
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] microphone: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("microphone")

ZMQ_SUB_ADDRESS = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS = "tcp://localhost:5556"
STATUS_PUBLISH_INTERVAL = 5.0
TOPIC_STATUS = b"dynamo/status/microphone"
TOPIC_LIPSYNC = b"dynamo/data/lipsync"
TOPIC_TRANSCRIPTION = b"dynamo/data/transcription"
TOPIC_TRANSCRIPTION_PARTIAL = b"dynamo/data/transcription_partial"

WHISPER_HOST, WHISPER_PORT = "localhost", 9090
WHISPER_MODEL = "OpenVINO/whisper-base-fp16-ov"
PROFILE_PATH = "models/ulipsync_male.json"
VOL_MIN, VOL_MAX = -2.5, -1.5 # log10(RMS) mapped to level 0..1 (uLipSync defaults); tune with --monitor
IDLE_PUBLISH_DIVIDER = 6      # when silent, publish every 6th lipsync frame
SLOW_CHUNK = 1600             # samples per websocket packet (100 ms)
SAMPLE_RATE = 16000
WINDOW = 1024                 # 64 ms, what the uLipSync profiles were calibrated with
HOP = 256                     # 16 ms between results (4x overlap)
N_MEL = 30
N_MFCC = 12
PRE_EMPHASIS = 0.97
NON_VOWELS = frozenset({"-", "S", "N"}) # breath/noise, sibilant, nasal: reported as `phoneme`, never as `vowel`
EPS = 1e-12

def _to_mel(hz: float) -> float:
    return 1127.0 * math.log(hz / 700.0 + 1.0)

def _to_hz(mel: float) -> float:
    return 700.0 * (math.exp(mel / 1127.0) - 1.0)

def _mel_matrix(sr: int = SAMPLE_RATE, n: int = WINDOW, channels: int = N_MEL) -> np.ndarray:
    """Literal port of Algorithm.MelFilterBank (including its integer index rounding)."""
    f_max = sr / 2
    n_max = n // 2
    df = f_max / n_max
    d_mel = _to_mel(f_max) / (channels + 1)
    w = np.zeros((channels, n), dtype=np.float64)
    for c in range(channels):
        f_b, f_c, f_e = _to_hz(d_mel * c), _to_hz(d_mel * (c + 1)), _to_hz(d_mel * (c + 2))
        i_b, i_c, i_e = math.ceil(f_b / df), int(np.round(f_c / df)), math.floor(f_e / df)
        for i in range(i_b + 1, i_e + 1):
            f = df * i
            a = (f - f_b) / (f_c - f_b) if i < i_c else (f_e - f) / (f_e - f_c)
            w[c, i] = a / ((f_e - f_b) * 0.5)
    return w

@lru_cache(maxsize=4)
def _tables(channels: int) -> tuple[np.ndarray, np.ndarray]:
    dct = np.cos((np.arange(channels) + 0.5)[None, :] * np.arange(1, N_MFCC + 1)[:, None] * np.pi / channels)
    return _mel_matrix(channels=channels), dct


def mfcc_ulipsync(frame: np.ndarray, channels: int = N_MEL) -> np.ndarray | None:
    """12 MFCCs of one 1024-sample, 16 kHz frame, exactly as uLipSync computes them (after resampling)."""
    mel_m, dct_m = _tables(channels)
    x = frame.astype(np.float64)
    x[1:] = x[1:] - PRE_EMPHASIS * frame[:-1].astype(np.float64)          # x[0] unchanged, like the original
    x *= np.hamming(WINDOW)
    peak = np.max(np.abs(x))
    if peak < 1e-9:
        return None
    x /= peak
    mel = mel_m @ np.abs(np.fft.fft(x))
    return (dct_m @ (10.0 * np.log10(np.maximum(mel, EPS)))).astype(np.float32)


class Profile:
    """uLipSync profile: one averaged MFCC vector per row; several rows may share a phoneme name."""
    def __init__(self, rows: list[tuple[str, np.ndarray]], compare: str = "cosine", source: str = "", mel_channels: int = N_MEL) -> None:
        if not rows:
            raise ValueError("empty profile")
        self.rows, self.compare, self.source, self.mel_channels = rows, compare, source, mel_channels
        self._mat = np.stack([v for _, v in rows]).astype(np.float64)
        self.names = list(dict.fromkeys(n for n, _ in rows))
        self.vowels = [n for n in self.names if n not in NON_VOWELS]
        self._vowel_idx = [i for i, (n, _) in enumerate(rows) if n in self.vowels]

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        d = json.loads(Path(path).read_text())
        if d.get("standardize"):
            raise ValueError("profiles with standardization are not supported")
        if (d["n_mfcc"], d["sample_rate"], d["sample_count"]) != (N_MFCC, SAMPLE_RATE, WINDOW):
            raise ValueError(f"{path}: analysis settings differ from lipsync.py ({N_MFCC} MFCC / {SAMPLE_RATE} Hz / {WINDOW} samples)")
        rows = [(p["name"], np.asarray(p["mfcc"], dtype=np.float32)) for p in d["phonemes"]]
        return cls(rows, d.get("compare", "cosine"), d.get("source", ""), d["mel_channels"])

    def nearest_vowel(self, mfcc: np.ndarray) -> tuple[np.ndarray, float]:
        """Template of the closest vowel row (by cosine) and that cosine."""
        p = self._mat[self._vowel_idx]
        sim = (p @ mfcc.astype(np.float64)) / (np.linalg.norm(p, axis=1) * np.linalg.norm(mfcc) + EPS)
        k = int(np.argmax(sim))
        return p[k], float(sim[k])

    def classify(self, mfcc: np.ndarray) -> tuple[dict[str, float], float]:
        """Return (ratio per phoneme name, summing to 1; fit 0..1 = how close the best row is)."""
        m, p = mfcc.astype(np.float64), self._mat
        if self.compare == "cosine":
            sim = np.maximum((p @ m) / (np.linalg.norm(p, axis=1) * np.linalg.norm(m) + EPS), 0.0)
            score, fit = sim ** 100.0, float(sim.max())
        else:                                                              # l1 / l2, as in LipSyncJob
            d = np.abs(p - m).mean(axis=1) if self.compare == "l1" else np.sqrt(((p - m) ** 2).mean(axis=1))
            score, fit = 10.0 ** (-d), float((10.0 ** (-d)).max())
        total = float(score.sum())
        ratios = dict.fromkeys(self.names, 0.0)
        if total > 0:
            for (name, _), s in zip(self.rows, score):
                ratios[name] += float(s) / total
        return ratios, fit


class ChannelAdapter:
    """Estimates a constant cepstral offset (mic response / room / head enclosure) and removes it."""
    def __init__(self, tau_s: float = 60.0, prior_s: float = 10.0, max_norm: float = 30.0) -> None:
        self.gamma = math.exp(-(HOP / SAMPLE_RATE) / tau_s)
        self.prior = prior_s * SAMPLE_RATE / HOP
        self.max_norm = max_norm
        self.reset()

    def reset(self) -> None:
        self._sum, self._weight = np.zeros(N_MFCC), 0.0

    @property
    def offset(self) -> np.ndarray:
        o = self._sum / (self._weight + self.prior)
        n = float(np.linalg.norm(o))
        return o * (self.max_norm / n) if n > self.max_norm else o

    def update(self, raw_mfcc: np.ndarray, template: np.ndarray) -> None:
        self._sum = self.gamma * self._sum + (raw_mfcc - template)
        self._weight = self.gamma * self._weight + 1.0

    def correct(self, raw_mfcc: np.ndarray) -> np.ndarray:
        return (raw_mfcc - self.offset).astype(np.float32)


@dataclass
class LipSyncFrame:
    timestamp: float
    rms: float
    db: float
    level: float                    # smoothed 0..1 (log10 RMS mapped between vol_min..vol_max)
    raw_level: float
    phoneme: str | None             # top phoneme including '-' (noise) and 'S' (sibilant)
    vowel: str | None               # same, but only A/I/U/E/O; None when quiet or non-vowel
    fit: float                      # cosine similarity of best match; low = consonant / unseen sound
    weights: dict[str, float]       # smoothed phoneme ratios (multiply by level for blendshape-style use)
    speaking: bool
    events: list[dict[str, Any]] = field(default_factory=list)
    def to_message(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "level": round(self.level, 4), "raw_level": round(self.raw_level, 4),
                "db": round(self.db, 1), "phoneme": self.phoneme, "vowel": self.vowel, "fit": round(self.fit, 3),
                "weights": {k: round(v, 3) for k, v in self.weights.items()}, "speaking": self.speaking}


class LipSyncAnalyzer:
    def __init__(self, profile: Profile, *, vol_min: float = -2.5, vol_max: float = -1.5, weight_attack: float = 0.6, weight_release: float = 0.3) -> None:
        self.profile = profile
        self.vol_min, self.vol_max = vol_min, vol_max          # log10(RMS) range, uLipSync defaults
        self.adapter = ChannelAdapter()
        self.w_up, self.w_down = weight_attack, weight_release
        self._buf = np.zeros(0, dtype=np.float32)
        self._level = 0.0
        self._w: dict[str, float] = {}
        self.speech_on, self.speech_off = 0.15, 0.08
        self._speaking, self._on_n, self._off_n = False, 0, 0
        self._syl_armed, self._syl_peak, self._syl_valley = True, 0.0, 1.0
        self._syl_vowel: str | None = None
        self._syl_t = 0.0
        self._last_vowel: str | None = None

    @property
    def offset_norm(self) -> float:
        return float(np.linalg.norm(self.adapter.offset)) if self.adapter else 0.0

    def push(self, samples: np.ndarray) -> list[LipSyncFrame]:
        self._buf = np.concatenate((self._buf, samples.astype(np.float32, copy=False)))
        out: list[LipSyncFrame] = []
        while self._buf.size >= WINDOW:
            out.append(self._process(self._buf[:WINDOW]))
            self._buf = self._buf[HOP:]
        return out

    def _process(self, frame: np.ndarray) -> LipSyncFrame:
        t = time.time()
        rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
        log_rms = math.log10(rms + EPS)
        raw = min(1.0, max(0.0, (log_rms - self.vol_min) / (self.vol_max - self.vol_min)))
        self._level += (0.6 if raw > self._level else 0.2) * (raw - self._level)   # fast attack, slower release
        phoneme, fit = None, 0.0
        raw_mfcc = mfcc_ulipsync(frame, self.profile.mel_channels)
        if raw_mfcc is not None:
            mfcc = self.adapter.correct(raw_mfcc) if self.adapter else raw_mfcc
            ratios, fit = self.profile.classify(mfcc)
            for n, r in ratios.items():
                cur = self._w.get(n, 0.0)
                self._w[n] = cur + (self.w_up if r > cur else self.w_down) * (r - cur)
            best = max(ratios, key=ratios.get)
            if self.adapter and self._level > 0.2 and best in self.profile.vowels:
                template, cos = self.profile.nearest_vowel(mfcc)
                if cos > 0.8:                          # learn the channel only from clearly voiced, vowel-like frames
                    self.adapter.update(raw_mfcc, template)
        if self._w and raw_mfcc is not None and self._level > 0.05:
            phoneme = max(self._w, key=self._w.get)
        vowel = phoneme if phoneme in self.profile.vowels else None
        if vowel:
            self._last_vowel = vowel
        events = self._speech_events(t) + self._syllable_events(t)
        return LipSyncFrame(timestamp=t, rms=rms, db=20.0 * log_rms, level=self._level, raw_level=raw, phoneme=phoneme, vowel=vowel, fit=fit, weights=dict(self._w), speaking=self._speaking, events=events)

    def _speech_events(self, t: float) -> list[dict[str, Any]]:
        ev: list[dict[str, Any]] = []
        if not self._speaking:
            self._on_n = self._on_n + 1 if self._level > self.speech_on else 0
            if self._on_n >= 3:
                self._speaking, self._off_n = True, 0
                ev.append({"type": "speech_start", "timestamp": t})
        else:
            self._off_n = self._off_n + 1 if self._level < self.speech_off else 0
            if self._off_n >= 12:                        # ~190 ms of quiet
                self._speaking, self._on_n = False, 0
                ev.append({"type": "speech_stop", "timestamp": t})
        return ev

    def _syllable_events(self, t: float, fall: float = 0.75, min_peak: float = 0.12, rise: float = 0.05) -> list[dict[str, Any]]:
        """Heuristic: one syllable ~ one smoothed-loudness peak. Fires shortly after the peak."""
        lvl, ev = self._level, []
        if self._syl_armed:
            if lvl > self._syl_peak:
                self._syl_peak, self._syl_t = lvl, t
                self._syl_vowel = self._last_vowel
            elif self._syl_peak > min_peak and lvl < self._syl_peak * fall:
                ev.append({"type": "syllable", "vowel": self._syl_vowel, "level": round(self._syl_peak, 3), "timestamp": self._syl_t})
                self._syl_armed, self._syl_valley = False, lvl
        else:
            if lvl < self._syl_valley:
                self._syl_valley = lvl
            elif lvl > self._syl_valley + rise and lvl > self._syl_valley * 1.25:
                self._syl_armed, self._syl_peak, self._syl_t = True, lvl, t
                self._syl_vowel = self._last_vowel
        return ev


class MicCapture:
    """Single sounddevice input stream; the callback only copies and hands off."""
    def __init__(self, on_block: Callable[[np.ndarray], None], device: int | str | None = None) -> None:
        self._on_block, self._device = on_block, device
        self._stream: Any = None
        self.xruns = 0

    def start(self) -> None:
        try:
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=HOP, device=self._device, latency="low", callback=self._cb)
            self._stream.start()
        except sd.PortAudioError as exc:
            raise RuntimeError(f"Cannot open the microphone at {SAMPLE_RATE} Hz mono ({exc}). Try --list-devices and pick a PulseAudio/PipeWire device (those resample for you).") from exc

    def _cb(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            self.xruns += 1
        self._on_block(indata[:, 0].copy())

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def _put_drop(q: "queue.Queue[np.ndarray]", item: np.ndarray, counters: list[int], idx: int) -> None:
    try:
        q.put_nowait(item)
    except queue.Full:
        counters[idx] += 1


class MicrophoneNode:
    def __init__(self, device: int | str | None = None) -> None:
        self._running = threading.Event()
        self._stopped = threading.Event() # set by stop(); used for interruptible sleeps
        self._push_lock = threading.Lock() # ZMQ sockets are not thread-safe
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._analyzer = LipSyncAnalyzer(self._load_profile(PROFILE_PATH), vol_min=VOL_MIN, vol_max=VOL_MAX)
        self._fast_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=256)
        self._slow_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._dropped = [0, 0] # [fast, slow]
        self._capture = MicCapture(self._on_audio, device)
        self._threads: list[threading.Thread] = []
        self._slow_client: Any = None
        self._slow_connected = threading.Event()
        self._idle_n = 0

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        self._capture.start()
        self._spawn(self._lipsync_loop, "lipsync-fast")
        self._spawn(self._whisper_loop, "whisper-slow")
        self._spawn(self._status_loop, "microphone-status")
        log.info("Microphone node started — SUB=%s PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping Microphone node...")
        self._running.clear()
        self._stopped.set()

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        t = threading.Thread(target=target, daemon=True, name=name)
        t.start()
        self._threads.append(t)

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_sub = self._zmq_ctx.socket(zmq.SUB)
        self._zmq_sub.connect(ZMQ_SUB_ADDRESS)
        self._zmq_sub.setsockopt(zmq.RCVTIMEO, 500)
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)

    def _on_audio(self, block: np.ndarray) -> None:
        _put_drop(self._fast_q, block, self._dropped, 0)
        if self._slow_connected.is_set():
            _put_drop(self._slow_q, block, self._dropped, 1)

    def _load_profile(self, path: Path | None = None) -> Profile:
        p = Profile.load(path)
        log.info("Loaded lipsync profile %s: %s (%s)", path, p.names, p.source)
        return p

    def _lipsync_loop(self) -> None:
        while self._running.is_set():
            try:
                block = self._fast_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                for frame in self._analyzer.push(block):
                    self._publish_frame(frame)
            except Exception:
                log.exception("lipsync analysis error")

    def _publish_frame(self, frame: LipSyncFrame) -> None:
        quiet = not frame.speaking and frame.level < 0.02
        self._idle_n = self._idle_n + 1 if quiet else 0
        if quiet and self._idle_n % IDLE_PUBLISH_DIVIDER:
            return
        if __name__ == "__main__" and frame.phoneme:
            log.info("LIPSYNC: %s", frame.phoneme)
        self._push(TOPIC_LIPSYNC, frame.to_message())

    def _whisper_loop(self) -> None:
        """Connect/reconnect to WhisperLive without ever blocking the fast path."""
        while self._running.is_set():
            closed = threading.Event()
            client = StreamingTranscriptionClient(
                WHISPER_HOST, WHISPER_PORT, model=WHISPER_MODEL, ready_timeout=10.0,
                on_partial_transcript=lambda text, segs: self._on_transcript(TOPIC_TRANSCRIPTION_PARTIAL, text),
                on_committed_transcript=lambda text, segs: self._on_transcript(TOPIC_TRANSCRIPTION, text),
                on_close=closed.set, on_error=lambda exc: log.warning("WhisperLive error: %s", exc))
            try:
                client.connect()
            except Exception as exc:
                log.warning("WhisperLive not ready (%s); retrying in 5 s", exc)
                self._safe_close(client)
                self._stopped.wait(5.0)
                continue
            log.info("WhisperLive connected (%s:%d)", WHISPER_HOST, WHISPER_PORT)
            self._slow_client = client
            self._drain(self._slow_q)
            self._slow_connected.set()
            pending: list[np.ndarray] = []
            n = 0
            while self._running.is_set() and not closed.is_set():
                try:
                    block = self._slow_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                pending.append(block)
                n += block.size
                if n >= SLOW_CHUNK:
                    try:
                        client.send_array(np.concatenate(pending))
                    except Exception as exc:
                        log.warning("WhisperLive send failed: %s", exc)
                        break
                    pending, n = [], 0
            self._slow_connected.clear()
            self._slow_client = None
            self._safe_close(client)
            if self._running.is_set():
                log.warning("WhisperLive connection lost; reconnecting")
                self._stopped.wait(2.0)

    def _on_transcript(self, topic: bytes, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        payload: dict[str, Any] = {"text": text, "timestamp": time.time()}
        if topic == TOPIC_TRANSCRIPTION:
            log.info("Transcribed: %s", text)
        self._push(topic, payload)

    @staticmethod
    def _safe_close(client: Any) -> None:
        try:
            client.close(timeout=2.0)
        except Exception:
            pass

    @staticmethod
    def _drain(q: "queue.Queue[np.ndarray]") -> None:
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass

    def _event_loop(self) -> None:
        assert self._zmq_sub is not None
        while self._running.is_set():
            try:
                frames = self._zmq_sub.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError as exc:
                if self._running.is_set():
                    log.error("ZeroMQ receive error: %s", exc)
                break
            if len(frames) < 2:
                log.warning("Malformed ZeroMQ message (%d frame(s))", len(frames))
                continue
            topic_bytes, payload_bytes = frames[0], frames[1]
            try:
                payload: dict[str, Any] = json.loads(payload_bytes)
            except json.JSONDecodeError as exc:
                log.warning("JSON decode error on topic %s: %s", topic_bytes, exc)
                continue
            handler = self._handlers.get(topic_bytes)
            if handler:
                try:
                    handler(payload)
                except Exception:
                    log.exception("Handler error for topic %s", topic_bytes)
        self._teardown()

    def _status_loop(self) -> None:
        while not self._stopped.is_set():
            self._push(TOPIC_STATUS, {"status": "online",
                                      "node": "microphone",
                                      "adapt_offset": round(self._analyzer.offset_norm, 1),
                                      "dropped_blocks": {"fast": self._dropped[0], "slow": self._dropped[1]},
                                      "audio_xruns": self._capture.xruns})
            if self._stopped.wait(STATUS_PUBLISH_INTERVAL):
                return

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        if self._zmq_push is None:
            return
        try:
            with self._push_lock:
                self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _teardown(self) -> None:
        log.info("Tearing down...")
        self._capture.stop()
        for t in self._threads:
            t.join(timeout=3.0)
        client, self._slow_client = self._slow_client, None
        if client is not None:
            self._safe_close(client)
        self._push(TOPIC_STATUS, {"status": "offline", "node": "microphone"})
        for sock in (self._zmq_sub, self._zmq_push):
            if sock is not None and not sock.closed:
                sock.close(linger=200)
        if self._zmq_ctx is not None:
            self._zmq_ctx.term()
        log.info("Microphone node stopped.")


def _run_with_analyzer(analyzer: LipSyncAnalyzer, device: int | str | None, on_frame: Callable[[LipSyncFrame], None], until: Callable[[], bool], timeout: float | None = None) -> None:
    q: queue.Queue[np.ndarray] = queue.Queue(maxsize=512)
    cap = MicCapture(lambda b: q.put_nowait(b) if not q.full() else None, device)
    cap.start()
    t0 = time.time()
    try:
        while not until() and (timeout is None or time.time() - t0 < timeout):
            try:
                block = q.get(timeout=0.2)
            except queue.Empty:
                continue
            for fr in analyzer.push(block):
                on_frame(fr)
    finally:
        cap.stop()


def run_monitor(device: int | str | None, profile_path: Path) -> None:
    analyzer = LipSyncAnalyzer(Profile.load(profile_path), vol_min=VOL_MIN, vol_max=VOL_MAX)
    print("Ctrl+C to quit. Speak quietly then loudly: set VOL_MIN/VOL_MAX so dB sits near level 0 / 1.")
    stop = threading.Event()
    def on_frame(fr: LipSyncFrame) -> None:
        bar = "#" * int(fr.level * 30)
        w = " ".join(f"{k}:{v:.2f}" for k, v in sorted(fr.weights.items(), key=lambda kv: -kv[1])[:3])
        extra = "".join(f"  <{e['type']} {e.get('vowel') or ''}>" for e in fr.events if e["type"] in ("syllable",))
        sys.stdout.write(f"\r{bar:<30} {fr.db:6.1f} dB  ph={fr.phoneme or '.':<2} fit={fr.fit:.2f} off={analyzer.offset_norm:4.1f}  {w:<28}{extra}   ")
        sys.stdout.flush()
    try:
        _run_with_analyzer(analyzer, device, on_frame, stop.is_set)
    except KeyboardInterrupt:
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="input device index or name substring")
    ap.add_argument("--profile", type=Path, default=PROFILE_PATH)
    ap.add_argument("--monitor", action="store_true")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    device: int | str | None = int(args.device) if args.device and args.device.isdigit() else args.device
    if args.list_devices:
        print(sd.query_devices())
        return
    if args.monitor:
        run_monitor(device, args.profile)
        return
    node = MicrophoneNode(device)
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d — shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
