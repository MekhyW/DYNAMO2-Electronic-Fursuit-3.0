from __future__ import annotations
import json
import logging
import os
import signal
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any
import paho.mqtt.client as mqtt
import zmq
from dotenv import load_dotenv
load_dotenv("../.env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] mqttbridge: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("mqttbridge")

def _env(key: str, default: str | None = None) -> str:
    value = os.environ.get(key, default)
    if value is None:
        raise RuntimeError(f"Required environment variable '{key}' is not set.")
    return value

@dataclass(frozen=True)
class BridgeConfig:
    hivemq_host:     str   = ""
    hivemq_port:     int   = 8883
    hivemq_username: str   = ""
    hivemq_password: str   = ""
    local_mqtt_host: str   = "localhost"
    local_mqtt_port: int   = 1883
    zmq_pub_address: str   = "tcp://*:5555"
    zmq_pull_address: str  = "tcp://*:5556"
    heartbeat_interval: float = 30.0   # seconds between cloud heartbeats
    health_check_interval: float = 60.0  # seconds of cloud inactivity before reconnect
    keepalive: int = 15

def load_config() -> BridgeConfig:
    return BridgeConfig(
        hivemq_host=_env("mqtt_host"),
        hivemq_port=int(_env("mqtt_port")),
        hivemq_username=_env("mqtt_username"),
        hivemq_password=_env("mqtt_password"),
    )


class MQTTBridgeNode:
    """Unified bridge: every message from any source is forwarded to all others"""
    def __init__(self, config: BridgeConfig) -> None:
        self._cfg = config
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._pub:  zmq.Socket | None = None
        self._pull: zmq.Socket | None = None
        self._cloud = self._make_cloud_client()
        self._local = self._make_local_client()
        self._cloud_connected = threading.Event()
        self._local_connected = threading.Event()
        self._last_cloud_rx = 0.0

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        self._connect_cloud()
        self._connect_local()
        threading.Thread(target=self._pull_loop,      daemon=True, name="zmq-pull").start()
        threading.Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat").start()
        threading.Thread(target=self._health_loop,    daemon=True, name="health-check").start()
        log.info("Bridge started — PUB %s | PULL %s", self._cfg.zmq_pub_address, self._cfg.zmq_pull_address)
        while self._running.is_set():
            time.sleep(1)
        self._teardown()

    def stop(self) -> None:
        log.info("Stopping bridge...")
        self._running.clear()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._pub = self._zmq_ctx.socket(zmq.PUB)
        self._pub.bind(self._cfg.zmq_pub_address)
        log.info("ZMQ PUB bound to %s", self._cfg.zmq_pub_address)
        self._pull = self._zmq_ctx.socket(zmq.PULL)
        self._pull.setsockopt(zmq.RCVTIMEO, 500)
        self._pull.bind(self._cfg.zmq_pull_address)
        log.info("ZMQ PULL bound to %s", self._cfg.zmq_pull_address)

    def _make_cloud_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id="dynamo-bridge-cloud", protocol=mqtt.MQTTv5)
        client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
        client.on_connect    = self._on_cloud_connect
        client.on_disconnect = self._on_cloud_disconnect
        client.on_message    = self._on_cloud_message
        return client

    def _make_local_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id="dynamo-bridge-local", protocol=mqtt.MQTTv311)
        client.on_connect    = self._on_local_connect
        client.on_disconnect = self._on_local_disconnect
        client.on_message    = self._on_local_message
        return client

    def _connect_cloud(self) -> None:
        cfg = self._cfg
        self._cloud.username_pw_set(cfg.hivemq_username, cfg.hivemq_password)
        self._cloud.reconnect_delay_set(min_delay=1, max_delay=30)
        log.info("Connecting to HiveMQ Cloud at %s:%d...", cfg.hivemq_host, cfg.hivemq_port)
        try:
            self._cloud.connect(cfg.hivemq_host, cfg.hivemq_port, keepalive=cfg.keepalive, clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY)
            self._cloud.loop_start()
        except Exception as exc:
            log.error("HiveMQ Cloud connection error: %s", exc)

    def _connect_local(self) -> None:
        cfg = self._cfg
        log.info("Connecting to local MQTT broker at %s:%d...", cfg.local_mqtt_host, cfg.local_mqtt_port)
        try:
            self._local.connect(cfg.local_mqtt_host, cfg.local_mqtt_port, keepalive=cfg.keepalive)
            self._local.loop_start()
        except Exception as exc:
            log.error("Local MQTT connection error: %s", exc)

    def _on_cloud_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: int, properties: Any = None) -> None:
        if rc != 0:
            log.error("HiveMQ Cloud connection failed (rc=%d)", rc)
            return
        log.info("Connected to HiveMQ Cloud")
        self._cloud_connected.set()
        self._last_cloud_rx = time.time()
        client.subscribe("dynamo/#")
        client.subscribe("mekhy/#")

    def _on_cloud_disconnect(self, client: mqtt.Client, userdata: Any, rc: int, properties: Any = None) -> None:
        self._cloud_connected.clear()
        if rc == 0:
            log.info("HiveMQ Cloud: disconnected cleanly")
        else:
            log.warning("HiveMQ Cloud: disconnected (rc=%d) — paho will reconnect", rc)

    def _on_cloud_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Cloud message → ZMQ PUB + local MQTT."""
        self._last_cloud_rx = time.time()
        threading.Thread(target=self._fan_out, args=(msg.topic, msg.payload, "cloud"), daemon=True).start()

    def _on_local_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: int) -> None:
        if rc != 0:
            log.error("Local MQTT connection failed (rc=%d)", rc)
            return
        log.info("Connected to local MQTT broker")
        self._local_connected.set()
        client.subscribe("dynamo/#")

    def _on_local_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self._local_connected.clear()
        if rc == 0:
            log.info("Local MQTT: disconnected cleanly")
        else:
            log.warning("Local MQTT: disconnected (rc=%d) — paho will reconnect", rc)

    def _on_local_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Local board message → ZMQ PUB + cloud MQTT."""
        threading.Thread(target=self._fan_out, args=(msg.topic, msg.payload, "local"), daemon=True).start()

    def _pull_loop(self) -> None:
        """
        Receives 2-frame messages from local nodes:
          Frame 0: topic bytes  e.g. b"dynamo/actuators/servo-states"
          Frame 1: JSON payload bytes
        Forwards to both MQTT brokers and back onto the ZMQ PUB bus.
        """
        assert self._pull is not None
        while self._running.is_set():
            try:
                frames = self._pull.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError as exc:
                if self._running.is_set():
                    log.error("ZMQ PULL error: %s", exc)
                break
            if len(frames) < 2:
                log.warning("Malformed PULL message (%d frame(s)) — dropping", len(frames))
                continue
            topic_bytes, payload_bytes = frames[0], frames[1]
            topic_str = topic_bytes.decode(errors="replace")
            try:
                json.loads(payload_bytes)
            except json.JSONDecodeError:
                log.warning("PULL message on %s has invalid JSON — dropping", topic_str)
                continue
            log.debug("ZMQ → all: %s", topic_str)
            self._fan_out(topic_str, payload_bytes, "zmq")

    def _fan_out(self, topic: str, payload_bytes: bytes, source: str) -> None:
        """Publish a message to all transports except where it came from ("cloud", "local" or "zmq")"""
        try:
            json.loads(payload_bytes)
        except json.JSONDecodeError:
            log.warning("Non-JSON message on %s from %s — dropping", topic, source)
            return
        retain = topic.startswith("dynamo/data/") # Topics whose last value should be retained by HiveMQ so mobile clients always receive the current list immediately on subscribe.
        if source != "cloud":
            self._publish_cloud(topic, None, raw=payload_bytes, retain=retain)
        if source != "local":
            self._publish_local(topic, None, raw=payload_bytes)
        if source != "zmq":
            self._zmq_pub(topic.encode(), payload_bytes)
        if retain:
            log.debug("%s → all (retained): %s", source, topic)
        else:
            log.debug("%s → all: %s", source, topic)

    def _publish_cloud(self, topic: str, payload: dict[str, Any] | None, raw: bytes | None = None, qos: int = 0, retain: bool = False) -> None:
        if not self._cloud_connected.is_set():
            return
        try:
            data = raw if raw is not None else json.dumps(payload).encode()
            self._cloud.publish(topic, data, qos=qos, retain=retain)
        except Exception as exc:
            log.error("Cloud publish failed on %s: %s", topic, exc)

    def _publish_local(self, topic: str, payload: dict[str, Any] | None, raw: bytes | None = None, qos: int = 0, retain: bool = False) -> None:
        if not self._local_connected.is_set():
            return
        try:
            data = raw if raw is not None else json.dumps(payload).encode()
            self._local.publish(topic, data, qos=qos, retain=retain)
        except Exception as exc:
            log.error("Local publish failed on %s: %s", topic, exc)

    def _zmq_pub(self, topic_bytes: bytes, payload_bytes: bytes) -> None:
        assert self._pub is not None
        try:
            self._pub.send_multipart([topic_bytes, payload_bytes])
        except zmq.ZMQError as exc:
            log.error("ZMQ PUB error: %s", exc)

    def _heartbeat_loop(self) -> None:
        while self._running.is_set():
            time.sleep(self._cfg.heartbeat_interval)
            if self._cloud_connected.is_set():
                self._publish_cloud("dynamo/heartbeat", {"timestamp": time.time(), "node": "mqttbridge"})

    def _health_loop(self) -> None:
        """Recycle cloud connection if no messages received within health_check_interval."""
        while self._running.is_set():
            time.sleep(self._cfg.health_check_interval)
            if not self._cloud_connected.is_set():
                continue
            since = time.time() - self._last_cloud_rx
            if self._last_cloud_rx > 0 and since > self._cfg.health_check_interval:
                log.warning("Cloud MQTT stale (no activity for %.0fs) — recycling", since)
                try:
                    self._cloud.loop_stop()
                    self._cloud.disconnect()
                except Exception:
                    pass
                time.sleep(2)
                self._connect_cloud()

    def _teardown(self) -> None:
        log.info("Tearing down bridge...")
        self._cloud.loop_stop()
        self._local.loop_stop()
        for client in (self._cloud, self._local):
            try:
                client.disconnect()
            except Exception:
                pass
        if self._pub  is not None and not self._pub.closed:
            self._pub.close(linger=0)
        if self._pull is not None and not self._pull.closed:
            self._pull.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("Bridge stopped.")


def main() -> None:
    try:
        config = load_config()
    except RuntimeError as exc:
        log.critical("Configuration error: %s", exc)
        raise SystemExit(1) from exc
    node = MQTTBridgeNode(config)
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d — shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
