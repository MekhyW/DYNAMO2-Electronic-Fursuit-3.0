"""Tests for src/leds.py."""
from __future__ import annotations

import json
import struct
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
import src.leds as leds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _make_node() -> leds.LedsNode:
    """Return a LedsNode with I/O mocked out."""
    node = leds.LedsNode()
    node._push_state = MagicMock()
    node._push = MagicMock()
    # Replace the real UDP sender with a spy so tests don't touch the network
    node._audio_sync = MagicMock(spec=leds.WLEDAudioSync)
    node._audio_sync.send.return_value = True
    return node


# ---------------------------------------------------------------------------
# Theme / palette
# ---------------------------------------------------------------------------

class TestThemePalette(unittest.TestCase):
    def test_palette_derivation(self) -> None:
        theme = leds.ThemeManager("#00ffff")
        palette = theme.palette()
        self.assertEqual(palette.primary, (0, 255, 255))
        self.assertNotEqual(palette.accent, palette.primary)
        self.assertNotEqual(palette.shadow, palette.primary)


# ---------------------------------------------------------------------------
# WLEDRenderer
# ---------------------------------------------------------------------------

class TestWLEDRenderer(unittest.TestCase):
    @patch("src.leds.time.sleep", return_value=None)
    @patch("src.leds.urllib.request.urlopen")
    def test_probe_and_payload(self, mock_urlopen: MagicMock, _sleep: MagicMock) -> None:
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


# ---------------------------------------------------------------------------
# WLEDAudioSync — packet encoding
# ---------------------------------------------------------------------------

class TestWLEDAudioSync(unittest.TestCase):
    def _sync(self) -> leds.WLEDAudioSync:
        """Return a WLEDAudioSync with the UDP socket mocked."""
        with patch("src.leds.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            sync = leds.WLEDAudioSync(addr="239.0.0.1", port=11988)
            sync._mock_sock = mock_sock
        return sync

    def test_send_emits_44_byte_packet_with_correct_header(self) -> None:
        sync = self._sync()
        sync.send(bands=[0.5] * 16, volume=0.5)
        packet: bytes = sync._mock_sock.sendto.call_args.args[0]
        self.assertEqual(len(packet), 44)
        self.assertEqual(packet[:6], b"00002\x00")

    def test_send_encodes_volume_scaled_to_0_255(self) -> None:
        sync = self._sync()
        sync.send(bands=[0.0] * 16, volume=1.0)
        packet = sync._mock_sock.sendto.call_args.args[0]
        raw_wire = struct.unpack_from("<f", packet, 8)[0]   # sampleRaw at offset 8
        self.assertAlmostEqual(raw_wire, 255.0, places=2)

    def test_send_sets_peak_byte(self) -> None:
        sync = self._sync()
        sync.send(bands=[0.0] * 16, volume=0.0, peak=True)
        packet = sync._mock_sock.sendto.call_args.args[0]
        self.assertEqual(packet[16], 1)                     # samplePeak at offset 16

    def test_frame_counter_increments(self) -> None:
        sync = self._sync()
        sync.send(bands=[0.0] * 16, volume=0.0)
        p1 = sync._mock_sock.sendto.call_args.args[0]
        sync.send(bands=[0.0] * 16, volume=0.0)
        p2 = sync._mock_sock.sendto.call_args.args[0]
        self.assertEqual(p2[17], p1[17] + 1)               # frameCounter at offset 17

    def test_major_peak_hz_is_written_to_last_float(self) -> None:
        sync = self._sync()
        sync.send(bands=[0.0] * 16, volume=0.0, major_peak_hz=440.0)
        packet = sync._mock_sock.sendto.call_args.args[0]
        hz = struct.unpack_from("<f", packet, 40)[0]        # FFT_MajorPeak at offset 40
        self.assertAlmostEqual(hz, 440.0, places=1)

    def test_socket_error_returns_false(self) -> None:
        sync = self._sync()
        sync._mock_sock.sendto.side_effect = OSError("network down")
        self.assertFalse(sync.send(bands=[0.0] * 16, volume=0.0))

    def test_send_returns_false_when_socket_is_none(self) -> None:
        sync = self._sync()
        sync._sock = None
        self.assertFalse(sync.send(bands=[0.0] * 16, volume=0.0))

    def test_resample_passthrough_for_equal_length(self) -> None:
        src = [float(i) for i in range(16)]
        self.assertEqual(leds.WLEDAudioSync._resample_bands(src, 16), src)

    def test_resample_empty_source_gives_zeros(self) -> None:
        self.assertEqual(leds.WLEDAudioSync._resample_bands([], 16), [0.0] * 16)

    def test_resample_preserves_endpoints(self) -> None:
        src = [0.0, 0.5, 1.0]
        out = leds.WLEDAudioSync._resample_bands(src, 5)
        self.assertAlmostEqual(out[0], 0.0)
        self.assertAlmostEqual(out[-1], 1.0)
        self.assertEqual(len(out), 5)

    def test_close_shuts_socket(self) -> None:
        sync = self._sync()
        sync.close()
        sync._mock_sock.close.assert_called_once()
        self.assertIsNone(sync._sock)


# ---------------------------------------------------------------------------
# LedsNode._handle_fft
# ---------------------------------------------------------------------------

class TestHandleFft(unittest.TestCase):
    def test_full_payload_calls_audio_sync_send(self) -> None:
        node = _make_node()
        node._handle_fft({
            "bands": [0.1 * i for i in range(8)],
            "energy": 0.42,
            "magnitude": 0.7,
            "major_peak": 880.0,
            "peak": True,
        })
        node._audio_sync.send.assert_called_once_with(
            bands=[0.1 * i for i in range(8)],
            volume=0.42,
            magnitude=0.7,
            major_peak_hz=880.0,
            peak=True,
        )
        self.assertAlmostEqual(node._state.last_audio_energy, 0.42)

    def test_minimal_payload_falls_back_to_band_mean_for_energy(self) -> None:
        node = _make_node()
        node._handle_fft({"bands": [0.2, 0.4, 0.6, 0.8]})
        kw = node._audio_sync.send.call_args.kwargs
        self.assertAlmostEqual(kw["volume"], 0.5)   # mean([0.2, 0.4, 0.6, 0.8])

    def test_empty_payload_sends_zero_energy(self) -> None:
        node = _make_node()
        node._handle_fft({})
        self.assertEqual(node._audio_sync.send.call_args.kwargs["volume"], 0.0)
        self.assertIsNone(node._state.last_audio_energy)

    def test_magnitude_defaults_to_energy_when_absent(self) -> None:
        node = _make_node()
        node._handle_fft({"energy": 0.6})
        self.assertAlmostEqual(node._audio_sync.send.call_args.kwargs["magnitude"], 0.6)

    def test_peak_false_by_default(self) -> None:
        node = _make_node()
        node._handle_fft({"energy": 0.3})
        self.assertFalse(node._audio_sync.send.call_args.kwargs["peak"])

    def test_nonzero_energy_stored_in_state(self) -> None:
        node = _make_node()
        node._handle_fft({"energy": 0.75})
        self.assertAlmostEqual(node._state.last_audio_energy, 0.75)

    def test_zero_energy_stores_none(self) -> None:
        node = _make_node()
        node._handle_fft({"energy": 0.0})
        self.assertIsNone(node._state.last_audio_energy)


# ---------------------------------------------------------------------------
# LedsNode — other handlers
# ---------------------------------------------------------------------------

class TestLedsHandlers(unittest.TestCase):
    def test_set_expression_updates_scene(self) -> None:
        node = _make_node()
        node._handle_set_expression({"expression": "happy"})
        self.assertEqual(node._state.base_scene, "happy")

    def test_expression_scores_picks_highest(self) -> None:
        node = _make_node()
        node._handle_expression_scores({"sad": 0.1, "happy": 0.9, "angry": 0.3})
        self.assertEqual(node._state.base_scene, "happy")

    def test_handle_leds_toggle(self) -> None:
        node = _make_node()
        node._handle_leds_toggle({"enabled": False})
        self.assertFalse(node._state.enabled)
        node._handle_leds_toggle({"enabled": True})
        self.assertTrue(node._state.enabled)

    def test_handle_leds_brightness_clamps(self) -> None:
        node = _make_node()
        node._handle_leds_brightness({"brightness": 9999})
        self.assertEqual(node._state.brightness, 255)

    def test_handle_leds_color(self) -> None:
        node = _make_node()
        node._handle_leds_color({"color": "#ff0000"})
        self.assertEqual(node._state.primary_color, "#ff0000")

    def test_handle_leds_effect(self) -> None:
        node = _make_node()
        node._handle_leds_effect({"effect": "rainbow"})
        self.assertEqual(node._state.base_scene, "rainbow")

    def test_handle_leds_animation_sets_temporary_scene(self) -> None:
        node = _make_node()
        node._handle_leds_animation({"animation": "party", "duration": 0.1})
        self.assertEqual(node._state.temporary_scene, "party")

    def test_animation_expires_and_returns_to_base_scene(self) -> None:
        node = _make_node()
        node._handle_leds_animation({"animation": "party", "duration": 0.05})
        self.assertEqual(node._state.active_scene(time.monotonic()), "party")
        future = time.monotonic() + 1.0
        self.assertTrue(node._state.expire_temporary_scene(future))
        self.assertIsNone(node._state.temporary_scene)
        self.assertEqual(node._state.active_scene(future), node._state.base_scene)


if __name__ == "__main__":
    unittest.main()
