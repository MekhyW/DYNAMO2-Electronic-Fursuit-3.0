from __future__ import annotations
import json
import logging
import signal
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
import zmq
from dotenv import load_dotenv
load_dotenv("../.env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] actuators: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("actuators")

ZMQ_SUB_ADDRESS:  str = "tcp://localhost:5555"   # connect to mqttbridge PUB bus
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"   # connect to mqttbridge PULL socket
STATUS_PUBLISH_INTERVAL:     float = 5.0          # seconds between status pushes

TOPIC_STATUS       = b"dynamo/status/actuators"
TOPIC_STATE_SERVO  = b"dynamo/state/servo"
TOPIC_MOVE_EAR      = b"dynamo/commands/move-ear"
TOPIC_MOVE_EYEBROW  = b"dynamo/commands/move-eyebrow"
TOPIC_MOVE_MUZZLE   = b"dynamo/commands/move-muzzle"
TOPIC_SET_POSE      = b"dynamo/commands/set-pose"
SUBSCRIBED_TOPICS: list[bytes] = [TOPIC_MOVE_EAR, TOPIC_MOVE_EYEBROW, TOPIC_MOVE_MUZZLE, TOPIC_SET_POSE]

class ServoId(str, Enum):
    EAR_LEFT      = "ear_left"
    EAR_RIGHT     = "ear_right"
    EYEBROW_LEFT  = "eyebrow_left"
    EYEBROW_RIGHT = "eyebrow_right"
    MUZZLE        = "muzzle"

SERVO_LIMITS: dict[ServoId, tuple[int, int]] = {
    ServoId.EAR_LEFT:      (0,   180),
    ServoId.EAR_RIGHT:     (0,   180),
    ServoId.EYEBROW_LEFT:  (30,  150),
    ServoId.EYEBROW_RIGHT: (30,  150),
    ServoId.MUZZLE:        (0,   90),
}

SERVO_DEFAULTS: dict[ServoId, float] = {
    ServoId.EAR_LEFT:      0.5,
    ServoId.EAR_RIGHT:     0.5,
    ServoId.EYEBROW_LEFT:  0.5,
    ServoId.EYEBROW_RIGHT: 0.5,
    ServoId.MUZZLE:        0.0,
}

POSE_MACROS: dict[str, dict[ServoId, float]] = {
    "neutral": {
        ServoId.EAR_LEFT:      0.5,
        ServoId.EAR_RIGHT:     0.5,
        ServoId.EYEBROW_LEFT:  0.5,
        ServoId.EYEBROW_RIGHT: 0.5,
        ServoId.MUZZLE:        0.0,
    },
    "happy": {
        ServoId.EAR_LEFT:      0.85,
        ServoId.EAR_RIGHT:     0.85,
        ServoId.EYEBROW_LEFT:  0.4,
        ServoId.EYEBROW_RIGHT: 0.4,
        ServoId.MUZZLE:        0.6,
    },
    "sad": {
        ServoId.EAR_LEFT:      0.2,
        ServoId.EAR_RIGHT:     0.2,
        ServoId.EYEBROW_LEFT:  0.7,
        ServoId.EYEBROW_RIGHT: 0.7,
        ServoId.MUZZLE:        0.2,
    },
    "angry": {
        ServoId.EAR_LEFT:      0.3,
        ServoId.EAR_RIGHT:     0.3,
        ServoId.EYEBROW_LEFT:  0.85,
        ServoId.EYEBROW_RIGHT: 0.85,
        ServoId.MUZZLE:        0.0,
    },
    "excited": {
        ServoId.EAR_LEFT:      1.0,
        ServoId.EAR_RIGHT:     1.0,
        ServoId.EYEBROW_LEFT:  0.3,
        ServoId.EYEBROW_RIGHT: 0.3,
        ServoId.MUZZLE:        0.8,
    },
    "surprised": {
        ServoId.EAR_LEFT:      0.9,
        ServoId.EAR_RIGHT:     0.9,
        ServoId.EYEBROW_LEFT:  0.2,
        ServoId.EYEBROW_RIGHT: 0.2,
        ServoId.MUZZLE:        0.5,
    },
    "tired": {
        ServoId.EAR_LEFT:      0.15,
        ServoId.EAR_RIGHT:     0.15,
        ServoId.EYEBROW_LEFT:  0.6,
        ServoId.EYEBROW_RIGHT: 0.6,
        ServoId.MUZZLE:        0.0,
    },
}

@dataclass
class ActuatorState:
    """Mutable servo state maintained by the node."""
    positions: dict[ServoId, float] = field(default_factory=lambda: dict(SERVO_DEFAULTS))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set(self, servo: ServoId, position: float) -> None:
        position = max(0.0, min(1.0, float(position)))
        with self._lock:
            self.positions[servo] = position

    def set_pose(self, pose: dict[ServoId, float]) -> None:
        with self._lock:
            for servo, position in pose.items():
                self.positions[servo] = max(0.0, min(1.0, float(position)))

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {s.value: p for s, p in self.positions.items()}


def normalised_to_angle(servo: ServoId, normalised: float) -> int:
    lo, hi = SERVO_LIMITS[servo]
    return round(lo + normalised * (hi - lo))

def build_servo_command(servo: ServoId, position: float) -> dict[str, Any]:
    return {
        "servo": servo.value,
        "angle": normalised_to_angle(servo, position),
        "position": position,
    }

def parse_side(payload: dict[str, Any], key: str = "side") -> str | None:
    side = payload.get(key, "").lower()
    if side not in ("left", "right", "both"):
        log.warning("Invalid side value: %r -- expected 'left', 'right', or 'both'", side)
        return None
    return side


class ActuatorsNode:
    """Main actuator node"""
    def __init__(self) -> None:
        self._state = ActuatorState()
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub:  zmq.Socket | None = None   # SUB — receives commands from PUB bus
        self._zmq_push: zmq.Socket | None = None   # PUSH — sends outbound messages to bridge
        self._handlers: dict[bytes, Callable[[dict[str, Any]], None]] = {
            TOPIC_MOVE_EAR:     self._handle_move_ear,
            TOPIC_MOVE_EYEBROW: self._handle_move_eyebrow,
            TOPIC_MOVE_MUZZLE:  self._handle_move_muzzle,
            TOPIC_SET_POSE:     self._handle_set_pose,
        }

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        threading.Thread(target=self._status_loop, daemon=True, name="status-loop").start()
        log.info("Actuators node started. SUB=%s  PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping actuators node...")
        self._running.clear()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_sub = self._zmq_ctx.socket(zmq.SUB)
        self._zmq_sub.connect(ZMQ_SUB_ADDRESS)
        self._zmq_sub.setsockopt(zmq.RCVTIMEO, 500)  # ms -- allows clean shutdown polling
        for topic in SUBSCRIBED_TOPICS:
            self._zmq_sub.setsockopt(zmq.SUBSCRIBE, topic)
            log.info("Subscribed to ZeroMQ topic: %s", topic.decode())
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)
        log.info("ZeroMQ PUSH connected to %s", ZMQ_PUSH_ADDRESS)

    def _event_loop(self) -> None:
        assert self._zmq_sub is not None, "ZeroMQ socket not initialised"
        while self._running.is_set():
            try:
                frames = self._zmq_sub.recv_multipart()
            except zmq.Again:
                continue   # RCVTIMEO expired -- check _running and loop
            except zmq.ZMQError as exc:
                if self._running.is_set():
                    log.error("ZeroMQ receive error: %s", exc)
                break
            if len(frames) < 2:
                log.warning("Received malformed ZeroMQ message (%d frame(s))", len(frames))
                continue
            topic_bytes, payload_bytes = frames[0], frames[1]
            try:
                payload: dict[str, Any] = json.loads(payload_bytes)
            except json.JSONDecodeError as exc:
                log.warning("Could not decode JSON payload on topic %s: %s", topic_bytes, exc)
                continue
            handler = self._handlers.get(topic_bytes)
            if handler is None:
                log.debug("No handler for topic %s", topic_bytes)
                continue
            try:
                handler(payload)
            except Exception as exc:  # noqa: BLE001
                log.exception("Handler error for topic %s: %s", topic_bytes, exc)
        self._teardown()

    def _handle_move_ear(self, payload: dict[str, Any]) -> None:
        side = parse_side(payload)
        if side is None:
            return
        position = payload.get("position")
        if position is None:
            log.warning("move-ear: missing 'position' field")
            return
        servos: list[ServoId] = []
        if side in ("left", "both"):
            servos.append(ServoId.EAR_LEFT)
        if side in ("right", "both"):
            servos.append(ServoId.EAR_RIGHT)
        for servo in servos:
            self._apply_servo(servo, position)
        log.info("move-ear: side=%s position=%.3f", side, position)

    def _handle_move_eyebrow(self, payload: dict[str, Any]) -> None:
        side = parse_side(payload)
        if side is None:
            return
        position = payload.get("position")
        if position is None:
            log.warning("move-eyebrow: missing 'position' field")
            return
        servos: list[ServoId] = []
        if side in ("left", "both"):
            servos.append(ServoId.EYEBROW_LEFT)
        if side in ("right", "both"):
            servos.append(ServoId.EYEBROW_RIGHT)
        for servo in servos:
            self._apply_servo(servo, position)
        log.info("move-eyebrow: side=%s position=%.3f", side, position)

    def _handle_move_muzzle(self, payload: dict[str, Any]) -> None:
        position = payload.get("position")
        if position is None:
            log.warning("move-muzzle: missing 'position' field")
            return
        self._apply_servo(ServoId.MUZZLE, position)
        log.info("move-muzzle: position=%.3f", position)

    def _handle_set_pose(self, payload: dict[str, Any]) -> None:
        expression: str | None = payload.get("expression")
        if expression is None: # Fallback: derive dominant expression from scores dict
            scores: dict[str, float] = payload.get("scores", {})
            if scores:
                expression = max(scores, key=lambda k: scores[k])
        if not expression:
            log.warning("expression: could not determine expression from payload")
            return
        macro = POSE_MACROS.get(expression.lower())
        if macro is None:
            log.debug("expression: no pose macro for '%s' -- ignoring", expression)
            return
        self._apply_pose(macro)
        log.info("expression: applied macro '%s'", expression)

    def _apply_servo(self, servo: ServoId, position: float) -> None:
        self._state.set(servo, position)
        command = build_servo_command(servo, self._state.positions[servo])
        self._push(TOPIC_STATE_SERVO, command)

    def _apply_pose(self, pose: dict[ServoId, float]) -> None:
        self._state.set_pose(pose)
        for servo, position in pose.items():
            command = build_servo_command(servo, self._state.positions[servo])
            self._push(TOPIC_STATE_SERVO, command)

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        assert self._zmq_push is not None
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _push_status(self, online: bool) -> None:
        self._push(TOPIC_STATUS, {"status": "online" if online else "offline", "node": "actuators"})

    def _status_loop(self) -> None:
        self._push_status(online=True)
        while self._running.is_set(): # Periodically push the node status heartbeat to the bridge
            time.sleep(STATUS_PUBLISH_INTERVAL)
            self._push_status(online=True)

    def _teardown(self) -> None:
        log.info("Tearing down connections...")
        self._push_status(online=False)
        if self._zmq_sub is not None and not self._zmq_sub.closed:
            self._zmq_sub.close(linger=0)
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("Actuators node stopped.")


def main() -> None:
    node = ActuatorsNode()
    def _handle_signal(signum: int, frame: Any) -> None:
        log.info("Received signal %d -- shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
