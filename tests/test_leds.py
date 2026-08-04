import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
import src.leds as leds


class DummyResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


class TestLedsNode(unittest.TestCase):
    def test_theme_palette_derivation(self) -> None:
        theme = leds.ThemeManager("#00ffff")
        palette = theme.palette()
        self.assertEqual(palette.primary, (0, 255, 255))
        self.assertNotEqual(palette.accent, palette.primary)
        self.assertNotEqual(palette.shadow, palette.primary)

    @patch("src.leds.time.sleep", return_value=None)
    @patch("src.leds.urllib.request.urlopen")
    def test_renderer_probes_catalog_and_builds_wled_payload(self, mock_urlopen, _mock_sleep) -> None:
        mock_urlopen.side_effect = [
            DummyResponse({"name": "WLED", "leds": {"count": 3}}),
            DummyResponse({"effects": ["Solid", "Rainbow", "Strobe"]}),
            DummyResponse({"palettes": ["Default", "Primary Color", "Rainbow"]}),
            DummyResponse({"success": True}),
        ]
        renderer = leds.WLEDRenderer(led_count=3, timeout=0.01, retries=0)
        self.assertTrue(renderer.probe())
        self.assertTrue(renderer.controller_online)
        self.assertEqual(renderer.controller_name, "WLED")
        self.assertEqual(renderer.led_count, 3)
        self.assertEqual(renderer.resolve_effect_id("Rainbow"), 1)
        self.assertEqual(renderer.resolve_palette_id("Rainbow"), 2)

        theme = leds.ThemeManager("#112233").palette()
        payload = renderer.build_state_payload(
            enabled=True,
            brightness=128,
            scene_name="happy",
            scene_spec=None,
            theme=theme,
        )
        self.assertEqual(payload["on"], True)
        self.assertEqual(payload["bri"], 128)
        self.assertEqual(payload["seg"][0]["fx"], renderer.resolve_effect_id("Rainbow"))
        self.assertEqual(payload["seg"][0]["pal"], renderer.resolve_palette_id("Rainbow"))
        self.assertEqual(payload["seg"][0]["col"][0], "112233")

        self.assertTrue(renderer.send_state(payload))
        self.assertEqual(mock_urlopen.call_count, 4)
        post_request = mock_urlopen.call_args_list[3].args[0]
        self.assertEqual(json.loads(post_request.data.decode("utf-8")), payload)

    def test_handlers_update_state_and_build_controller_payload(self) -> None:
        node = leds.LedsNode()
        node._push_state = MagicMock()

        node._handle_leds_color({"color": "#112233"})
        node._handle_leds_brightness({"brightness": 300})
        node._handle_set_expression({"scores": {"sad": 0.1, "happy": 0.9}})
        node._handle_leds_effect({"effect": "rainbow"})
        node._handle_leds_animation({"animation": "party", "duration": 0.1})
        node._handle_external_beat({"beat": 0.8})

        self.assertEqual(node._state.primary_color, "#112233")
        self.assertEqual(node._state.brightness, 255)
        self.assertEqual(node._state.base_scene, "rainbow")
        self.assertEqual(node._state.temporary_scene, "beat")
        self.assertTrue(node._state.reactive_mode)

        payload = node._build_controller_payload(time.monotonic())
        self.assertEqual(payload["seg"][0]["fx"], node._renderer.resolve_effect_id("Strobe"))
        self.assertEqual(payload["seg"][0]["col"][0], "FF0000")
        self.assertGreaterEqual(node._push_state.call_count, 6)

    def test_animation_expires_and_returns_to_base_scene(self) -> None:
        node = leds.LedsNode()
        node._push_state = MagicMock()

        node._handle_leds_animation({"animation": "party", "duration": 0.05})
        self.assertEqual(node._state.active_scene(time.monotonic()), "party")

        time.sleep(0.06)
        now = time.monotonic()
        self.assertTrue(node._state.expire_temporary_scene(now))
        self.assertIsNone(node._state.temporary_scene)
        self.assertEqual(node._state.active_scene(now), node._state.base_scene)


if __name__ == "__main__":
    unittest.main()
