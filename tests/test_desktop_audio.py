"""test_desktop_audio.py — Unit tests for desktop audio FFT analysis and publishing."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import zmq

from src.desktop_audio import (
    FFTBandAnalyzer,
    DesktopAudioNode,
    _band_indices,
    _find_loopback_device,
    _mel_edges,
    HOP,
    SAMPLE_RATE,
    WINDOW,
    N_BANDS,
    TOPIC_FFT,
)


class TestMelEdgesAndBandIndices(unittest.TestCase):
    def test_mel_edges_monotonic_and_correct_length(self) -> None:
        edges = _mel_edges(16, 44100, f_min=20.0, f_max=20000.0)
        self.assertEqual(len(edges), 18)
        self.assertTrue(np.all(np.diff(edges) > 0))

    def test_band_indices_coverage(self) -> None:
        indices = _band_indices(WINDOW, SAMPLE_RATE, N_BANDS)
        self.assertEqual(len(indices), N_BANDS)
        for lo, hi in indices:
            self.assertGreaterEqual(lo, 0)
            self.assertGreaterEqual(hi, lo)


class TestFFTBandAnalyzer(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = FFTBandAnalyzer(sr=SAMPLE_RATE, n_fft=WINDOW, n_bands=N_BANDS)

    def test_push_incomplete_window_returns_empty(self) -> None:
        block = np.zeros(WINDOW // 2, dtype=np.float32)
        results = self.analyzer.push(block)
        self.assertEqual(results, [])

    def test_push_full_window_returns_payload(self) -> None:
        block = np.zeros(WINDOW + HOP, dtype=np.float32)
        results = self.analyzer.push(block)
        self.assertGreaterEqual(len(results), 1)

        payload = results[0]
        self.assertIn("bands", payload)
        self.assertIn("energy", payload)
        self.assertIn("magnitude", payload)
        self.assertIn("major_peak", payload)
        self.assertIn("peak", payload)
        self.assertEqual(len(payload["bands"]), N_BANDS)

    def test_sine_wave_activates_expected_peak(self) -> None:
        freq = 1000.0  # 1 kHz sine
        t = np.arange(WINDOW * 2) / float(SAMPLE_RATE)
        signal = (np.sin(2 * np.pi * freq * t) * 0.8).astype(np.float32)

        results = self.analyzer.push(signal)
        self.assertTrue(len(results) > 0)
        last_res = results[-1]
        self.assertAlmostEqual(last_res["major_peak"], freq, delta=50.0)
        self.assertGreater(last_res["energy"], 0.0)

    def test_peak_detection_lifecycle(self) -> None:
        analyzer = FFTBandAnalyzer(sr=SAMPLE_RATE, n_fft=WINDOW, n_bands=N_BANDS)
        # Force high energy
        analyzer._peak_armed = True
        analyzer._energy_smooth = 0.8
        res = analyzer._process(np.ones(WINDOW, dtype=np.float32))
        self.assertTrue(res["peak"])
        self.assertFalse(analyzer._peak_armed)

        # Drop energy below reset
        analyzer._energy_smooth = 0.1
        res = analyzer._process(np.zeros(WINDOW, dtype=np.float32))
        self.assertFalse(res["peak"])
        self.assertTrue(analyzer._peak_armed)


class TestDeviceLookup(unittest.TestCase):
    def test_hint_returns_directly(self) -> None:
        self.assertEqual(_find_loopback_device(2), 2)
        self.assertEqual(_find_loopback_device("default"), "default")

    @patch("sounddevice.query_devices")
    def test_finds_loopback_device(self, mock_query: MagicMock) -> None:
        mock_query.return_value = [
            {"name": "Microphone", "max_input_channels": 1},
            {"name": "Stereo Mix (Realtek Audio)", "max_input_channels": 2},
        ]
        self.assertEqual(_find_loopback_device(), 1)

    @patch("sounddevice.query_devices")
    def test_no_loopback_returns_none(self, mock_query: MagicMock) -> None:
        mock_query.return_value = [
            {"name": "Microphone", "max_input_channels": 1},
        ]
        self.assertIsNone(_find_loopback_device())


class TestDesktopAudioNode(unittest.TestCase):
    def setUp(self) -> None:
        self.node = DesktopAudioNode()
        self.node._zmq_push = MagicMock()

    def test_publish_encodes_and_sends(self) -> None:
        payload = {"bands": [0.1] * 16, "energy": 0.5, "peak": False}
        self.node._publish(payload)

        self.node._zmq_push.send_multipart.assert_called_once()
        args, kwargs = self.node._zmq_push.send_multipart.call_args
        self.assertEqual(args[0][0], TOPIC_FFT)
        self.assertEqual(json.loads(args[0][1]), payload)
        self.assertEqual(kwargs.get("flags"), zmq.NOBLOCK)
        self.assertEqual(self.node._packets_sent, 1)

    def test_publish_handles_zmq_again(self) -> None:
        self.node._zmq_push.send_multipart.side_effect = zmq.Again()
        payload = {"bands": [0.1] * 16}
        self.node._publish(payload)
        self.assertEqual(self.node._packets_sent, 0)

    def test_audio_callback_processes_samples(self) -> None:
        indata = np.ones((HOP, 1), dtype=np.float32)
        with patch.object(self.node._analyzer, "push", return_value=[{"energy": 0.5}]) as mock_push:
            self.node._audio_callback(indata, HOP, None, None)
            mock_push.assert_called_once()
            self.node._zmq_push.send_multipart.assert_called_once()

    def test_lifecycle_blocks_until_stopped(self) -> None:
        import threading
        import time

        with patch.object(self.node, "_setup_zmq"), \
             patch.object(self.node, "_start_capture"), \
             patch.object(self.node, "_teardown"):
            t = threading.Thread(target=self.node.start)
            t.start()
            time.sleep(0.05)
            self.assertTrue(t.is_alive())
            self.assertTrue(self.node._running.is_set())

            self.node.stop()
            t.join(timeout=1.0)
            self.assertFalse(t.is_alive())
            self.assertFalse(self.node._running.is_set())


if __name__ == "__main__":
    unittest.main()
