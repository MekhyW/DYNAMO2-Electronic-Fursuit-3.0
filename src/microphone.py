from __future__ import annotations
import json
import logging
import signal
import threading
import time
from typing import Any
import zmq
from whisper_live.client import TranscriptionClient
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] microphone: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("microphone")

ZMQ_SUB_ADDRESS: str = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"
STATUS_PUBLISH_INTERVAL: float = 5.0
TOPIC_STATUS = b"dynamo/status/microphone"
TOPIC_TRANSCRIPTION = b"dynamo/data/transcription"


class MicrophoneNode:
    def __init__(self) -> None:
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._whisper_client: TranscriptionClient | None = None
        self._client_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()

        self._start_client()
        threading.Thread(target=self._status_loop, daemon=True, name="microphone-status").start()
        log.info("Microphone node started — SUB=%s PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping Microphone node...")
        self._running.clear()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_sub = self._zmq_ctx.socket(zmq.SUB)
        self._zmq_sub.connect(ZMQ_SUB_ADDRESS)
        self._zmq_sub.setsockopt(zmq.RCVTIMEO, 500)
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)
        log.info("ZeroMQ PUSH connected to %s", ZMQ_PUSH_ADDRESS)

    def _start_client(self) -> None:
        log.info("Initializing TranscriptionClient connecting to localhost:9090...")
        try:
            self._whisper_client = TranscriptionClient("localhost", 9090, model="OpenVINO/whisper-base-fp16-ov", translate=False)
            if hasattr(self._whisper_client, "on_transcription_callback"):
                self._whisper_client.on_transcription_callback = self._on_transcription
            else:
                log.warning("WhisperLive client may not support on_transcription_callback natively. Monkeypatching process_network_message if necessary...")
            self._client_thread = threading.Thread(target=self._run_client_loop, daemon=True, name="whisper-client")
            self._client_thread.start()
        except Exception as exc:
            log.error("Failed to initialize WhisperLive client: %s", exc)

    def _run_client_loop(self) -> None:
        try:
            self._whisper_client() # Running the client without an audio file argument will default to capturing from the microphone
        except Exception as exc:
            log.error("WhisperLive client loop exited with error: %s", exc)

    def _on_transcription(self, text: str) -> None:
        """Callback triggered when the server returns a new transcribed segment."""
        text = (text or "").strip()
        if not text:
            return
        payload = {"text": text, "timestamp": time.time()}
        log.info("Transcribed: %s", text)
        self._push(TOPIC_TRANSCRIPTION, payload)

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
        self._push(TOPIC_STATUS, {"status": "online", "node": "microphone"})
        while self._running.is_set():
            time.sleep(STATUS_PUBLISH_INTERVAL)
            self._push(TOPIC_STATUS, {"status": "online", "node": "microphone"})

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        if self._zmq_push is None:
            return
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _teardown(self) -> None:
        log.info("Tearing down ZMQ connections...")
        self._push(TOPIC_STATUS, {"status": "offline", "node": "microphone"})
        if self._zmq_sub is not None and not self._zmq_sub.closed:
            self._zmq_sub.close(linger=0)
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("Microphone node stopped.")


def main() -> None:
    node = MicrophoneNode()
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d — shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
