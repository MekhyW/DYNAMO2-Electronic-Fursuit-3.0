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
    def __init__(self, payload: dict[str, object]) -> None:
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

    def test_segment_mapper_resolves_full_strip_and_regions(self) -> None:
        mapper = leds.SegmentMapper()
        full_strip = mapper.resolve_indices()
        self.assertEqual(len(full_strip), leds.DEFAULT_LED_COUNT)
        self.assertEqual(full_strip[0], 0)
        self.assertEqual(full_strip[-1], leds.DEFAULT_LED_COUNT - 1)
        body = mapper.resolve_indices(["body"])
        self.assertIn(0, body)
        self.assertIn(180, body)
        self.assertNotIn(181, body)

    @patch("src.leds.time.sleep", return_value=None)
    @patch("src.leds.urllib.request.urlopen")
    def test_renderer_primes_controller_then_streams_frame(self, mock_urlopen, _mock_sleep) -> None:
        mock_urlopen.side_effect = [
            DummyResponse({"info": {"name": "WLED", "leds": {"count": 3}}}),
            DummyResponse({"success": True}),
            DummyResponse({"success": True}),
        ]
        renderer = leds.WLEDRenderer(led_count=3, timeout=0.01, retries=0)
        renderer.probe()
        self.assertTrue(renderer.controller_online)
        self.assertEqual(renderer.controller_name, "WLED")
        self.assertEqual(renderer.led_count, 3)
        ok = renderer.send_frame([(1, 2, 3), (4, 5, 6), (7, 8, 9)], brightness=128, enabled=True)
        self.assertTrue(ok)
        self.assertEqual(mock_urlopen.call_count, 3)
        activate_request = mock_urlopen.call_args_list[1].args[0]
        frame_request = mock_urlopen.call_args_list[2].args[0]
        self.assertEqual(json.loads(activate_request.data.decode("utf-8")), {"on": True, "bri": 128, "transition": 0, "v": True})
        frame_payload = json.loads(frame_request.data.decode("utf-8"))
        self.assertEqual(frame_payload["seg"][0]["i"], ["010203", "040506", "070809"])

    def test_handlers_update_scene_and_queue_events(self) -> None:
        node = leds.LedsNode()
        node._push_state = MagicMock()
        node._handle_leds_color({"color": "#112233"})
        self.assertEqual(node._state.primary_color, "#112233")
        node._handle_leds_brightness({"brightness": 300})
        self.assertEqual(node._state.brightness, 255)
        node._handle_set_expression({"scores": {"sad": 0.1, "happy": 0.9}})
        self.assertEqual(node._state.base_scene, "happy")
        node._handle_leds_animation({"animation": "rainbow", "duration": 0.1})
        self.assertEqual(node._state.animation_scene, "rainbow")
        self.assertIsNotNone(node._state.animation_until)
        node._handle_external_beat({"beat": 0.8})
        self.assertTrue(node._state.reactive_mode)
        active_layers = node._events.active_layers(time.monotonic())
        self.assertTrue(any(layer.effect == "strobe" for layer in active_layers))
        self.assertGreaterEqual(node._push_state.call_count, 4)

    def test_animation_expires_and_scene_state_syncs(self) -> None:
        node = leds.LedsNode()
        node._push_state = MagicMock()
        node._handle_leds_animation({"animation": "party", "duration": 0.05})
        time.sleep(0.06)
        now = time.monotonic()
        node._scene_manager.tick(now)
        node._sync_scene_state(now)
        self.assertIsNone(node._state.animation_scene)
        self.assertIsNone(node._state.animation_until)


if __name__ == "__main__":
    unittest.main()
