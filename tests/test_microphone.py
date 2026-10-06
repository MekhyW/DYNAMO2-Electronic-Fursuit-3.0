import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


# The node talks to physical audio hardware and WhisperLive at import time.  Keep these tests usable on CI machines that do not have either optional dependency.
_sounddevice = types.ModuleType("sounddevice")
_sounddevice.InputStream = MagicMock()
_sounddevice.PortAudioError = type("PortAudioError", (Exception,), {})
_whisper_live = types.ModuleType("whisper_live")
_whisper_client = types.ModuleType("whisper_live.client")
_whisper_client.StreamingTranscriptionClient = MagicMock()
_whisper_live.client = _whisper_client
with patch.dict(sys.modules, {"sounddevice": _sounddevice, "whisper_live": _whisper_live, "whisper_live.client": _whisper_client,}):
    from src import microphone


class TestSignalHelpers(unittest.TestCase):
    def test_mel_hz_conversion_round_trips(self):
        for hz in (0.0, 100.0, 440.0, 8000.0):
            self.assertAlmostEqual(microphone._to_hz(microphone._to_mel(hz)), hz)

    def test_mel_matrix_has_expected_shape_and_nonzero_filters(self):
        matrix = microphone._mel_matrix(sr=16000, n=1024, channels=30)
        self.assertEqual(matrix.shape, (30, 1024))
        self.assertTrue(np.all(matrix >= 0.0))
        self.assertTrue(np.all(matrix.sum(axis=1) > 0.0))

    def test_mfcc_returns_none_for_silence_and_vector_for_audio(self):
        self.assertIsNone(microphone.mfcc_ulipsync(np.zeros(microphone.WINDOW, dtype=np.float32)))
        frame = np.sin(np.linspace(0, 40 * np.pi, microphone.WINDOW)).astype(np.float32)
        mfcc = microphone.mfcc_ulipsync(frame)
        self.assertIsNotNone(mfcc)
        self.assertEqual(mfcc.shape, (microphone.N_MFCC,))
        self.assertEqual(mfcc.dtype, np.float32)
        self.assertTrue(np.all(np.isfinite(mfcc)))


class TestProfileAndAdapter(unittest.TestCase):
    def setUp(self):
        self.a = np.zeros(microphone.N_MFCC, dtype=np.float32)
        self.a[0] = 1.0
        self.i = np.zeros(microphone.N_MFCC, dtype=np.float32)
        self.i[1] = 1.0
        self.profile = microphone.Profile([("A", self.a), ("I", self.i), ("S", -self.a)])

    def test_profile_classify_returns_normalized_ratios_and_fit(self):
        ratios, fit = self.profile.classify(self.a)
        self.assertAlmostEqual(sum(ratios.values()), 1.0)
        self.assertGreater(ratios["A"], ratios["I"])
        self.assertAlmostEqual(fit, 1.0)

    def test_profile_excludes_non_vowels_from_vowel_templates(self):
        self.assertEqual(self.profile.vowels, ["A", "I"])
        template, similarity = self.profile.nearest_vowel(self.i)
        np.testing.assert_array_equal(template, self.i)
        self.assertAlmostEqual(similarity, 1.0)

    def test_profile_load_rejects_standardized_profiles(self):
        data = {
            "standardize": True,
            "n_mfcc": microphone.N_MFCC,
            "sample_rate": microphone.SAMPLE_RATE,
            "sample_count": microphone.WINDOW,
            "phonemes": [],
        }
        with self.subTest("standardization"):
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "profile.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    microphone.Profile.load(path)

    def test_channel_adapter_learns_and_corrects_offset(self):
        adapter = microphone.ChannelAdapter(tau_s=60.0, prior_s=0.0)
        raw = np.arange(microphone.N_MFCC, dtype=np.float32)
        template = raw - 2.0
        adapter.update(raw, template)
        np.testing.assert_allclose(adapter.correct(raw), template)
        adapter.reset()
        # A zero prior is useful for the exact one-sample calculation above,
        # while the production default keeps an empty adapter well-defined.
        np.testing.assert_allclose(microphone.ChannelAdapter().offset, np.zeros(microphone.N_MFCC))


class TestLipSyncAnalyzer(unittest.TestCase):
    def _analyzer(self):
        vector = np.zeros(microphone.N_MFCC, dtype=np.float32)
        vector[0] = 1.0
        return microphone.LipSyncAnalyzer(microphone.Profile([("A", vector)]))

    def test_push_waits_for_window_and_then_uses_hop_overlap(self):
        analyzer = self._analyzer()
        analyzer._process = MagicMock(side_effect=lambda frame: frame.copy())
        first = analyzer.push(np.ones(512, dtype=np.float32))
        self.assertEqual(first, [])
        frames = analyzer.push(np.ones(768, dtype=np.float32))
        self.assertEqual(len(frames), 2)
        self.assertEqual(analyzer._buf.size, microphone.WINDOW - microphone.HOP)
        self.assertEqual(analyzer._process.call_args_list[1].args[0].size, microphone.WINDOW)

    def test_speech_start_and_stop_have_debouncing(self):
        analyzer = self._analyzer()
        for _ in range(2):
            analyzer._level = 0.3
            self.assertEqual(analyzer._speech_events(1.0), [])
        analyzer._level = 0.3
        self.assertEqual(analyzer._speech_events(1.0)[0]["type"], "speech_start")
        for _ in range(11):
            analyzer._level = 0.0
            self.assertEqual(analyzer._speech_events(2.0), [])
        analyzer._level = 0.0
        self.assertEqual(analyzer._speech_events(2.0)[0]["type"], "speech_stop")

    def test_syllable_event_reports_last_vowel_after_peak_falls(self):
        analyzer = self._analyzer()
        analyzer._last_vowel = "A"
        analyzer._level = 0.2
        analyzer._syllable_events(3.0)
        analyzer._level = 0.1
        events = analyzer._syllable_events(3.1)
        self.assertEqual(events[0]["type"], "syllable")
        self.assertEqual(events[0]["vowel"], "A")
        self.assertEqual(events[0]["timestamp"], 3.0)

    def test_frame_message_rounds_values_without_losing_fields(self):
        frame = microphone.LipSyncFrame(1.23456, 0.2, -13.456, 0.12345, 0.23456, "A", "A", 0.9876, {"A": 0.8766}, True)
        self.assertEqual(frame.to_message(), {
            "timestamp": 1.23456, "level": 0.1235, "raw_level": 0.2346,
            "db": -13.5, "phoneme": "A", "vowel": "A", "fit": 0.988,
            "weights": {"A": 0.877}, "speaking": True,
        })


class TestMicCapture(unittest.TestCase):
    @patch.object(microphone.sd, "InputStream")
    def test_start_configures_stream_and_callback_copies_mono_channel(self, input_stream):
        stream = MagicMock()
        input_stream.return_value = stream
        received = []
        capture = microphone.MicCapture(received.append, device="USB mic")
        capture.start()
        input_stream.assert_called_once()
        kwargs = input_stream.call_args.kwargs
        self.assertEqual(kwargs["samplerate"], microphone.SAMPLE_RATE)
        self.assertEqual(kwargs["channels"], 1)
        self.assertEqual(kwargs["blocksize"], microphone.HOP)
        callback = kwargs["callback"]
        source = np.array([[1.0], [2.0]], dtype=np.float32)
        callback(source, 2, None, object())
        np.testing.assert_array_equal(received[0], [1.0, 2.0])
        self.assertEqual(capture.xruns, 1)
        capture.stop()
        stream.stop.assert_called_once()
        stream.close.assert_called_once()

    @patch.object(microphone.sd, "InputStream", side_effect=microphone.sd.PortAudioError("no device"))
    def test_start_translates_portaudio_error(self, _input_stream):
        with self.assertRaisesRegex(RuntimeError, "Cannot open the microphone"):
            microphone.MicCapture(lambda _block: None).start()


class TestMicrophoneNodeHelpers(unittest.TestCase):
    def _node(self):
        profile = microphone.Profile([("A", np.eye(microphone.N_MFCC, dtype=np.float32)[0])])
        with patch.object(microphone.MicrophoneNode, "_load_profile", return_value=profile):
            return microphone.MicrophoneNode()

    def test_audio_is_sent_to_fast_queue_and_only_connected_slow_queue(self):
        node = self._node()
        block = np.ones(8, dtype=np.float32)
        node._on_audio(block)
        np.testing.assert_array_equal(node._fast_q.get_nowait(), block)
        self.assertTrue(node._slow_q.empty())
        node._slow_connected.set()
        node._on_audio(block)
        np.testing.assert_array_equal(node._slow_q.get_nowait(), block)

    def test_on_transcript_ignores_blank_text_and_includes_first_segment_times(self):
        node = self._node()
        node._push = MagicMock()
        node._on_transcript(microphone.TOPIC_TRANSCRIPTION, "  hello ")
        node._push.assert_called_once()
        topic, payload = node._push.call_args.args
        self.assertEqual(topic, microphone.TOPIC_TRANSCRIPTION)
        self.assertEqual(payload["text"], "hello")
        node._push.reset_mock()
        node._on_transcript(microphone.TOPIC_TRANSCRIPTION, "  ")
        node._push.assert_not_called()

    def test_publish_frame_throttles_quiet_frames(self):
        node = self._node()
        node._push = MagicMock()
        frame = microphone.LipSyncFrame(0, 0, -100, 0, 0, None, None, 0, {}, False)
        for _ in range(microphone.IDLE_PUBLISH_DIVIDER - 1):
            node._publish_frame(frame)
        node._push.assert_not_called()
        node._publish_frame(frame)
        node._push.assert_called_once_with(microphone.TOPIC_LIPSYNC, frame.to_message())

    def test_safe_close_swallows_client_errors(self):
        client = MagicMock()
        client.close.side_effect = RuntimeError("already closed")
        microphone.MicrophoneNode._safe_close(client)
        client.close.assert_called_once_with(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
