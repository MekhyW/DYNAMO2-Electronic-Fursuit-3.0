import os
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List
import pygame
from elevenlabs import ElevenLabs, VoiceSettings
import tempfile
import zmq
from dotenv import load_dotenv
load_dotenv("../.env")

ZMQ_SUB_ADDRESS: str = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"
STATUS_PUBLISH_INTERVAL: float = 10.0     

TOPIC_STATUS = b"dynamo/status/audio_sfx"
TOPIC_PLAY_SOUND_EFFECT = b"dynamo/commands/play-sound-effect"
TOPIC_TEXT_TO_SPEECH = b"dynamo/commands/text-to-speech"
SUBSCRIBED_TOPICS: List[bytes] = [TOPIC_PLAY_SOUND_EFFECT, TOPIC_TEXT_TO_SPEECH]

SFX_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".", "sfx"))

log = logging.getLogger("audio_sfx")
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler())

class AudioSFXNode:
    def __init__(self) -> None:
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._handlers: Dict[bytes, Callable[[Dict[str, Any]], None]] = {
            TOPIC_PLAY_SOUND_EFFECT: self._handle_play_sound_effect,
            TOPIC_TEXT_TO_SPEECH: self._handle_text_to_speech,
        }
        pygame.mixer.init()
        self._catalogue: List[Dict[str, str]] = []
        self._load_sound_catalogue()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_sub = self._zmq_ctx.socket(zmq.SUB)
        self._zmq_sub.connect(ZMQ_SUB_ADDRESS)
        self._zmq_sub.setsockopt(zmq.RCVTIMEO, 500)
        for topic in SUBSCRIBED_TOPICS:
            self._zmq_sub.setsockopt(zmq.SUBSCRIBE, topic)
            log.info("Subscribed to ZMQ topic: %s", topic.decode())
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)

    def _push(self, topic: bytes, payload: Any) -> None:
        if not self._zmq_push:
            return
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _load_sound_catalogue(self) -> None:
        if not os.path.isdir(SFX_ROOT):
            log.warning("SFX root directory does not exist: %s", SFX_ROOT)
            return
        for root, _, files in os.walk(SFX_ROOT):
            for f in files:
                if f.lower().endswith((".wav", ".mp3", ".ogg")):
                    rel_path = os.path.relpath(os.path.join(root, f), SFX_ROOT)
                    name = os.path.splitext(f)[0]
                    self._catalogue.append({"name": name, "filename": rel_path})
        self._catalogue.sort(key=lambda x: x["name"].lower())
        log.info("Loaded %d sound-effect files", len(self._catalogue))

    def _resolve_effect_path(self, effect_id: Any) -> str | None:
        """Resolve ``effect_id`` to an absolute file path. It may be:
        * an integer index into the catalogue
        * the exact filename (case-insensitive)
        * the plain name (without extension) - the first matching entry is used
        """
        if effect_id is None:
            return None
        if isinstance(effect_id, int):
            if 0 <= effect_id < len(self._catalogue):
                return os.path.abspath(os.path.join(SFX_ROOT, self._catalogue[effect_id]["filename"]))
            return None
        if isinstance(effect_id, str):
            for entry in self._catalogue:
                if entry["filename"].lower() == effect_id.lower():
                    return os.path.abspath(os.path.join(SFX_ROOT, entry["filename"]))
            for entry in self._catalogue:
                stem = os.path.splitext(entry["filename"])[0]
                if stem.lower() == effect_id.lower():
                    return os.path.abspath(os.path.join(SFX_ROOT, entry["filename"]))
        return None

    def _handle_play_sound_effect(self, payload: Dict[str, Any]) -> None:
        effect_id = payload.get("effectId")
        if effect_id == "stop":
            log.info("Stopping all sound-effects")
            pygame.mixer.stop()
            return
        path = self._resolve_effect_path(effect_id)
        if not path:
            log.warning("Could not resolve sound-effect ID: %s", effect_id)
            return
        if not os.path.isfile(path):
            log.error("Resolved path does not exist: %s", path)
            return
        try:
            sound = pygame.mixer.Sound(path)
            sound.play()
            log.info("Playing sound-effect %s", path)
        except Exception as e:
            log.exception("Failed to play sound-effect %s: %s", path, e)

    def _handle_text_to_speech(self, payload: Dict[str, Any]) -> None:
        """Generate speech via ElevenLabs and play it using pygame mixer."""
        text = payload.get("text")
        if not text:
            log.warning("text-to-speech payload missing 'text'")
            return
        api_key = os.getenv("eleven_api_key")
        try:
            client = ElevenLabs(api_key=api_key)
            voice_settings = VoiceSettings(stability=0.3, similarity_boost=1.0, style=0.0, speed=1.1, use_speaker_boost=True)
            audio_stream = client.text_to_speech.convert(text=text, voice_id="Rb9J9nOjoNgGbjJUN5wt", voice_settings=voice_settings, model_id="eleven_multilingual_v2", output_format="mp3_44100_128")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
                for chunk in audio_stream:
                    if chunk:
                        tmp_file.write(chunk)
                temp_path = tmp_file.name
            sound = pygame.mixer.Sound(temp_path)
            sound.play()
            log.info("Played TTS audio for text: %s", text[:30])
            def _cleanup():
                # Wait for the sound to finish playing, then delete the temporary file.
                # Adding a small safety margin ensures the file isn't removed before playback ends.
                time.sleep(sound.get_length() + 0.1)
                try:
                    os.remove(temp_path)
                    log.info("Deleted temporary TTS file %s", temp_path)
                except OSError as exc:
                    log.warning("Failed to delete temporary TTS file %s: %s", temp_path, exc)
            threading.Thread(target=_cleanup, daemon=True).start()
        except Exception as exc:
            log.exception("Error generating or playing TTS audio: %s", exc)

    def _status_loop(self) -> None:
        while self._running.is_set():
            self._push(TOPIC_STATUS, {"status": "online", "node": "audio_sfx"})
            time.sleep(STATUS_PUBLISH_INTERVAL)

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
                log.warning("Malformed ZeroMQ message (%d frames)", len(frames))
                continue
            topic, payload_bytes = frames[0], frames[1]
            try:
                payload = json.loads(payload_bytes)
            except json.JSONDecodeError as exc:
                log.warning("JSON decode error on topic %s: %s", topic, exc)
                continue
            handler = self._handlers.get(topic)
            if handler:
                try:
                    handler(payload)
                except Exception:
                    log.exception("Handler error for topic %s", topic)
        self._teardown()

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        threading.Thread(target=self._status_loop, daemon=True, name="audio-sfx-status").start()
        log.info("Audio SFX node started – SUB=%s PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping Audio SFX node…")
        self._running.clear()

    def _teardown(self) -> None:
        log.info("Tearing down ZMQ sockets…")
        if self._zmq_sub and not self._zmq_sub.closed:
            self._zmq_sub.close(linger=0)
        if self._zmq_push and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx:
            self._zmq_ctx.destroy(linger=0)
        pygame.mixer.quit()
        log.info("Audio SFX node stopped.")

def main() -> None:
    node = AudioSFXNode()
    import signal
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d – shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
