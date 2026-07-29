from __future__ import annotations
import json
import logging
import signal
import threading
import time
from typing import Any
import zmq
from pynput import keyboard
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] handheld: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("handheld")

ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"
TOPIC_INPUT = b"dynamo/state/handheld-input"

HOLD_THRESHOLD: float = 0.2   # minimum hold duration before a key is "held"
COMBO_WINDOW:   float = 0.4   # maximum gap between two taps to count as a combo
KEY_NAMES: dict[keyboard.Key, str] = {
    keyboard.Key.left:  "left",
    keyboard.Key.right: "right",
    keyboard.Key.up:    "up",
    keyboard.Key.down:  "down",
    keyboard.Key.enter: "enter",
}
TRACKED_KEYS: frozenset[keyboard.Key] = frozenset(KEY_NAMES)


def _make_hold_event(key: str, held: bool) -> dict[str, Any]:
    """Published when a key crosses/drops the hold threshold."""
    return {"type": "hold", "key": key, "held": held, "timestamp": time.time()}


def _make_tap_event(key: str) -> dict[str, Any]:
    """Published on a quick press-and-release that did NOT become a hold."""
    return {"type": "tap", "key": key, "timestamp": time.time()}


def _make_combo_event(key1: str, key2: str) -> dict[str, Any]:
    """Published when two quick taps occur within COMBO_WINDOW of each other."""
    return {"type": "combo", "keys": [key1, key2], "timestamp": time.time()}


class HandheldNode:
    def __init__(self) -> None:
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_push: zmq.Socket | None = None
        self._lock = threading.Lock()
        self._held:       dict[keyboard.Key, bool]  = {}
        self._press_time: dict[keyboard.Key, float] = {}
        self._hold_fired: dict[keyboard.Key, bool]  = {}  # True once hold event sent
        self._combo_buffer: list[tuple[str, float]] = []    # (key_name, release_time)
        self._pending_tap_timers: dict[str, threading.Timer] = {}
        self._kb_listener: keyboard.Listener | None = None

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        self._kb_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._kb_listener.start()
        log.info("Handheld node started. PUSH=%s | topic=%s", ZMQ_PUSH_ADDRESS, TOPIC_INPUT.decode())
        self._hold_poll_loop()

    def stop(self) -> None:
        log.info("Stopping handheld node...")
        self._running.clear()
        if self._kb_listener is not None:
            self._kb_listener.stop()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)
        log.info("ZMQ PUSH connected to %s", ZMQ_PUSH_ADDRESS)

    def _teardown(self) -> None:
        with self._lock:
            for key, is_held in list(self._held.items()): # Fire held=False for any keys still physically held when we shut down
                if is_held and self._hold_fired.get(key):
                    name = KEY_NAMES[key]
                    self._publish(TOPIC_INPUT, _make_hold_event(name, held=False))
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("Handheld node stopped.")

    def _publish(self, topic: bytes, payload: dict[str, Any]) -> None:
        if self._zmq_push is None:
            return
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
            log.debug("PUB %s: %s", topic.decode(), payload)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic.decode())
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic.decode(), exc)

    def _on_press(self, key: keyboard.Key) -> None:
        if key not in TRACKED_KEYS:
            return
        with self._lock:
            if self._held.get(key):
                return   # key repeat -- already tracking
            self._held[key]       = True
            self._press_time[key] = time.time()
            self._hold_fired[key] = False

    def _on_release(self, key: keyboard.Key) -> None:
        if key not in TRACKED_KEYS:
            return
        with self._lock:
            if not self._held.get(key):
                return   # spurious release
            press_time     = self._press_time.get(key, time.time())
            hold_was_fired = self._hold_fired.get(key, False)
            self._held[key]       = False
            self._press_time[key] = 0.0
            self._hold_fired[key] = False
            held_duration = time.time() - press_time
            name = KEY_NAMES[key]
        if hold_was_fired:
            self._publish(TOPIC_INPUT, _make_hold_event(name, held=False))
            return
        if held_duration < HOLD_THRESHOLD:
            self._handle_tap(name)

    def _handle_tap(self, key_name: str) -> None:
        """
        Add this tap to the combo buffer, then:
        - If it completes a 2-key combo -> emit combo immediately.
        - Otherwise start a deferred timer; emit a plain tap only if no second tap arrives before COMBO_WINDOW expires.
        """
        now = time.time()
        self._combo_buffer = [(k, t) for k, t in self._combo_buffer if now - t <= COMBO_WINDOW]
        old_timer = self._pending_tap_timers.pop(key_name, None)
        if old_timer is not None:
            old_timer.cancel()
        if self._combo_buffer:
            prev_key, _ = self._combo_buffer[-1]
            self._combo_buffer.clear()
            prev_timer = self._pending_tap_timers.pop(prev_key, None) # Cancel the deferred tap for the previous key too
            if prev_timer is not None:
                prev_timer.cancel()
            self._publish(TOPIC_INPUT, _make_combo_event(prev_key, key_name))
            return
        self._combo_buffer.append((key_name, now))
        timer = threading.Timer(COMBO_WINDOW, self._emit_deferred_tap, args=[key_name])
        timer.daemon = True
        timer.start()
        self._pending_tap_timers[key_name] = timer

    def _emit_deferred_tap(self, key_name: str) -> None:
        """Called by the COMBO_WINDOW timer if no second tap arrived."""
        self._pending_tap_timers.pop(key_name, None)
        self._combo_buffer = [(k, t) for k, t in self._combo_buffer if k != key_name]
        self._publish(TOPIC_INPUT, _make_tap_event(key_name))

    def _hold_poll_loop(self) -> None:
        """Continuously checks whether any key has been held long enough to cross HOLD_THRESHOLD and fires a hold event exactly once when that threshold is crossed"""
        POLL_INTERVAL = 0.02  # 50 Hz
        try:
            while self._running.is_set():
                now = time.time()
                with self._lock:
                    for key in TRACKED_KEYS:
                        if not self._held.get(key):
                            continue
                        if self._hold_fired.get(key):
                            continue
                        duration = now - self._press_time.get(key, now)
                        if duration >= HOLD_THRESHOLD:
                            self._hold_fired[key] = True
                            name = KEY_NAMES[key]
                            timer = self._pending_tap_timers.pop(name, None)
                            if timer is not None:
                                timer.cancel()
                            self._combo_buffer = [(k, t) for k, t in self._combo_buffer if k != name]
                            self._publish(TOPIC_INPUT, _make_hold_event(name, held=True))
                time.sleep(POLL_INTERVAL)
        finally:
            self._teardown()


def main() -> None:
    node = HandheldNode()
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d -- shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
