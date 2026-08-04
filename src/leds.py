from __future__ import annotations
import colorsys
import json
import logging
import os
import signal
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
import zmq
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] leds: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("leds")

ZMQ_SUB_ADDRESS: str = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"

STATUS_PUBLISH_INTERVAL: float = 10.0
CONTROLLER_POLL_INTERVAL: float = 30.0
SYNC_INTERVAL: float = 0.25
HTTP_TIMEOUT: float = 0.5
HTTP_RETRIES: int = 2
ANIMATION_DEFAULT_DURATION: float = 2.0
DEFAULT_LED_COUNT: int = 721

TOPIC_STATUS = b"dynamo/leds/status"
TOPIC_STATUS_LEGACY = b"dynamo/status/leds"
TOPIC_LED_STATE = b"dynamo/state/leds"
TOPIC_LEDS_TOGGLE = b"dynamo/commands/leds-toggle"
TOPIC_LEDS_BRIGHTNESS = b"dynamo/commands/leds-brightness"
TOPIC_LEDS_COLOR = b"dynamo/commands/leds-color"
TOPIC_LEDS_EFFECT = b"dynamo/commands/leds-effect"
TOPIC_LEDS_ANIMATION = b"dynamo/commands/leds-animation"
TOPIC_SET_EXPRESSION = b"dynamo/commands/set-expression"
TOPIC_EXPRESSION = b"dynamo/expression"
TOPIC_INTERNAL_FFT = b"dynamo/microphone/internal/fft"
TOPIC_EXTERNAL_FFT = b"dynamo/microphone/external/fft"
TOPIC_INTERNAL_AED = b"dynamo/microphone/internal/aed"
TOPIC_EXTERNAL_AED = b"dynamo/microphone/external/aed"
TOPIC_EXTERNAL_BEAT = b"dynamo/microphone/external/beat-detect"
TOPIC_EXTERNAL_MUSIC = b"dynamo/microphone/external/music-detect"
SUBSCRIBED_TOPICS: list[bytes] = [TOPIC_LEDS_TOGGLE, TOPIC_LEDS_BRIGHTNESS, TOPIC_LEDS_COLOR, TOPIC_LEDS_EFFECT, TOPIC_LEDS_ANIMATION, TOPIC_SET_EXPRESSION, TOPIC_EXPRESSION, TOPIC_INTERNAL_FFT, TOPIC_EXTERNAL_FFT, TOPIC_INTERNAL_AED, TOPIC_EXTERNAL_AED, TOPIC_EXTERNAL_BEAT, TOPIC_EXTERNAL_MUSIC,]

NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 128, 0),
    "purple": (160, 64, 255),
    "pink": (255, 96, 180),
}

DEFAULT_EFFECT_ORDER = [
    "Solid",
    "Breathe",
    "Fade",
    "Wipe",
    "Rainbow",
    "Strobe",
    "Sparkle",
    "Pulse",
    "BPM",
    "Theater Chase",
    "Twinkle",
]

DEFAULT_PALETTE_ORDER = [
    "Default",
    "Random Cycle",
    "Primary Color",
    "Based on Primary",
    "Set Colors",
    "Based on Set",
    "Party",
    "Rainbow",
    "Red & Blue",
]

SCENE_PRESETS: dict[str, dict[str, Any]] = {
    "idle": {
        "effect": "Breathe",
        "palette": "Primary Color",
        "speed": 80,
        "intensity": 110,
        "transition": 6,
        "colors": ("primary", "accent", "shadow"),
    },
    "neutral": {
        "effect": "Solid",
        "palette": "Based on Primary",
        "speed": 0,
        "intensity": 0,
        "transition": 0,
        "colors": ("primary", "background", "shadow"),
    },
    "happy": {
        "effect": "Rainbow",
        "palette": "Rainbow",
        "speed": 180,
        "intensity": 150,
        "transition": 4,
        "colors": ("primary", "accent", "highlight"),
    },
    "sad": {
        "effect": "Fade",
        "palette": "Based on Primary",
        "speed": 60,
        "intensity": 90,
        "transition": 8,
        "colors": ("primary", "background", "shadow"),
    },
    "angry": {
        "effect": "Strobe",
        "palette": "Red & Blue",
        "speed": 255,
        "intensity": 255,
        "transition": 0,
        "colors": ("red", "primary", "highlight"),
    },
    "surprised": {
        "effect": "Wipe",
        "palette": "Primary Color",
        "speed": 180,
        "intensity": 130,
        "transition": 2,
        "colors": ("primary", "accent", "highlight"),
    },
    "sleep": {
        "effect": "Breathe",
        "palette": "Primary Color",
        "speed": 35,
        "intensity": 80,
        "transition": 10,
        "colors": ("background", "shadow", "primary"),
    },
    "alert": {
        "effect": "Strobe",
        "palette": "Primary Color",
        "speed": 255,
        "intensity": 255,
        "transition": 0,
        "colors": ("red", "accent", "highlight"),
    },
    "breathing": {
        "effect": "Breathe",
        "palette": "Primary Color",
        "speed": 100,
        "intensity": 120,
        "transition": 6,
        "colors": ("primary", "accent", "shadow"),
    },
    "rainbow": {
        "effect": "Rainbow",
        "palette": "Rainbow",
        "speed": 200,
        "intensity": 140,
        "transition": 4,
        "colors": ("primary", "accent", "highlight"),
    },
    "reactive": {
        "effect": "Solid",
        "palette": "Based on Primary",
        "speed": 0,
        "intensity": 0,
        "transition": 0,
        "colors": ("primary", "accent", "highlight"),
    },
    "party": {
        "effect": "BPM",
        "palette": "Party",
        "speed": 220,
        "intensity": 160,
        "transition": 2,
        "colors": ("primary", "accent", "highlight"),
    },
    "fft": {
        "effect": "Pulse",
        "palette": "Primary Color",
        "speed": 160,
        "intensity": 180,
        "transition": 0,
        "colors": ("primary", "accent", "highlight"),
    },
    "speech": {
        "effect": "Sparkle",
        "palette": "Based on Primary",
        "speed": 170,
        "intensity": 150,
        "transition": 0,
        "colors": ("primary", "highlight", "accent"),
    },
    "beat": {
        "effect": "Strobe",
        "palette": "Red & Blue",
        "speed": 255,
        "intensity": 255,
        "transition": 0,
        "colors": ("red", "accent", "highlight"),
    },
    "music": {
        "effect": "Rainbow",
        "palette": "Rainbow",
        "speed": 220,
        "intensity": 140,
        "transition": 0,
        "colors": ("primary", "accent", "highlight"),
    },
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))

def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default

def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "enabled"}:
            return True
        if lowered in {"false", "0", "no", "off", "disabled"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default

def _normalize_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None

def _normalize_key(value: Any) -> str:
    text = str(value).strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(text.split())

def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    text = value.strip().lower()
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        try:
            return tuple(int(component * 2, 16) for component in text)  # type: ignore[return-value]
        except ValueError:
            return None
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None

def _rgb_to_hls(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(channel / 255.0 for channel in rgb))

def _hls_to_rgb(hls: tuple[float, float, float]) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(*hls)
    return (round(_clamp(r, 0.0, 1.0) * 255), round(_clamp(g, 0.0, 1.0) * 255), round(_clamp(b, 0.0, 1.0) * 255),)

def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], weight: float) -> tuple[int, int, int]:
    weight = _clamp(weight, 0.0, 1.0)
    return (round(a[0] * (1.0 - weight) + b[0] * weight), round(a[1] * (1.0 - weight) + b[1] * weight), round(a[2] * (1.0 - weight) + b[2] * weight),)

def _scale_rgb(rgb: tuple[int, int, int], scalar: float) -> tuple[int, int, int]:
    scalar = _clamp(scalar, 0.0, 1.0)
    return (round(rgb[0] * scalar), round(rgb[1] * scalar), round(rgb[2] * scalar),)

def _theme_colors(theme: ThemePalette, names: Iterable[str]) -> list[str]:
    values: list[str] = []
    for name in names:
        rgb = getattr(theme, name, theme.primary)
        values.append(_rgb_to_hex(rgb))
    return values

def _scene_template(scene: str) -> dict[str, Any]:
    key = _normalize_key(scene)
    spec = SCENE_PRESETS.get(key)
    if spec is not None:
        return dict(spec)
    return {
        "effect": scene,
        "palette": "Primary Color",
        "speed": 128,
        "intensity": 128,
        "transition": 4,
        "colors": ("primary", "accent", "highlight"),
    }


@dataclass(frozen=True)
class ThemePalette:
    primary: tuple[int, int, int]
    accent: tuple[int, int, int]
    highlight: tuple[int, int, int]
    shadow: tuple[int, int, int]
    background: tuple[int, int, int]
    red: tuple[int, int, int]


@dataclass
class LedsState:
    enabled: bool = True
    brightness: int = 255
    primary_color: str = "#00ffff"
    base_scene: str = "idle"
    temporary_scene: str | None = None
    temporary_scene_until: float | None = None
    controller_online: bool = False
    controller_name: str | None = None
    led_count: int = DEFAULT_LED_COUNT
    last_audio_energy: float | None = None
    last_beat_strength: float | None = None
    reactive_mode: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def active_scene(self, now: float) -> str:
        with self._lock:
            if self.temporary_scene is not None and self.temporary_scene_until is not None and now < self.temporary_scene_until:
                return self.temporary_scene
            return self.base_scene

    def set_base_scene(self, scene: str) -> None:
        with self._lock:
            self.base_scene = _normalize_key(scene) or "idle"

    def set_temporary_scene(self, scene: str, until: float) -> None:
        with self._lock:
            self.temporary_scene = _normalize_key(scene) or "idle"
            self.temporary_scene_until = until

    def clear_temporary_scene(self) -> None:
        with self._lock:
            self.temporary_scene = None
            self.temporary_scene_until = None

    def expire_temporary_scene(self, now: float) -> bool:
        with self._lock:
            if self.temporary_scene is None or self.temporary_scene_until is None:
                return False
            if now < self.temporary_scene_until:
                return False
            self.temporary_scene = None
            self.temporary_scene_until = None
            return True

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            scene = self.base_scene if now is None else self.active_scene(now)
            return {
                "enabled": self.enabled,
                "brightness": self.brightness,
                "primary_color": self.primary_color,
                "base_scene": self.base_scene,
                "scene": scene,
                "animation_scene": self.temporary_scene,
                "animation_until": self.temporary_scene_until,
                "controller_online": self.controller_online,
                "controller_name": self.controller_name,
                "led_count": self.led_count,
                "last_audio_energy": self.last_audio_energy,
                "last_beat_strength": self.last_beat_strength,
                "reactive_mode": self.reactive_mode,
            }


class ThemeManager:
    def __init__(self, initial_color: str = "#00ffff") -> None:
        self._color = self._parse_color(initial_color) or NAMED_COLORS["cyan"]
        self._lock = threading.RLock()

    def set_primary(self, value: Any) -> None:
        color = self._parse_color(value)
        if color is None:
            return
        with self._lock:
            self._color = color

    def palette(self) -> ThemePalette:
        with self._lock:
            primary = self._color
        hue, lightness, saturation = _rgb_to_hls(primary)
        accent = _hls_to_rgb(((hue + 0.08) % 1.0, _clamp(lightness + 0.04, 0.0, 1.0), saturation))
        highlight = _hls_to_rgb((hue, _clamp(lightness + 0.22, 0.0, 1.0), _clamp(saturation * 0.82, 0.0, 1.0)))
        shadow = _hls_to_rgb((hue, _clamp(lightness * 0.45, 0.0, 1.0), _clamp(saturation * 0.9, 0.0, 1.0)))
        background = _hls_to_rgb((hue, _clamp(lightness * 0.22, 0.0, 1.0), _clamp(saturation * 0.6, 0.0, 1.0)))
        red = NAMED_COLORS["red"]
        return ThemePalette(primary=primary, accent=accent, highlight=highlight, shadow=shadow, background=background, red=red)

    def primary_text(self) -> str:
        with self._lock:
            return _rgb_to_hex(self._color)

    def _parse_color(self, value: Any) -> tuple[int, int, int] | None:
        if isinstance(value, tuple) and len(value) == 3:
            try:
                return tuple(max(0, min(255, int(component))) for component in value)  # type: ignore[return-value]
            except (TypeError, ValueError):
                return None
        if isinstance(value, list) and len(value) == 3:
            try:
                return tuple(max(0, min(255, int(component))) for component in value)  # type: ignore[return-value]
            except (TypeError, ValueError):
                return None
        if isinstance(value, str):
            return _hex_to_rgb(value)
        return None


class WLEDRenderer:
    def __init__(self, led_count: int = DEFAULT_LED_COUNT, host: str | None = None, port: int | None = None, timeout: float = HTTP_TIMEOUT, retries: int = HTTP_RETRIES,) -> None:
        self._host = host or os.getenv("WLED_HOST", "wled.local")
        self._port = port if port is not None else _clamp_int(os.getenv("WLED_PORT", "80"), 1, 65535, 80)
        self._timeout = timeout
        self._retries = retries
        self.controller_online = False
        self.controller_name: str | None = None
        self.led_count = max(1, int(led_count))
        self._effect_catalog = self._build_catalog(DEFAULT_EFFECT_ORDER)
        self._palette_catalog = self._build_catalog(DEFAULT_PALETTE_ORDER)

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def probe(self) -> bool:
        info_blob = self._request_json("/json/info")
        info = self._coerce_info(info_blob)
        self.controller_online = info is not None
        if info is not None:
            self.controller_name = self._extract_name(info)
            leds_info = info.get("leds") if isinstance(info.get("leds"), dict) else None
            if isinstance(leds_info, dict):
                self.led_count = _clamp_int(leds_info.get("count"), 1, 10_000, self.led_count)
        effects_blob = self._request_json("/json/eff")
        effect_names = self._extract_names(effects_blob, "effects")
        if effect_names:
            self._effect_catalog = self._build_catalog(effect_names)
        palettes_blob = self._request_json("/json/pal")
        palette_names = self._extract_names(palettes_blob, "palettes")
        if palette_names:
            self._palette_catalog = self._build_catalog(palette_names)
        return self.controller_online

    def resolve_effect_id(self, effect_name: Any) -> int:
        if isinstance(effect_name, int):
            return max(0, effect_name)
        text = _normalize_text(effect_name)
        if text is None:
            return 0
        if text.isdigit():
            return max(0, int(text))
        return self._effect_catalog.get(_normalize_key(text), 0)

    def resolve_palette_id(self, palette_name: Any) -> int:
        if isinstance(palette_name, int):
            return max(0, palette_name)
        text = _normalize_text(palette_name)
        if text is None:
            return 0
        if text.isdigit():
            return max(0, int(text))
        return self._palette_catalog.get(_normalize_key(text), 0)

    def build_state_payload(self, *, enabled: bool, brightness: int, scene_name: str, scene_spec: dict[str, Any] | None, theme: ThemePalette,) -> dict[str, Any]:
        spec = dict(scene_spec or _scene_template(scene_name))
        colors = _theme_colors(theme, spec.get("colors", ("primary", "accent", "highlight")))
        return {
            "on": bool(enabled),
            "bri": _clamp_int(brightness, 0, 255, brightness),
            "transition": _clamp_int(spec.get("transition", 4), 0, 65_535, 4),
            "v": True,
            "seg": [
                {
                    "id": 0,
                    "fx": self.resolve_effect_id(spec.get("effect", scene_name)),
                    "sx": _clamp_int(spec.get("speed", 128), 0, 255, 128),
                    "ix": _clamp_int(spec.get("intensity", 128), 0, 255, 128),
                    "pal": self.resolve_palette_id(spec.get("palette", "Primary Color")),
                    "col": colors,
                }
            ],
        }

    def send_state(self, payload: dict[str, Any]) -> bool:
        response = self._request_json("/json/state", method="POST", payload=payload)
        return response is not None

    def _build_catalog(self, items: Iterable[Any]) -> dict[str, int]:
        catalog: dict[str, int] = {}
        for index, item in enumerate(items):
            if isinstance(item, str):
                catalog[_normalize_key(item)] = index
            elif isinstance(item, dict):
                name = item.get("name") or item.get("label") or item.get("title")
                if isinstance(name, str):
                    catalog[_normalize_key(name)] = index
        return catalog

    def _request_json(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None,) -> Any | None:
        data = None
        headers = {"User-Agent": "dynamo-leds", "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self._retries:
                    time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            log.debug("WLED request failed for %s: %s", path, last_error)
        return None

    def _coerce_info(self, blob: Any) -> dict[str, Any] | None:
        if not isinstance(blob, dict):
            return None
        if "leds" in blob or "name" in blob:
            return blob
        info = blob.get("info")
        return info if isinstance(info, dict) else None

    def _extract_names(self, blob: Any, key: str) -> list[str]:
        if isinstance(blob, dict):
            values = blob.get(key)
            if isinstance(values, list):
                return [str(item) for item in values if isinstance(item, (str, int, float))]
        if isinstance(blob, list):
            return [str(item) for item in blob if isinstance(item, (str, int, float))]
        return []

    def _extract_name(self, info: dict[str, Any]) -> str | None:
        for key in ("name", "brand", "product"):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None


class LedsNode:
    def __init__(self) -> None:
        self._state = LedsState(
            enabled=_normalize_bool(os.getenv("LEDS_ENABLED", "1"), default=True),
            brightness=_clamp_int(os.getenv("LEDS_BRIGHTNESS", "255"), 0, 255, 255),
            primary_color=os.getenv("LEDS_PRIMARY_COLOR", "#00ffff"),
            base_scene=_normalize_text(os.getenv("LEDS_BASE_SCENE")) or "idle",
            led_count=_clamp_int(os.getenv("LED_TOTAL_LEDS", str(DEFAULT_LED_COUNT)), 1, 10_000, DEFAULT_LED_COUNT),
        )
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._theme = ThemeManager(self._state.primary_color)
        self._renderer = WLEDRenderer(self._state.led_count)
        self._last_controller_signature: str | None = None
        self._handlers: dict[bytes, Callable[[dict[str, Any]], None]] = {
            TOPIC_LEDS_TOGGLE: self._handle_leds_toggle,
            TOPIC_LEDS_BRIGHTNESS: self._handle_leds_brightness,
            TOPIC_LEDS_COLOR: self._handle_leds_color,
            TOPIC_LEDS_EFFECT: self._handle_leds_effect,
            TOPIC_LEDS_ANIMATION: self._handle_leds_animation,
            TOPIC_SET_EXPRESSION: self._handle_set_expression,
            TOPIC_EXPRESSION: self._handle_expression_scores,
            TOPIC_INTERNAL_FFT: self._handle_internal_fft,
            TOPIC_EXTERNAL_FFT: self._handle_external_fft,
            TOPIC_INTERNAL_AED: self._handle_internal_aed,
            TOPIC_EXTERNAL_AED: self._handle_external_aed,
            TOPIC_EXTERNAL_BEAT: self._handle_external_beat,
            TOPIC_EXTERNAL_MUSIC: self._handle_external_music,
        }

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        self._renderer.probe()
        self._sync_controller_metadata()
        self._apply_controller_state(force=True)
        threading.Thread(target=self._status_loop, daemon=True, name="leds-status-loop").start()
        threading.Thread(target=self._controller_probe_loop, daemon=True, name="leds-controller-probe").start()
        threading.Thread(target=self._sync_loop, daemon=True, name="leds-sync-loop").start()
        log.info("LEDs node started. SUB=%s PUSH=%s WLED=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS, self._renderer.base_url)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping leds node...")
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
        assert self._zmq_sub is not None, "ZeroMQ socket not initialised"
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

    def _status_loop(self) -> None:
        self._push_status(online=True)
        while self._running.is_set():
            time.sleep(STATUS_PUBLISH_INTERVAL)
            self._push_status(online=True)

    def _controller_probe_loop(self) -> None:
        while self._running.is_set():
            self._renderer.probe()
            self._sync_controller_metadata()
            time.sleep(CONTROLLER_POLL_INTERVAL)

    def _sync_loop(self) -> None:
        while self._running.is_set():
            now = time.monotonic()
            if self._state.expire_temporary_scene(now):
                self._push_state("animation-expired", now=now)
            self._apply_controller_state(now=now)
            time.sleep(SYNC_INTERVAL)

    def _sync_controller_metadata(self) -> None:
        with self._state._lock:
            self._state.controller_online = self._renderer.controller_online
            self._state.controller_name = self._renderer.controller_name
            self._state.led_count = self._renderer.led_count

    def _build_controller_payload(self, now: float) -> dict[str, Any]:
        scene_name = self._state.active_scene(now)
        spec = _scene_template(scene_name)
        return self._renderer.build_state_payload(
            enabled=self._state.enabled,
            brightness=self._state.brightness,
            scene_name=scene_name,
            scene_spec=spec,
            theme=self._theme.palette(),
        )

    def _apply_controller_state(self, now: float | None = None, force: bool = False) -> bool:
        if not self._renderer.controller_online and not force:
            return False
        current_time = now if now is not None else time.monotonic()
        payload = self._build_controller_payload(current_time)
        signature = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if not force and signature == self._last_controller_signature:
            return False
        if self._renderer.send_state(payload):
            self._last_controller_signature = signature
            return True
        return False

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        assert self._zmq_push is not None
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode("utf-8")], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _push_state(self, reason: str, now: float | None = None) -> None:
        payload = self._state.snapshot(now=now)
        payload["reason"] = reason
        self._push(TOPIC_LED_STATE, payload)

    def _push_status(self, online: bool) -> None:
        now = time.monotonic()
        payload = {
            "status": "online" if online else "offline",
            "node": "leds",
            "controller_online": self._state.controller_online,
            "controller_name": self._state.controller_name,
            "led_count": self._state.led_count,
            "enabled": self._state.enabled,
            "brightness": self._state.brightness,
            "scene": self._state.active_scene(now),
            "primary_color": self._state.primary_color,
            "reactive_mode": self._state.reactive_mode,
        }
        self._push(TOPIC_STATUS, payload)
        self._push(TOPIC_STATUS_LEGACY, payload)

    def _set_scene(self, scene: str, reason: str) -> None:
        normalized = _normalize_key(scene) or "idle"
        self._state.set_base_scene(normalized)
        log.info("%s: scene=%s", reason, normalized)
        self._push_state(reason)

    def _handle_leds_toggle(self, payload: dict[str, Any]) -> None:
        enabled = _normalize_bool(payload.get("enabled"), default=self._state.enabled)
        with self._state._lock:
            self._state.enabled = enabled
            if not enabled:
                self._state.reactive_mode = False
        log.info("leds-toggle: enabled=%s", enabled)
        self._push_state("toggle")

    def _handle_leds_brightness(self, payload: dict[str, Any]) -> None:
        brightness = payload.get("brightness")
        if brightness is None:
            log.warning("leds-brightness: missing 'brightness' field")
            return
        value = _clamp_int(brightness, 0, 255, self._state.brightness)
        with self._state._lock:
            self._state.brightness = value
        log.info("leds-brightness: %d", value)
        self._push_state("brightness")

    def _handle_leds_color(self, payload: dict[str, Any]) -> None:
        color = _normalize_text(payload.get("color"))
        if color is None:
            log.warning("leds-color: missing or invalid 'color' field")
            return
        self._theme.set_primary(color)
        with self._state._lock:
            self._state.primary_color = color
        log.info("leds-color: %s", color)
        self._push_state("color")

    def _handle_leds_effect(self, payload: dict[str, Any]) -> None:
        effect = _normalize_text(payload.get("effect"))
        scene = _normalize_text(payload.get("scene")) or effect
        if scene is None:
            log.warning("leds-effect: missing or invalid 'effect' field")
            return
        self._set_scene(scene, "effect")

    def _handle_leds_animation(self, payload: dict[str, Any]) -> None:
        animation = _normalize_text(payload.get("animation") or payload.get("scene") or payload.get("effect"))
        if animation is None:
            log.warning("leds-animation: missing or invalid animation identifier")
            return
        duration = payload.get("duration")
        duration_seconds = float(duration) if isinstance(duration, (int, float)) else ANIMATION_DEFAULT_DURATION
        now = time.monotonic()
        self._state.set_temporary_scene(animation, now + max(0.05, duration_seconds))
        log.info("leds-animation: animation=%s duration=%s", animation, duration)
        self._push_state("animation", now=now)

    def _handle_set_expression(self, payload: dict[str, Any]) -> None:
        expression = _normalize_text(payload.get("expression"))
        if expression is None:
            scores = payload.get("scores")
            if isinstance(scores, dict) and scores:
                expression = max(scores, key=lambda key: scores[key])
        if expression is None:
            log.warning("set-expression: could not determine expression from payload")
            return
        self._set_scene(expression, "expression")

    def _handle_expression_scores(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or not payload:
            return
        expression = max(payload, key=lambda key: payload[key])
        self._set_scene(str(expression), "expression-scores")

    def _handle_internal_fft(self, payload: dict[str, Any]) -> None:
        self._handle_fft(payload, source="internal")

    def _handle_external_fft(self, payload: dict[str, Any]) -> None:
        self._handle_fft(payload, source="external")

    def _handle_fft(self, payload: dict[str, Any], source: str) -> None:
        energy = self._extract_audio_metric(payload, "energy")
        bands = payload.get("bands")
        if isinstance(bands, list):
            values = [float(value) for value in bands if isinstance(value, (int, float))]
            if values:
                energy = sum(values) / len(values)
        with self._state._lock:
            self._state.last_audio_energy = energy
            if energy is not None and energy > 0.0:
                self._state.reactive_mode = True
        duration = 0.2 + min(0.45, (energy or 0.0) * 0.45)
        self._state.set_temporary_scene("fft", time.monotonic() + duration)
        log.info("%s-fft: energy=%s", source, energy)
        self._push_state(f"{source}-fft")

    def _handle_internal_aed(self, payload: dict[str, Any]) -> None:
        self._handle_audio_event(payload, source="internal")

    def _handle_external_aed(self, payload: dict[str, Any]) -> None:
        self._handle_audio_event(payload, source="external")

    def _handle_audio_event(self, payload: dict[str, Any], source: str) -> None:
        label = _normalize_text(payload.get("event") or payload.get("label") or payload.get("type")) or "speech_started"
        confidence = payload.get("confidence")
        intensity = _clamp(float(confidence), 0.2, 1.0) if isinstance(confidence, (int, float)) else 0.75
        with self._state._lock:
            self._state.reactive_mode = True
        if "speech" in label.lower():
            scene = "speech"
        else:
            scene = "fft" if intensity < 0.7 else "party"
        duration = 0.35 + (0.5 * intensity)
        self._state.set_temporary_scene(scene, time.monotonic() + duration)
        log.info("%s-aed: label=%s confidence=%s", source, label, confidence)
        self._push_state(f"{source}-aed")

    def _handle_external_beat(self, payload: dict[str, Any]) -> None:
        beat = self._extract_audio_metric(payload, "beat")
        with self._state._lock:
            self._state.last_beat_strength = beat
            self._state.reactive_mode = True
        duration = 0.18 + min(0.25, (beat or 0.0) * 0.25)
        self._state.set_temporary_scene("beat", time.monotonic() + duration)
        log.info("external-beat: strength=%s", beat)
        self._push_state("beat")

    def _handle_external_music(self, payload: dict[str, Any]) -> None:
        detected = _normalize_bool(payload.get("detected"), default=True)
        with self._state._lock:
            self._state.reactive_mode = detected
        if detected:
            self._state.set_temporary_scene("music", time.monotonic() + 0.5)
        log.info("external-music: detected=%s", detected)
        self._push_state("music")

    def _extract_audio_metric(self, payload: dict[str, Any], key: str) -> float | None:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            for candidate in ("value", "level", "strength", "avg", "rms", "amplitude"):
                nested = value.get(candidate)
                if isinstance(nested, (int, float)):
                    return float(nested)
        return None

    def _teardown(self) -> None:
        log.info("Tearing down leds node...")
        self._push_status(online=False)
        if self._zmq_sub is not None and not self._zmq_sub.closed:
            self._zmq_sub.close(linger=0)
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("LEDs node stopped.")


def main() -> None:
    node = LedsNode()
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d -- shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
