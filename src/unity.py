from __future__ import annotations
import json
import logging
import signal
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
import zmq
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] unity: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("unity")

ZMQ_SUB_ADDRESS: str = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"
STATUS_PUBLISH_INTERVAL: float = 5.0
SEND_INTERVAL: float = 0.05

UNITY_HOST: str = "localhost"
UNITY_PORT: int = 50000
TOPIC_STATUS = b"dynamo/status/unity"
TOPIC_FACE_EXPRESSION_TRACKING = b"dynamo/commands/face-expression-tracking-toggle"
TOPIC_EYE_TRACKING = b"dynamo/commands/eye-tracking-toggle"
TOPIC_SET_EXPRESSION = b"dynamo/commands/set-expression"
TOPIC_EYES_BRIGHTNESS = b"dynamo/commands/eyes-brightness"
TOPIC_EYE_STATE = b"dynamo/data/eye-state"
TOPIC_EYES_VIDEO = b"dynamo/eyes-video"
SUBSCRIBED_TOPICS: list[bytes] = [TOPIC_FACE_EXPRESSION_TRACKING, TOPIC_EYE_TRACKING, TOPIC_SET_EXPRESSION, TOPIC_EYES_BRIGHTNESS, TOPIC_EYE_STATE, TOPIC_EYES_VIDEO]
EXPRESSION_INDEX: dict[str, int] = {
    "angry":   0,
    "disgusted": 1,
    "happy": 2,
    "neutral": 3,
    "sad": 4,
    "surprised": 5,
    "hypnotic": 6,
    "heart": 7,
    "rainbow": 8,
    "nightmare": 9,
    "gears": 10,
    "sans": 11,
    "mischievous": 12
}
NUM_EMOTIONS: int = len(EXPRESSION_INDEX)


@dataclass
class UnityState:
    """All mutable state that feeds the Unity send loop."""
    displacement_eye_x: float = 0.0
    displacement_eye_y: float = 0.0
    closeness_left: float = 0.0
    closeness_right: float = 0.0
    emotion_scores: list[float] = field(default_factory=lambda: [0.0] * NUM_EMOTIONS)
    silly_mode: bool = False
    screen_brightness: int = 100
    face_expression_tracking: bool = True
    eye_tracking: bool = True
    manual_expression_id: int = -1
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def build_message(self) -> str:
        with self._lock:
            def _fmt(v: float) -> str:
                return str(v).replace(",", ".")
            disp_x   = _fmt(self.displacement_eye_x)
            disp_y   = _fmt(self.displacement_eye_y)
            cl_left  = _fmt(self.closeness_left)
            cl_right = _fmt(self.closeness_right)
            scores   = ["0" if s < 0.01 else _fmt(s) for s in self.emotion_scores]
            manual_mode = not self.face_expression_tracking
            manual_id   = self.manual_expression_id
            msg  = f"{disp_x} {disp_y} {cl_left} {cl_right} {' '.join(scores)}"
            msg += f" {manual_id}" if (manual_mode and manual_id >= 0) else " -1"
            msg += " 1" if self.silly_mode else " 0"
            msg += f" {self.screen_brightness}"
            return msg


class UnityNode:
    def __init__(self) -> None:
        self._state = UnityState()
        self._running = threading.Event()
        self._zmq_ctx:  zmq.Context | None = None
        self._zmq_sub:  zmq.Socket  | None = None
        self._zmq_push: zmq.Socket  | None = None
        self._sock:      socket.socket | None = None
        self._sock_lock: threading.Lock = threading.Lock()
        self._handlers: dict[bytes, Callable[[dict[str, Any]], None]] = {
            TOPIC_FACE_EXPRESSION_TRACKING: self._handle_face_expression_tracking,
            TOPIC_EYE_TRACKING:              self._handle_eye_tracking,
            TOPIC_SET_EXPRESSION:            self._handle_set_expression,
            TOPIC_EYES_BRIGHTNESS:           self._handle_eyes_brightness,
            TOPIC_EYE_STATE:                 self._handle_eye_state,
            TOPIC_EYES_VIDEO:                self._handle_eyes_video,
        }

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        self._connect_unity()
        threading.Thread(target=self._status_loop, daemon=True, name="unity-status").start()
        threading.Thread(target=self._send_loop,   daemon=True, name="unity-send").start()
        log.info("Unity node started — SUB=%s PUSH=%s Unity=%s:%d", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS, UNITY_HOST, UNITY_PORT,)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping Unity node...")
        self._running.clear()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_sub = self._zmq_ctx.socket(zmq.SUB)
        self._zmq_sub.connect(ZMQ_SUB_ADDRESS)
        self._zmq_sub.setsockopt(zmq.RCVTIMEO, 500)
        for topic in SUBSCRIBED_TOPICS:
            self._zmq_sub.setsockopt(zmq.SUBSCRIBE, topic)
            log.info("Subscribed to ZeroMQ topic: %s", topic.decode())
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)
        log.info("ZeroMQ PUSH connected to %s", ZMQ_PUSH_ADDRESS)

    def _connect_unity(self) -> bool:
        with self._sock_lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((UNITY_HOST, UNITY_PORT))
                self._sock = s
                log.info("Unity app connected at %s:%d", UNITY_HOST, UNITY_PORT)
                return True
            except ConnectionRefusedError:
                log.warning("Unity app connection refused — is the app running?")
            except OSError as exc:
                log.warning("Unity connection error: %s", exc)
            return False

    def _send_loop(self) -> None:
        while self._running.is_set():
            self._send_state()
            time.sleep(SEND_INTERVAL)

    def _send_state(self) -> None:
        message = self._state.build_message()
        with self._sock_lock:
            if self._sock is None:
                return
            try:
                self._sock.sendall(message.encode())
                response = self._sock.recv(1024).decode()
                if "Invalid message format!" in response:
                    log.error("Unity reported invalid message format: %s", message)
            except OSError as exc:
                log.warning("Unity send error: %s — reconnecting", exc)
                self._sock = None
        if self._sock is None:
            self._connect_unity() #reconnect outside the lock so the lock isn't held during blocking connect

    def _send_video_command(self, message: str) -> None:
        with self._sock_lock:
            if self._sock is None:
                log.warning("Unity not connected — dropping video command: %s", message)
                return
            try:
                self._sock.sendall(message.encode())
                response = self._sock.recv(1024).decode()
                log.info("Video command response: %s", response.strip())
            except OSError as exc:
                log.warning("Unity video send error: %s", exc)
                self._sock = None

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
        self._push(TOPIC_STATUS, {"status": "online", "node": "unity"})
        while self._running.is_set():
            time.sleep(STATUS_PUBLISH_INTERVAL)
            self._push(TOPIC_STATUS, {"status": "online", "node": "unity"})

    def _handle_face_expression_tracking(self, payload: dict[str, Any]) -> None:
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            log.warning("face-expression-tracking-toggle: missing/invalid 'enabled' field")
            return
        with self._state._lock:
            self._state.face_expression_tracking = enabled
        log.info("Face expression tracking: %s", "enabled" if enabled else "disabled")

    def _handle_eye_tracking(self, payload: dict[str, Any]) -> None:
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            log.warning("eye-tracking-toggle: missing/invalid 'enabled' field")
            return
        with self._state._lock:
            self._state.eye_tracking = enabled
        log.info("Eye tracking: %s", "enabled" if enabled else "disabled")

    def _handle_set_expression(self, payload: dict[str, Any]) -> None:
        expression = payload.get("expression", "").lower()
        idx = EXPRESSION_INDEX.get(expression)
        if idx is None:
            log.warning("set-expression: unknown expression '%s'", expression)
            return
        scores = [0.0] * NUM_EMOTIONS
        scores[idx] = 1.0
        with self._state._lock:
            self._state.emotion_scores = scores
            self._state.manual_expression_id = idx
        log.info("Expression set to '%s' (index %d)", expression, idx)

    def _handle_eyes_brightness(self, payload: dict[str, Any]) -> None:
        brightness = payload.get("brightness")
        if brightness is None or not isinstance(brightness, (int, float)):
            log.warning("eyes-brightness: missing/invalid 'brightness' field")
            return
        brightness = max(0, min(100, int(brightness)))
        with self._state._lock:
            self._state.screen_brightness = brightness
        log.info("Eyes brightness set to %d", brightness)

    def _handle_eye_state(self, payload: dict[str, Any]) -> None:
        with self._state._lock:
            if "displacement_x" in payload:
                self._state.displacement_eye_x = float(payload["displacement_x"])
            if "displacement_y" in payload:
                self._state.displacement_eye_y = float(payload["displacement_y"])
            if "closeness_left" in payload:
                self._state.closeness_left = float(payload["closeness_left"])
            if "closeness_right" in payload:
                self._state.closeness_right = float(payload["closeness_right"])
            scores = payload.get("emotion_scores")
            if isinstance(scores, list) and len(scores) == NUM_EMOTIONS:
                self._state.emotion_scores = [float(s) for s in scores]
            if "silly_mode" in payload:
                self._state.silly_mode = bool(payload["silly_mode"])

    def _handle_eyes_video(self, payload: dict[str, Any]) -> None:
        url = payload.get("url", "").strip()
        if not url:
            log.warning("eyes-video: missing 'url' field")
            return
        message = "VIDEO STOP" if url.lower() == "stop" else f"VIDEO PLAY {url}"
        log.info("Sending video command: %s", message)
        self._send_video_command(message)

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
        log.info("Tearing down connections...")
        self._push(TOPIC_STATUS, {"status": "offline", "node": "unity"})
        with self._sock_lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
        if self._zmq_sub is not None and not self._zmq_sub.closed:
            self._zmq_sub.close(linger=0)
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("Unity node stopped.")


def main() -> None:
    node = UnityNode()
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d — shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
