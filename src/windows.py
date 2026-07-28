from __future__ import annotations
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any
import psutil
from ctypes import POINTER, cast
from comtypes import CLSCTX_ALL
import comtypes
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import zmq
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] windows: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("windows")

ZMQ_SUB_ADDRESS: str = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"
STATUS_PUBLISH_INTERVAL: float = 5.0
DEVICE_PUBLISH_INTERVAL: float = 15.0

TOPIC_STATUS = b"dynamo/status/windows"
TOPIC_SOUND_DEVICES = b"dynamo/data/sound_devices"
TOPIC_OUTPUT_VOLUME = b"dynamo/state/output-volume"
TOPIC_SET_OUTPUT_VOLUME = b"dynamo/commands/set-output-volume"
TOPIC_SHUTDOWN = b"dynamo/commands/shutdown"
TOPIC_REBOOT = b"dynamo/commands/reboot"
TOPIC_KILL_SOFTWARE = b"dynamo/commands/kill-software"
TOPIC_SET_SOUND_DEVICE = b"dynamo/commands/set-sound-device"
SUBSCRIBED_TOPICS: list[bytes] = [TOPIC_SET_OUTPUT_VOLUME, TOPIC_SHUTDOWN, TOPIC_REBOOT, TOPIC_KILL_SOFTWARE, TOPIC_SET_SOUND_DEVICE]


class WindowsNode:
    """Windows/system control node for the ZMQ-based suit runtime."""
    def __init__(self) -> None:
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._handlers: dict[bytes, Any] = {
            TOPIC_SET_OUTPUT_VOLUME: self._handle_set_output_volume,
            TOPIC_SHUTDOWN: self._handle_shutdown,
            TOPIC_REBOOT: self._handle_reboot,
            TOPIC_KILL_SOFTWARE: self._handle_kill_software,
            TOPIC_SET_SOUND_DEVICE: self._handle_set_sound_device,
        }

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        threading.Thread(target=self._status_loop, daemon=True, name="windows-status-loop").start()
        threading.Thread(target=self._device_loop, daemon=True, name="windows-device-loop").start()
        log.info("Windows node started. SUB=%s PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping windows node...")
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
                log.warning("Received malformed ZeroMQ message (%d frame(s))", len(frames))
                continue
            topic_bytes, payload_bytes = frames[0], frames[1]
            try:
                payload = json.loads(payload_bytes)
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

    def _status_loop(self) -> None:
        while self._running.is_set():
            self._push(TOPIC_STATUS, self._build_status_payload())
            time.sleep(STATUS_PUBLISH_INTERVAL)

    def _device_loop(self) -> None:
        while self._running.is_set():
            devices = refresh_sound_devices()
            self._push(TOPIC_SOUND_DEVICES, {"devices": devices})
            self._push(TOPIC_OUTPUT_VOLUME, {"volume": get_system_volume()})
            time.sleep(DEVICE_PUBLISH_INTERVAL)

    def _build_status_payload(self) -> dict[str, Any]:
        return {
            "node": "windows",
            "platform": sys.platform,
            "cpu": get_cpu_info(),
            "memory": get_memory_info(),
            "disk": get_disk_info(),
        }

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        assert self._zmq_push is not None
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _handle_set_output_volume(self, payload: dict[str, Any]) -> None:
        volume = payload.get("volume")
        if volume is None:
            log.warning("set-output-volume: missing 'volume' field")
            return
        set_system_volume(_clamp_volume(float(volume)))
        log.info("set-output-volume: %.2f", volume)

    def _handle_shutdown(self, payload: dict[str, Any]) -> None:
        _ = payload
        subprocess.run(["shutdown", "/s", "/t", "1"], check=False)
        log.info("shutdown requested")

    def _handle_reboot(self, payload: dict[str, Any]) -> None:
        _ = payload
        subprocess.run(["shutdown", "/r", "/t", "1"], check=False)
        log.info("reboot requested")

    def _handle_kill_software(self, payload: dict[str, Any]) -> None:
        _ = payload
        subprocess.run(["taskkill", "/f", "/im", "DYNAMO-2.exe"], check=False)
        log.info("kill-software requested")

    def _handle_set_sound_device(self, payload: dict[str, Any]) -> None:
        device_name = payload.get("deviceName")
        device_type = payload.get("deviceType")
        if not isinstance(device_name, str) or not device_name:
            log.warning("set-sound-device: invalid deviceName")
            return
        if device_type not in {"input", "output"}:
            log.warning("set-sound-device: invalid deviceType")
            return
        set_default_sound_device(device_name, device_type)
        log.info("set-sound-device: type=%s name=%s", device_type, device_name)

    def _teardown(self) -> None:
        log.info("Tearing down windows node...")
        if self._zmq_sub is not None and not self._zmq_sub.closed:
            self._zmq_sub.close(linger=0)
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("Windows node stopped.")

def get_cpu_info() -> dict[str, Any]:
    cpu_freq = psutil.cpu_freq()
    return {
        "physical_cores": psutil.cpu_count(logical=False),
        "total_cores": psutil.cpu_count(logical=True),
        "max_frequency": getattr(cpu_freq, "max", None),
        "min_frequency": getattr(cpu_freq, "min", None),
        "current_frequency": getattr(cpu_freq, "current", None),
        "usage": psutil.cpu_percent(interval=None),
    }

def get_memory_info() -> dict[str, Any]:
    virtual_memory = psutil.virtual_memory()
    return {
        "total": virtual_memory.total,
        "available": virtual_memory.available,
        "used": virtual_memory.used,
        "percent": virtual_memory.percent,
    }

def get_disk_info() -> dict[str, Any]:
    disk_usage = psutil.disk_usage("/")
    return {
        "total": disk_usage.total,
        "used": disk_usage.used,
        "free": disk_usage.free,
        "percent": disk_usage.percent,
    }

def get_system_volume() -> float:
    comtypes.CoInitialize()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    return float(volume.GetMasterVolumeLevelScalar())

def set_system_volume(volume_level: float) -> None:
    comtypes.CoInitialize()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMasterVolumeLevelScalar(_clamp_float(volume_level), None)

def refresh_sound_devices() -> list[dict[str, str]]:
    subprocess.run(["SoundVolumeView.exe", "/sjson", "sound_volume.json"], shell=True, check=False)
    if not os.path.exists("sound_volume.json"):
        return []
    with open("sound_volume.json", "rb") as handle:
        data = json.load(handle)
    devices: list[dict[str, str]] = []
    for item in data:
        if item.get("Type") != "Device":
            continue
        devices.append({"Name": str(item.get("Device Name", ""))[:30], "ID": str(item.get("Item ID", ""))})
    return devices

def set_default_sound_device(device_name: str, direction: str) -> None:
    devices = refresh_sound_devices()
    for device in devices:
        if device["Name"] == device_name:
            log.info("Sound device selection requested for %s/%s", direction, device_name)
            return
    raise ValueError(f"Device '{device_name}' not found")

def _clamp_volume(value: float) -> int:
    return max(0, min(100, int(round(value))))

def _clamp_float(value: float) -> float:
    return max(0.0, min(1.0, float(value)))

def main() -> None:
    node = WindowsNode()
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d -- shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()


if __name__ == "__main__":
    main()
