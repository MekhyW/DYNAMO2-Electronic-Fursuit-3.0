from __future__ import annotations
import argparse
import json
import logging
import math
import os
import signal
import sys
import threading
from typing import Any
import numpy as np
import sounddevice as sd
import zmq
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] desktop_audio: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("desktop_audio")

ZMQ_PUSH_ADDRESS: str = os.getenv("ZMQ_PUSH_ADDRESS", "tcp://localhost:5556")
STATUS_PUBLISH_INTERVAL: float = 5.0
TOPIC_FFT = b"dynamo/data/fft"
TOPIC_STATUS = b"dynamo/status/desktop_audio"

SAMPLE_RATE: int = 44100          # WASAPI loopback delivers the device's native rate
HOP: int = 882                    # ~20 ms at 44.1 kHz  -> ~50 packets/s
WINDOW: int = 4096                # FFT window (~93 ms, good freq resolution)
N_BANDS: int = 16                 # Must match WLED's GEQ band count
_EPS: float = 1e-12               # Small epsilon to avoid division by zero.
PEAK_THRESHOLD: float = 0.55      # Peak detection: fire when the smoothed energy rises above PEAK_THRESHOLD after falling below PEAK_RESET.
PEAK_RESET: float = 0.30          # Reset threshold for peak detection.
_ATTACK_ALPHA: float = 0.85       # fast attack for smoothing
_RELEASE_ALPHA: float = 0.15      # slower release for smoothing


def _mel_edges(n_bands: int, sr: int, f_min: float = 20.0, f_max: float | None = None) -> np.ndarray:
    """Return ``n_bands + 2`` linearly-spaced Mel-scale frequency edges in Hz."""
    if f_max is None:
        f_max = sr / 2.0
    mel_min = 1127.0 * math.log(f_min / 700.0 + 1.0)
    mel_max = 1127.0 * math.log(f_max / 700.0 + 1.0)
    mels = np.linspace(mel_min, mel_max, n_bands + 2)
    return 700.0 * (np.exp(mels / 1127.0) - 1.0)


def _band_indices(n_fft: int, sr: int, n_bands: int) -> list[tuple[int, int]]:
    """Return FFT bin index ranges for each Mel band."""
    edges = _mel_edges(n_bands, sr)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    indices: list[tuple[int, int]] = []
    for k in range(n_bands):
        lo = int(np.searchsorted(freqs, edges[k]))
        hi = int(np.searchsorted(freqs, edges[k + 1]))
        if hi <= lo:
            hi = lo + 1
        indices.append((lo, min(hi, len(freqs) - 1)))
    return indices


class FFTBandAnalyzer:
    """Continuously accumulates audio samples and emits band-energy packets."""
    def __init__(self, sr: int = SAMPLE_RATE, n_fft: int = WINDOW, n_bands: int = N_BANDS) -> None:
        self._sr = sr
        self._n_fft = n_fft
        self._n_bands = n_bands
        self._band_idx = _band_indices(n_fft, sr, n_bands)
        self._window = np.hanning(n_fft).astype(np.float32)
        self._buf = np.zeros(0, dtype=np.float32)
        self._smooth = np.zeros(n_bands, dtype=np.float64)
        self._energy_smooth: float = 0.0
        self._peak_armed: bool = True
        self._max_energy_seen: float = _EPS    # running max for normalisation

    def push(self, block: np.ndarray) -> list[dict[str, Any]]:
        """Feed ``block`` (mono float32) and return a list of FFT payloads."""
        self._buf = np.concatenate((self._buf, block.astype(np.float32, copy=False)))
        results: list[dict[str, Any]] = []
        while self._buf.size >= self._n_fft:
            frame = self._buf[: self._n_fft]
            self._buf = self._buf[HOP:]
            results.append(self._process(frame))
        return results

    def _process(self, frame: np.ndarray) -> dict[str, Any]:
        windowed = frame * self._window
        spectrum = np.abs(np.fft.rfft(windowed, n=self._n_fft)) ** 2  # power spectrum
        raw_bands = np.array([spectrum[lo:hi].mean() if hi > lo else 0.0 for lo, hi in self._band_idx], dtype=np.float64) # per-band energies (mean power in each Mel bin)
        peak_power = float(raw_bands.max())
        self._max_energy_seen = max(self._max_energy_seen * 0.9995, peak_power, _EPS) # track max for normalisation (slow-decaying)
        norm_bands = raw_bands / self._max_energy_seen
        alpha = np.where(norm_bands > self._smooth, _ATTACK_ALPHA, _RELEASE_ALPHA)
        self._smooth = self._smooth + alpha * (norm_bands - self._smooth)
        bands_out = list(np.clip(self._smooth, 0.0, 1.0))
        energy = float(np.mean(self._smooth))
        self._energy_smooth += (0.8 if energy > self._energy_smooth else 0.2) * (energy - self._energy_smooth)
        energy_out = float(np.clip(self._energy_smooth, 0.0, 1.0)) # overall energy (smoothed mean of bands)
        peak_bin = int(np.argmax(spectrum)) # dominant frequency peak
        freqs = np.fft.rfftfreq(self._n_fft, d=1.0 / self._sr)
        major_peak_hz = float(freqs[peak_bin])
        magnitude = float(np.clip(spectrum[peak_bin] / self._max_energy_seen, 0.0, 1.0))
        is_peak = False
        if self._peak_armed and energy_out >= PEAK_THRESHOLD:
            is_peak = True
            self._peak_armed = False
        elif not self._peak_armed and energy_out < PEAK_RESET:
            self._peak_armed = True
        return {
            "bands": [round(v, 4) for v in bands_out],
            "energy": round(energy_out, 4),
            "magnitude": round(magnitude, 4),
            "major_peak": round(major_peak_hz, 2),
            "peak": is_peak,
        }


def _find_loopback_device(hint: int | str | None = None) -> int | str | None:
    """Return the best WASAPI loopback device index."""
    if hint is not None:
        return hint
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            name_lower = dev["name"].lower()
            if "loopback" in name_lower or "stereo mix" in name_lower:
                if dev["max_input_channels"] > 0:
                    log.info("Auto-selected loopback device %d: %s", i, dev["name"])
                    return i
    except Exception as exc:
        log.debug("Device query failed: %s", exc)
    return None


class DesktopAudioNode:
    """Captures desktop audio and publishes FFT packets over ZeroMQ."""
    def __init__(self, device: int | str | None = None) -> None:
        self._device = device
        self._running = threading.Event()
        self._stop_event = threading.Event()
        self._push_lock = threading.Lock()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_push: zmq.Socket | None = None
        self._analyzer = FFTBandAnalyzer()
        self._stream: Any = None
        self._dropped: int = 0
        self._packets_sent: int = 0

    def start(self) -> None:
        self._running.set()
        self._stop_event.clear()
        self._setup_zmq()
        self._start_capture()
        threading.Thread(target=self._status_loop, daemon=True, name="desktop-audio-status").start()
        log.info("Desktop audio node started. PUSH=%s", ZMQ_PUSH_ADDRESS)
        try:
            while not self._stop_event.wait(timeout=0.2):
                pass
        except KeyboardInterrupt:
            self.stop()
        self._teardown()

    def stop(self) -> None:
        log.info("Stopping desktop audio node...")
        self._running.clear()
        self._stop_event.set()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)
        log.info("ZeroMQ PUSH connected to %s", ZMQ_PUSH_ADDRESS)

    def _start_capture(self) -> None:
        device = _find_loopback_device(self._device)
        self._stream = None
        try:
            extra_settings = sd.WasapiSettings(exclusive=False, loopback=True)  # type: ignore[call-arg]
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=HOP, device=device, extra_settings=extra_settings, callback=self._audio_callback)
            log.info("Using WASAPI loopback (device=%s, %d Hz)", device, SAMPLE_RATE)
        except (TypeError, AttributeError, Exception):
            pass
        if self._stream is None:
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=HOP, device=device, callback=self._audio_callback,)
            log.info("Using audio capture (device=%s, %d Hz)", device, SAMPLE_RATE)
        self._stream.start()

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            self._dropped += 1
        mono = indata[:, 0].copy()
        try:
            for payload in self._analyzer.push(mono):
                self._publish(payload)
        except Exception as exc:
            log.debug("FFT callback error: %s", exc)

    def _publish(self, payload: dict[str, Any]) -> None:
        if self._zmq_push is None:
            return
        try:
            with self._push_lock:
                self._zmq_push.send_multipart([TOPIC_FFT, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
            self._packets_sent += 1
        except zmq.Again:
            pass
        except zmq.ZMQError as exc:
            log.error("PUSH error: %s", exc)

    def _status_loop(self) -> None:
        while not self._stop_event.is_set():
            self._publish_raw(TOPIC_STATUS, {"status": "online", "node": "desktop_audio", "packets_sent": self._packets_sent, "dropped_blocks": self._dropped})
            if self._stop_event.wait(STATUS_PUBLISH_INTERVAL):
                break
        self._publish_raw(TOPIC_STATUS, {"status": "offline", "node": "desktop_audio"})

    def _publish_raw(self, topic: bytes, payload: dict[str, Any]) -> None:
        if self._zmq_push is None:
            return
        try:
            with self._push_lock:
                self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except (zmq.Again, zmq.ZMQError):
            pass

    def _teardown(self) -> None:
        log.info("Tearing down desktop audio node...")
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=200)
        if self._zmq_ctx is not None:
            self._zmq_ctx.term()
        log.info("Desktop audio node stopped.")


def run_monitor(device: int | str | None) -> None:
    """Pretty-print live FFT bars in the terminal (does not publish to ZMQ)."""
    analyzer = FFTBandAnalyzer()
    def on_block(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        mono = indata[:, 0]
        for p in analyzer.push(mono.copy()):
            bar = "".join(("#" if v > 0.5 else ":" if v > 0.15 else ".") for v in p["bands"])
            peak_marker = " *** PEAK" if p["peak"] else ""
            sys.stdout.write(f"\r[{bar}] vol={p['energy']:.2f} peak={p['major_peak']:6.0f} Hz{peak_marker}   ")
            sys.stdout.flush()
    dev = _find_loopback_device(device)
    stream = None
    try:
        extra = sd.WasapiSettings(exclusive=False, loopback=True)  # type: ignore[call-arg]
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=HOP, device=dev, extra_settings=extra, callback=on_block)
    except (TypeError, AttributeError, Exception):
        pass
    if stream is None:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=HOP, device=dev, callback=on_block)
    print("Monitoring desktop audio -- Ctrl+C to quit")
    stop_event = threading.Event()
    with stream:
        try:
            while not stop_event.wait(timeout=0.2):
                pass
        except KeyboardInterrupt:
            print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="Input device index or name substring (leave blank for WASAPI loopback auto-detect)")
    ap.add_argument("--list-devices", action="store_true", help="Print available audio devices and exit")
    ap.add_argument("--monitor", action="store_true", help="Print live FFT bars in the terminal (does not publish)")
    args = ap.parse_args()
    device: int | str | None = None
    if args.device:
        device = int(args.device) if args.device.isdigit() else args.device
    if args.list_devices:
        print(sd.query_devices())
        return
    if args.monitor:
        run_monitor(device)
        return
    node = DesktopAudioNode(device)
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d -- shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()


if __name__ == "__main__":
    main()
