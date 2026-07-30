from __future__ import annotations
import colorsys
import json
import logging
import math
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
DEFAULT_RENDER_FPS: float = 60.0
STATIC_RENDER_FPS: float = 6.0
HTTP_TIMEOUT: float = 0.5
HTTP_RETRIES: int = 2
ANIMATION_DEFAULT_DURATION: float = 2.0
SCENE_TRANSITION_SECONDS: float = 0.35

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
SUBSCRIBED_TOPICS: list[bytes] = [TOPIC_LEDS_TOGGLE,TOPIC_LEDS_BRIGHTNESS,TOPIC_LEDS_COLOR,TOPIC_LEDS_EFFECT,TOPIC_LEDS_ANIMATION,TOPIC_SET_EXPRESSION,TOPIC_EXPRESSION,TOPIC_INTERNAL_FFT,TOPIC_EXTERNAL_FFT,TOPIC_INTERNAL_AED,TOPIC_EXTERNAL_AED,TOPIC_EXTERNAL_BEAT,TOPIC_EXTERNAL_MUSIC]

DEFAULT_REGION_MAP: dict[str, tuple[tuple[int, int], ...]] = {
    "body": ((0, 180),),
    "left_arm": ((181, 260),),
    "right_arm": ((261, 340),),
    "left_leg": ((341, 450),),
    "right_leg": ((451, 560),),
    "tail": ((561, 690),),
    "ears": ((691, 720),),
}

DEFAULT_SCENES: dict[str, list[dict[str, Any]]] = {
    "idle": [
        {"effect": "breathing", "regions": ["body"], "priority": 10, "params": {"speed": 0.18, "palette": "primary"}},
    ],
    "neutral": [
        {"effect": "solid_color", "regions": ["body"], "priority": 10, "params": {"palette": "background"}},
    ],
    "happy": [
        {"effect": "rainbow", "regions": ["body"], "priority": 10, "params": {"speed": 0.45}},
        {"effect": "sparkle", "regions": ["ears", "body"], "priority": 25, "params": {"density": 0.08, "palette": "highlight"}},
    ],
    "sad": [
        {"effect": "fade", "regions": ["body"], "priority": 10, "params": {"speed": 0.10, "palette": "shadow"}},
    ],
    "angry": [
        {"effect": "strobe", "regions": ["body"], "priority": 10, "params": {"frequency": 7.0, "palette": "primary"}},
    ],
    "surprised": [
        {"effect": "wipe", "regions": ["body", "ears"], "priority": 10, "params": {"speed": 0.75, "palette": "highlight"}},
    ],
    "sleep": [
        {"effect": "breathing", "regions": ["body"], "priority": 10, "params": {"speed": 0.07, "palette": "background"}},
    ],
    "alert": [
        {"effect": "strobe", "regions": ["body"], "priority": 10, "params": {"frequency": 10.0, "palette": "red"}},
    ],
    "breathing": [
        {"effect": "breathing", "regions": ["body"], "priority": 10, "params": {"speed": 0.20, "palette": "primary"}},
    ],
    "rainbow": [
        {"effect": "rainbow", "regions": ["body"], "priority": 10, "params": {"speed": 0.60}},
    ],
    "reactive": [
        {"effect": "solid_color", "regions": ["body"], "priority": 10, "params": {"palette": "primary"}},
    ],
    "party": [
        {"effect": "rainbow", "regions": ["body"], "priority": 10, "params": {"speed": 0.85}},
        {"effect": "theater_chase", "regions": ["ears", "body"], "priority": 30, "params": {"speed": 0.90, "palette": "highlight"}},
    ],
}

SUPPORTED_EFFECTS = {"solid_color", "fade", "wipe", "theater_chase", "rainbow", "strobe", "breathing", "pulse", "sparkle", "twinkle"}
STATIC_SCENES = {"neutral", "idle"}
DEFAULT_LED_COUNT = 721

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

def _normalize_color_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None

def _coerce_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]

def _parse_region_map(raw: str | None) -> dict[str, tuple[tuple[int, int], ...]]:
    if not raw:
        return dict(DEFAULT_REGION_MAP)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Invalid LED_REGION_MAP JSON; falling back to defaults")
        return dict(DEFAULT_REGION_MAP)
    region_map: dict[str, tuple[tuple[int, int], ...]] = {}
    if not isinstance(parsed, dict):
        return dict(DEFAULT_REGION_MAP)
    for region, ranges in parsed.items():
        if not isinstance(region, str):
            continue
        resolved: list[tuple[int, int]] = []
        if isinstance(ranges, list):
            for entry in ranges:
                if isinstance(entry, (list, tuple)) and len(entry) == 2:
                    start, stop = entry
                    try:
                        resolved.append((int(start), int(stop)))
                    except (TypeError, ValueError):
                        continue
        if resolved:
            region_map[region] = tuple(resolved)
    return region_map or dict(DEFAULT_REGION_MAP)

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
            r = int(text[0] * 2, 16)
            g = int(text[1] * 2, 16)
            b = int(text[2] * 2, 16)
        except ValueError:
            return None
        return (r, g, b)
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
    return (round(_clamp(r, 0.0, 1.0) * 255), round(_clamp(g, 0.0, 1.0) * 255), round(_clamp(b, 0.0, 1.0) * 255))

def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], weight: float) -> tuple[int, int, int]:
    weight = _clamp(weight, 0.0, 1.0)
    return (round(a[0] * (1.0 - weight) + b[0] * weight), round(a[1] * (1.0 - weight) + b[1] * weight), round(a[2] * (1.0 - weight) + b[2] * weight))

def _scale_rgb(rgb: tuple[int, int, int], scalar: float) -> tuple[int, int, int]:
    scalar = _clamp(scalar, 0.0, 1.0)
    return (round(rgb[0] * scalar), round(rgb[1] * scalar), round(rgb[2] * scalar))


@dataclass(frozen=True)
class ThemePalette:
    primary: tuple[int, int, int]
    accent: tuple[int, int, int]
    highlight: tuple[int, int, int]
    shadow: tuple[int, int, int]
    background: tuple[int, int, int]
    red: tuple[int, int, int]


@dataclass
class RenderState:
    enabled: bool = True
    brightness: int = 255
    primary_color: str = "#00ffff"
    base_scene: str = "idle"
    animation_scene: str | None = None
    animation_until: float | None = None
    controller_online: bool = False
    controller_name: str | None = None
    led_count: int = DEFAULT_LED_COUNT
    last_audio_energy: float | None = None
    last_beat_strength: float | None = None
    reactive_mode: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "brightness": self.brightness,
                "primary_color": self.primary_color,
                "base_scene": self.base_scene,
                "animation_scene": self.animation_scene,
                "animation_until": self.animation_until,
                "controller_online": self.controller_online,
                "controller_name": self.controller_name,
                "led_count": self.led_count,
                "last_audio_energy": self.last_audio_energy,
                "last_beat_strength": self.last_beat_strength,
                "reactive_mode": self.reactive_mode,
            }


@dataclass(frozen=True)
class LayerSpec:
    effect: str
    regions: tuple[str, ...]
    priority: int = 10
    params: dict[str, Any] = field(default_factory=dict)
    opacity: float = 1.0
    ttl: float | None = None
    name: str | None = None


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
        if isinstance(value, str):
            return _hex_to_rgb(value)
        return None


class SegmentMapper:
    def __init__(self, total_leds: int = DEFAULT_LED_COUNT, region_map: dict[str, tuple[tuple[int, int], ...]] | None = None) -> None:
        self._lock = threading.RLock()
        self._total_leds = max(1, int(total_leds))
        self._region_map = region_map or dict(DEFAULT_REGION_MAP)

    @property
    def total_leds(self) -> int:
        with self._lock:
            return self._total_leds

    def set_total_leds(self, count: int) -> None:
        with self._lock:
            self._total_leds = max(1, int(count))

    def set_region_map(self, region_map: dict[str, tuple[tuple[int, int], ...]]) -> None:
        with self._lock:
            self._region_map = region_map or dict(DEFAULT_REGION_MAP)

    def resolve_indices(self, regions: Iterable[str] | None = None) -> list[int]:
        with self._lock:
            total_leds = self._total_leds
            region_map = dict(self._region_map)
        region_names = [region for region in (regions or []) if region in region_map]
        if not region_names:
            return list(range(total_leds))
        indices: list[int] = []
        for region_name in region_names:
            for start, stop in region_map.get(region_name, ()):
                lo = max(0, min(total_leds - 1, int(start)))
                hi = max(0, min(total_leds - 1, int(stop)))
                if hi < lo:
                    lo, hi = hi, lo
                indices.extend(range(lo, hi + 1))
        return sorted(set(index for index in indices if 0 <= index < total_leds))


class SceneManager:
    def __init__(self, initial_scene: str = "idle") -> None:
        self._lock = threading.RLock()
        self._base_scene = initial_scene
        self._previous_scene = initial_scene
        self._transition_started = 0.0
        self._transition_duration = SCENE_TRANSITION_SECONDS
        self._animation_scene: str | None = None
        self._animation_until: float | None = None

    def set_base_scene(self, scene: str, now: float | None = None, transition_seconds: float = SCENE_TRANSITION_SECONDS) -> None:
        with self._lock:
            scene = scene.strip().lower() or "idle"
            if scene == self._base_scene:
                return
            self._previous_scene = self._base_scene
            self._base_scene = scene
            self._transition_started = now if now is not None else time.monotonic()
            self._transition_duration = max(0.0, transition_seconds)

    def play_animation(self, scene: str, duration: float | None = None, now: float | None = None) -> None:
        with self._lock:
            self._animation_scene = scene.strip().lower() or "idle"
            self._animation_until = (now if now is not None else time.monotonic()) + max(0.05, duration or ANIMATION_DEFAULT_DURATION)

    def tick(self, now: float) -> None:
        with self._lock:
            if self._animation_until is not None and now >= self._animation_until:
                self._animation_scene = None
                self._animation_until = None

    def current_scene(self, now: float) -> str:
        with self._lock:
            if self._animation_scene is not None:
                return self._animation_scene
            return self._base_scene

    def transition_progress(self, now: float) -> float:
        with self._lock:
            if self._transition_duration <= 0.0:
                return 1.0
            progress = (now - self._transition_started) / self._transition_duration
            return _clamp(progress, 0.0, 1.0)

    def previous_scene(self) -> str:
        with self._lock:
            return self._previous_scene

    def base_scene(self) -> str:
        with self._lock:
            return self._base_scene

    def active_animation(self, now: float) -> str | None:
        with self._lock:
            if self._animation_scene is None or self._animation_until is None:
                return None
            if now >= self._animation_until:
                return None
            return self._animation_scene

    def animation_until(self) -> float | None:
        with self._lock:
            return self._animation_until


class EventManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[LayerSpec] = []

    def add(self, layer: LayerSpec, now: float) -> None:
        if layer.ttl is None:
            with self._lock:
                self._events.append(layer)
            return
        expires = now + max(0.05, layer.ttl)
        with self._lock:
            self._events.append(LayerSpec(layer.effect, layer.regions, layer.priority, dict(layer.params), layer.opacity, expires, layer.name))

    def active_layers(self, now: float) -> list[LayerSpec]:
        with self._lock:
            active: list[LayerSpec] = []
            kept: list[LayerSpec] = []
            for layer in self._events:
                if layer.ttl is not None and layer.ttl < now:
                    continue
                active.append(layer)
                kept.append(layer)
            self._events = kept
            return active

    def has_active_layers(self, now: float) -> bool:
        return bool(self.active_layers(now))


class SceneLibrary:
    def __init__(self) -> None:
        self._recipes = dict(DEFAULT_SCENES)

    def recipe(self, scene: str) -> list[LayerSpec]:
        key = scene.strip().lower()
        raw_layers = self._recipes.get(key)
        if not raw_layers:
            return [LayerSpec(effect="solid_color", regions=("body",), priority=10, params={"palette": "primary"})]
        layers: list[LayerSpec] = []
        for entry in raw_layers:
            layers.append(LayerSpec(effect=str(entry.get("effect", "solid_color")), regions=tuple(str(region) for region in entry.get("regions", ["body"])), priority=int(entry.get("priority", 10)), params=dict(entry.get("params", {})), opacity=float(entry.get("opacity", 1.0)), ttl=entry.get("ttl"), name=entry.get("name")))
        return layers


class EffectLibrary:
    def render(self, layer: LayerSpec, indices: list[int], palette: ThemePalette, now: float, total_leds: int) -> list[tuple[int, int, int] | None]:
        frame: list[tuple[int, int, int] | None] = [None] * total_leds
        if not indices:
            return frame
        effect = layer.effect.lower()
        params = layer.params
        chosen_palette = self._choose_palette(params, palette)
        if effect == "solid_color":
            for index in indices:
                frame[index] = chosen_palette
            return frame
        if effect in {"fade", "breathing"}:
            speed = float(params.get("speed", 0.20))
            amplitude = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(now * math.tau * speed))
            color = _scale_rgb(chosen_palette, amplitude)
            for index in indices:
                frame[index] = color
            return frame
        if effect == "wipe":
            speed = float(params.get("speed", 0.75))
            width = max(1, int(params.get("width", max(1, len(indices) // 8 or 1))))
            phase = (now * speed) % 1.0
            head = int(phase * max(1, len(indices)))
            for offset, index in enumerate(indices):
                if head <= offset < head + width:
                    frame[index] = chosen_palette
                else:
                    frame[index] = palette.background
            return frame
        if effect == "theater_chase":
            speed = float(params.get("speed", 1.0))
            spacing = max(2, int(params.get("spacing", 3)))
            phase = int(now * speed) % spacing
            for offset, index in enumerate(indices):
                frame[index] = chosen_palette if (offset + phase) % spacing == 0 else palette.shadow
            return frame
        if effect == "rainbow":
            speed = float(params.get("speed", 0.6))
            for offset, index in enumerate(indices):
                hue = ((offset / max(1, len(indices))) + (now * speed * 0.08)) % 1.0
                frame[index] = _hsv_to_rgb(hue, 1.0, 1.0)
            return frame
        if effect == "strobe":
            frequency = float(params.get("frequency", 8.0))
            on = math.sin(now * math.tau * frequency) > 0.0
            color = chosen_palette if on else palette.background
            for index in indices:
                frame[index] = color
            return frame
        if effect in {"pulse", "sparkle", "twinkle"}:
            intensity = float(params.get("intensity", params.get("energy", 0.7)))
            density = float(params.get("density", 0.10))
            seed = int(now * 10.0)
            for offset, index in enumerate(indices):
                if effect == "sparkle":
                    if ((offset + seed) % max(2, round(1.0 / max(0.01, density)))) == 0:
                        frame[index] = chosen_palette
                    else:
                        frame[index] = palette.shadow
                elif effect == "twinkle":
                    phase = math.sin((offset + seed) * 0.75 + now * 3.0)
                    frame[index] = _scale_rgb(chosen_palette, 0.35 + 0.65 * max(0.0, phase))
                else:
                    phase = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(now * math.tau * max(0.2, intensity)))
                    frame[index] = _scale_rgb(chosen_palette, phase)
            return frame
        # Unknown effect names are rendered as the primary theme color.
        for index in indices:
            frame[index] = chosen_palette
        return frame

    def _choose_palette(self, params: dict[str, Any], palette: ThemePalette) -> tuple[int, int, int]:
        slot = str(params.get("palette", "primary")).lower()
        mapping = {"primary": palette.primary, "accent": palette.accent, "highlight": palette.highlight, "shadow": palette.shadow, "background": palette.background, "red": palette.red}
        custom_color = params.get("color")
        if isinstance(custom_color, str):
            parsed = _hex_to_rgb(custom_color)
            if parsed is not None:
                return parsed
        return mapping.get(slot, palette.primary)


class Compositor:
    def blend(self, base: list[tuple[int, int, int] | None], overlay: list[tuple[int, int, int] | None], opacity: float) -> list[tuple[int, int, int] | None]:
        opacity = _clamp(opacity, 0.0, 1.0)
        result = list(base)
        for index, color in enumerate(overlay):
            if color is None:
                continue
            existing = result[index]
            if existing is None:
                result[index] = color
                continue
            result[index] = _mix_rgb(existing, color, opacity)
        return result

    def fill(self, total_leds: int, color: tuple[int, int, int] | None = None) -> list[tuple[int, int, int] | None]:
        return [color] * total_leds


class WLEDRenderer:
    def __init__(self, led_count: int, timeout: float = HTTP_TIMEOUT, retries: int = HTTP_RETRIES) -> None:
        self._lock = threading.RLock()
        self._led_count = max(1, int(led_count))
        self._timeout = timeout
        self._retries = retries
        self._url = self._build_state_url()
        self._info_url = self._build_info_url()
        self._controller_online = False
        self._controller_name: str | None = None
        self._last_probe = 0.0
        self._lights_on = False

    @property
    def led_count(self) -> int:
        with self._lock:
            return self._led_count

    @property
    def controller_online(self) -> bool:
        with self._lock:
            return self._controller_online

    @property
    def controller_name(self) -> str | None:
        with self._lock:
            return self._controller_name

    def _build_state_url(self) -> str:
        direct_url = os.getenv("WLED_URL")
        if direct_url:
            return direct_url.rstrip("/") + "/json/state"
        host = os.getenv("WLED_HOST", "127.0.0.1")
        port = int(os.getenv("WLED_PORT", "80"))
        path = os.getenv("WLED_STATE_PATH", "/json/state")
        return f"http://{host}:{port}{path}"

    def _build_info_url(self) -> str:
        direct_url = os.getenv("WLED_URL")
        if direct_url:
            return direct_url.rstrip("/") + "/json/info"
        host = os.getenv("WLED_HOST", "127.0.0.1")
        port = int(os.getenv("WLED_PORT", "80"))
        path = os.getenv("WLED_INFO_PATH", "/json/info")
        return f"http://{host}:{port}{path}"

    def probe(self) -> None:
        try:
            data = self._get_json(self._info_url)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._controller_online = False
            log.debug("WLED probe failed: %s", exc)
            return
        leds = self._extract_led_info(data)
        with self._lock:
            self._controller_online = True
            self._controller_name = self._extract_controller_name(data)
            if leds is not None:
                self._led_count = leds
            self._last_probe = time.monotonic()

    def send_frame(self, frame: list[tuple[int, int, int] | None], brightness: int, enabled: bool) -> bool:
        with self._lock:
            lights_on = self._lights_on
        if not enabled:
            ok = self._post_state({"on": False, "v": True})
            with self._lock:
                self._lights_on = False if ok else self._lights_on
            return ok
        if not lights_on:
            activate = {"on": True, "bri": _clamp_int(brightness, 0, 255, 255), "transition": 0, "v": True}
            if not self._post_state(activate):
                with self._lock:
                    self._lights_on = False
                return False
            with self._lock:
                self._lights_on = True
            time.sleep(0.02)
        led_count = self.led_count
        colors: list[str] = []
        for index in range(led_count):
            rgb = frame[index] if index < len(frame) else None
            colors.append(_rgb_to_hex(rgb or (0, 0, 0)))
        payload = {
            "on": True,
            "bri": _clamp_int(brightness, 0, 255, 255),
            "v": True,
            "transition": 0,
            "seg": [{"id": 0, "i": colors}],
        }
        ok = self._post_state(payload)
        with self._lock:
            self._lights_on = ok or self._lights_on
        return ok

    def _post_state(self, payload: dict[str, Any]) -> bool:
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(self._url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        for attempt in range(self._retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    response.read()
                with self._lock:
                    self._controller_online = True
                return True
            except Exception as exc:  # noqa: BLE001
                if attempt >= self._retries:
                    with self._lock:
                        self._controller_online = False
                    log.debug("WLED POST failed: %s", exc)
                    return False
                time.sleep(0.05)
        return False

    def refresh_status(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_probe < CONTROLLER_POLL_INTERVAL:
                return
        self.probe()

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
        raise ValueError("WLED info response was not a JSON object")

    def _extract_led_info(self, data: dict[str, Any]) -> int | None:
        candidates = [
            data.get("leds"),
            data.get("info", {}).get("leds") if isinstance(data.get("info"), dict) else None,
            data.get("state", {}).get("leds") if isinstance(data.get("state"), dict) else None,
        ]
        for entry in candidates:
            if isinstance(entry, dict):
                count = entry.get("count")
                if isinstance(count, int) and count > 0:
                    return count
        return None

    def _extract_controller_name(self, data: dict[str, Any]) -> str | None:
        info = data.get("info") if isinstance(data.get("info"), dict) else data
        if isinstance(info, dict):
            name = info.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return None


class LedsNode:
    def __init__(self) -> None:
        self._state = RenderState(
            enabled=_normalize_bool(os.getenv("LEDS_ENABLED", "true"), True),
            brightness=_clamp_int(os.getenv("LEDS_BRIGHTNESS", "255"), 0, 255, 255),
            primary_color=os.getenv("LEDS_PRIMARY_COLOR", "#00ffff"),
            base_scene=os.getenv("LEDS_BASE_SCENE", "idle"),
            led_count=_clamp_int(os.getenv("LED_TOTAL_LEDS", str(DEFAULT_LED_COUNT)), 1, 10_000, DEFAULT_LED_COUNT),
        )
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._theme = ThemeManager(self._state.primary_color)
        self._scene_manager = SceneManager(self._state.base_scene)
        self._events = EventManager()
        self._scene_library = SceneLibrary()
        self._effects = EffectLibrary()
        self._compositor = Compositor()
        self._mapper = SegmentMapper(total_leds=self._state.led_count, region_map=_parse_region_map(os.getenv("LED_REGION_MAP")))
        self._renderer = WLEDRenderer(self._state.led_count)
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
        self._sync_controller_state()
        threading.Thread(target=self._status_loop, daemon=True, name="leds-status-loop").start()
        threading.Thread(target=self._controller_probe_loop, daemon=True, name="leds-controller-probe").start()
        threading.Thread(target=self._render_loop, daemon=True, name="leds-render-loop").start()
        log.info("LEDs node started. SUB=%s PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
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
            self._renderer.refresh_status()
            self._sync_controller_state()
            time.sleep(CONTROLLER_POLL_INTERVAL)

    def _render_loop(self) -> None:
        next_tick = time.monotonic()
        while self._running.is_set():
            now = time.monotonic()
            self._scene_manager.tick(now)
            self._sync_scene_state(now)
            self._sync_controller_state()
            palette = self._theme.palette()
            scene_name = self._scene_manager.current_scene(now)
            scene_layers = self._scene_library.recipe(scene_name)
            frame = self._render_scene_layers(scene_layers, palette, now)
            previous_scene = self._scene_manager.previous_scene()
            progress = self._scene_manager.transition_progress(now)
            if previous_scene != scene_name and progress < 1.0:
                previous_layers = self._scene_library.recipe(previous_scene)
                previous_frame = self._render_scene_layers(previous_layers, palette, now)
                frame = self._blend_scene_frames(previous_frame, frame, progress)
            active_event_layers = self._events.active_layers(now)
            if active_event_layers:
                frame = self._compose_event_layers(frame, active_event_layers, palette, now)
            self._renderer.send_frame(frame, self._state.brightness, self._state.enabled)
            self._sync_controller_state()
            target_fps = self._target_fps(scene_name, active_event_layers)
            next_tick = max(next_tick + 1.0 / target_fps, now)
            sleep_for = max(0.0, next_tick - time.monotonic())
            time.sleep(sleep_for)

    def _target_fps(self, scene_name: str, active_events: list[LayerSpec]) -> float:
        if not self._state.enabled:
            return 1.0
        if active_events:
            return DEFAULT_RENDER_FPS
        if self._scene_manager.active_animation(time.monotonic()) is not None:
            return DEFAULT_RENDER_FPS
        if scene_name in STATIC_SCENES:
            return STATIC_RENDER_FPS
        return DEFAULT_RENDER_FPS

    def _render_scene_layers(self, layers: list[LayerSpec], palette: ThemePalette, now: float) -> list[tuple[int, int, int] | None]:
        frame = self._compositor.fill(self._mapper.total_leds)
        ordered_layers = sorted(layers, key=lambda layer: layer.priority)
        for layer in ordered_layers:
            indices = self._mapper.resolve_indices(layer.regions)
            rendered = self._effects.render(layer, indices, palette, now, self._mapper.total_leds)
            frame = self._compositor.blend(frame, rendered, layer.opacity)
        return frame

    def _blend_scene_frames(self, previous: list[tuple[int, int, int] | None], current: list[tuple[int, int, int] | None], progress: float) -> list[tuple[int, int, int] | None]:
        progress = _clamp(progress, 0.0, 1.0)
        blended: list[tuple[int, int, int] | None] = []
        for previous_color, current_color in zip(previous, current):
            if previous_color is None and current_color is None:
                blended.append(None)
            elif previous_color is None:
                blended.append(current_color)
            elif current_color is None:
                blended.append(previous_color)
            else:
                blended.append(_mix_rgb(previous_color, current_color, progress))
        return blended

    def _compose_event_layers(self, base_frame: list[tuple[int, int, int] | None], layers: list[LayerSpec], palette: ThemePalette, now: float) -> list[tuple[int, int, int] | None]:
        frame = list(base_frame)
        for layer in sorted(layers, key=lambda layer: layer.priority):
            indices = self._mapper.resolve_indices(layer.regions)
            rendered = self._effects.render(layer, indices, palette, now, self._mapper.total_leds)
            frame = self._compositor.blend(frame, rendered, layer.opacity)
        return frame

    def _sync_controller_state(self) -> None:
        with self._state._lock:
            self._state.controller_online = self._renderer.controller_online
            self._state.controller_name = self._renderer.controller_name
            self._state.led_count = self._renderer.led_count
            self._mapper.set_total_leds(self._state.led_count)

    def _sync_scene_state(self, now: float) -> None:
        active_animation = self._scene_manager.active_animation(now)
        with self._state._lock:
            self._state.base_scene = self._scene_manager.base_scene()
            self._state.animation_scene = active_animation
            self._state.animation_until = self._scene_manager.animation_until() if active_animation else None

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        assert self._zmq_push is not None
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _push_state(self, reason: str) -> None:
        payload = self._state.snapshot()
        payload["reason"] = reason
        self._push(TOPIC_LED_STATE, payload)

    def _push_status(self, online: bool) -> None:
        payload = {
            "status": "online" if online else "offline",
            "node": "leds",
            "controller_online": self._state.controller_online,
            "controller_name": self._state.controller_name,
            "led_count": self._state.led_count,
            "enabled": self._state.enabled,
            "brightness": self._state.brightness,
            "scene": self._scene_manager.current_scene(time.monotonic()),
            "primary_color": self._state.primary_color,
            "reactive_mode": self._state.reactive_mode,
        }
        self._push(TOPIC_STATUS, payload)
        self._push(TOPIC_STATUS_LEGACY, payload)

    def _set_scene(self, scene: str, reason: str, now: float | None = None) -> None:
        scene = scene.strip().lower() or "idle"
        self._scene_manager.set_base_scene(scene, now=now or time.monotonic())
        with self._state._lock:
            self._state.base_scene = scene
        log.info("%s: scene=%s", reason, scene)
        self._push_state(reason)

    def _handle_leds_toggle(self, payload: dict[str, Any]) -> None:
        enabled = _normalize_bool(payload.get("enabled"), default=self._state.enabled)
        with self._state._lock:
            self._state.enabled = enabled
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
        color = _normalize_color_text(payload.get("color"))
        if color is None:
            log.warning("leds-color: missing or invalid 'color' field")
            return
        self._theme.set_primary(color)
        with self._state._lock:
            self._state.primary_color = color
        log.info("leds-color: %s", color)
        self._push_state("color")

    def _handle_leds_effect(self, payload: dict[str, Any]) -> None:
        effect = payload.get("effect")
        scene = _normalize_color_text(payload.get("scene")) or effect
        if scene is None:
            log.warning("leds-effect: missing or invalid 'effect' field")
            return
        if effect not in SUPPORTED_EFFECTS and effect not in DEFAULT_SCENES:
            log.debug("leds-effect: unrecognized effect '%s', treating as scene name", effect)
        self._set_scene(scene, "effect")

    def _handle_leds_animation(self, payload: dict[str, Any]) -> None:
        animation = _normalize_color_text(payload.get("animation") or payload.get("scene") or payload.get("effect"))
        if animation is None:
            log.warning("leds-animation: missing or invalid animation identifier")
            return
        duration = payload.get("duration")
        now = time.monotonic()
        self._scene_manager.play_animation(animation, duration=float(duration) if isinstance(duration, (int, float)) else None, now=now)
        with self._state._lock:
            self._state.animation_scene = animation
            self._state.animation_until = now + max(0.05, float(duration) if isinstance(duration, (int, float)) else ANIMATION_DEFAULT_DURATION)
        log.info("leds-animation: animation=%s duration=%s", animation, duration)
        self._push_state("animation")

    def _handle_set_expression(self, payload: dict[str, Any]) -> None:
        expression = _normalize_color_text(payload.get("expression"))
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
        layer = LayerSpec(effect="pulse", regions=("body",), priority=35, params={"intensity": energy or 0.6, "palette": "highlight"}, opacity=0.85, ttl=0.20, name=f"{source}-fft")
        self._events.add(layer, time.monotonic())
        log.info("%s-fft: energy=%s", source, energy)
        self._push_state(f"{source}-fft")

    def _handle_internal_aed(self, payload: dict[str, Any]) -> None:
        self._handle_audio_event(payload, source="internal")

    def _handle_external_aed(self, payload: dict[str, Any]) -> None:
        self._handle_audio_event(payload, source="external")

    def _handle_audio_event(self, payload: dict[str, Any], source: str) -> None:
        label = _normalize_color_text(payload.get("event") or payload.get("label") or payload.get("type")) or "speech_started"
        confidence = payload.get("confidence")
        if isinstance(confidence, (int, float)):
            intensity = _clamp(float(confidence), 0.2, 1.0)
        else:
            intensity = 0.75
        with self._state._lock:
            self._state.reactive_mode = True
        if "speech" in label.lower():
            layer = LayerSpec(effect="pulse", regions=("body",), priority=40, params={"intensity": intensity, "palette": "accent"}, opacity=0.90, ttl=0.75, name=f"{source}-speech")
        else:
            layer = LayerSpec(effect="sparkle", regions=("body", "ears"), priority=30, params={"density": 0.12, "palette": "highlight"}, opacity=0.80, ttl=0.60, name=f"{source}-{label}")
        self._events.add(layer, time.monotonic())
        log.info("%s-aed: label=%s confidence=%s", source, label, confidence)
        self._push_state(f"{source}-aed")

    def _handle_external_beat(self, payload: dict[str, Any]) -> None:
        beat = self._extract_audio_metric(payload, "beat")
        with self._state._lock:
            self._state.last_beat_strength = beat
            self._state.reactive_mode = True
        layer = LayerSpec(effect="strobe", regions=("body", "ears"), priority=50, params={"frequency": 10.0 + (float(beat) * 8.0 if beat is not None else 0.0), "palette": "red"}, opacity=1.0, ttl=0.20, name="beat")
        self._events.add(layer, time.monotonic())
        log.info("external-beat: strength=%s", beat)
        self._push_state("beat")

    def _handle_external_music(self, payload: dict[str, Any]) -> None:
        detected = _normalize_bool(payload.get("detected"), default=True)
        with self._state._lock:
            self._state.reactive_mode = detected
        if detected:
            layer = LayerSpec(effect="rainbow", regions=("body",), priority=30, params={"speed": 0.9}, opacity=0.55, ttl=0.50, name="music")
            self._events.add(layer, time.monotonic())
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


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, _clamp(s, 0.0, 1.0), _clamp(v, 0.0, 1.0))
    return (round(r * 255), round(g * 255), round(b * 255))


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
