import os
import sys
import tempfile
import threading
import time
import unittest
import zmq
from pathlib import Path
from unittest.mock import MagicMock, patch
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Patch pygame.mixer before importing the module so the hardware is never touched
with patch("pygame.mixer"):
    import src.audio_sfx as audio_sfx
    from src.audio_sfx import AudioSFXNode


class TestAudioSFXNodeCatalogue(unittest.TestCase):
    def _make_node(self, sfx_root: str) -> AudioSFXNode:
        """Create a node whose SFX_ROOT is patched to a controlled directory."""
        with patch("pygame.mixer"):
            with patch("src.audio_sfx.SFX_ROOT", sfx_root):
                node = AudioSFXNode.__new__(AudioSFXNode)
                node._running = threading.Event()
                node._zmq_ctx = None
                node._zmq_sub = None
                node._zmq_push = None
                node._handlers = {}
                node._catalogue = []
                node._load_sound_catalogue()
        return node

    def test_catalogue_loads_wav_mp3_ogg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("laser.wav", "explosion.mp3", "beep.ogg", "ignore.txt"):
                Path(tmpdir, name).touch()
            node = self._make_node(tmpdir)
            names = [e["name"] for e in node._catalogue]
            self.assertIn("laser", names)
            self.assertIn("explosion", names)
            self.assertIn("beep", names)
            self.assertNotIn("ignore", names)

    def test_catalogue_is_sorted_alphabetically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("zzz.wav", "aaa.wav", "mmm.wav"):
                Path(tmpdir, name).touch()
            node = self._make_node(tmpdir)
            names = [e["name"] for e in node._catalogue]
            self.assertEqual(names, sorted(names, key=str.lower))

    def test_catalogue_walks_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir, "system")
            subdir.mkdir()
            Path(subdir, "startup.wav").touch()
            Path(tmpdir, "alert.wav").touch()
            node = self._make_node(tmpdir)
            names = [e["name"] for e in node._catalogue]
            self.assertIn("startup", names)
            self.assertIn("alert", names)

    def test_catalogue_empty_when_dir_missing(self):
        node = self._make_node("/does/not/exist")
        self.assertEqual(node._catalogue, [])


class TestAudioSFXNodeResolver(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "laser.wav").touch()
        Path(self.tmpdir, "BOOM.MP3").touch()
        with patch("pygame.mixer"):
            with patch("src.audio_sfx.SFX_ROOT", self.tmpdir):
                self.node = AudioSFXNode.__new__(AudioSFXNode)
                self.node._running = threading.Event()
                self.node._zmq_ctx = None
                self.node._zmq_sub = None
                self.node._zmq_push = None
                self.node._handlers = {}
                self.node._catalogue = []
                self.node._load_sound_catalogue()

    def test_resolve_by_index(self):
        result = self.node._resolve_effect_path(0)
        self.assertIsNotNone(result)
        self.assertTrue(os.path.isabs(result))

    def test_resolve_out_of_range_index(self):
        self.assertIsNone(self.node._resolve_effect_path(999))

    def test_resolve_by_exact_filename(self):
        result = self.node._resolve_effect_path("laser.wav")
        self.assertIsNotNone(result)
        self.assertIn("laser", result)

    def test_resolve_by_stem_without_extension(self):
        result = self.node._resolve_effect_path("laser")
        self.assertIsNotNone(result)
        self.assertIn("laser", result)

    def test_resolve_case_insensitive_stem(self):
        result = self.node._resolve_effect_path("LASER")
        self.assertIsNotNone(result)

    def test_resolve_none_returns_none(self):
        self.assertIsNone(self.node._resolve_effect_path(None))

    def test_resolve_unknown_returns_none(self):
        self.assertIsNone(self.node._resolve_effect_path("nonexistent"))


class TestHandlePlaySoundEffect(unittest.TestCase):
    def setUp(self):
        with patch("pygame.mixer"):
            self.node = AudioSFXNode.__new__(AudioSFXNode)
        self.node._running = threading.Event()
        self.node._zmq_ctx = None
        self.node._zmq_sub = None
        self.node._zmq_push = None
        self.node._catalogue = [{"name": "laser", "filename": "laser.wav"}]

    @patch("pygame.mixer.stop")
    def test_stop_command_calls_mixer_stop(self, mock_stop):
        self.node._handle_play_sound_effect({"effectId": "stop"})
        mock_stop.assert_called_once()

    def test_missing_effect_id_logs_warning(self):
        self.node._resolve_effect_path = MagicMock(return_value=None)
        with self.assertLogs("audio_sfx", level="WARNING"):
            self.node._handle_play_sound_effect({"effectId": "ghost"})

    @patch("pygame.mixer.Sound")
    @patch("os.path.isfile", return_value=True)
    def test_valid_effect_plays_sound(self, mock_isfile, mock_sound_class):
        mock_sound = MagicMock()
        mock_sound_class.return_value = mock_sound
        self.node._resolve_effect_path = MagicMock(return_value="/sfx/laser.wav")
        self.node._handle_play_sound_effect({"effectId": "laser"})
        mock_sound_class.assert_called_once_with("/sfx/laser.wav")
        mock_sound.play.assert_called_once()

    @patch("os.path.isfile", return_value=False)
    def test_unresolvable_file_logs_error(self, mock_isfile):
        self.node._resolve_effect_path = MagicMock(return_value="/sfx/missing.wav")
        with self.assertLogs("audio_sfx", level="ERROR"):
            self.node._handle_play_sound_effect({"effectId": "missing"})

    @patch("pygame.mixer.Sound", side_effect=Exception("mixer error"))
    @patch("os.path.isfile", return_value=True)
    def test_playback_exception_is_caught(self, mock_isfile, mock_sound):
        self.node._resolve_effect_path = MagicMock(return_value="/sfx/bad.wav")
        self.node._handle_play_sound_effect({"effectId": "bad"}) # Should not raise


class TestHandleTextToSpeech(unittest.TestCase):
    def setUp(self):
        with patch("pygame.mixer"):
            self.node = AudioSFXNode.__new__(AudioSFXNode)
        self.node._running = threading.Event()
        self.node._zmq_ctx = None
        self.node._zmq_sub = None
        self.node._zmq_push = None
        self.node._catalogue = []

    def test_missing_text_logs_warning(self):
        with self.assertLogs("audio_sfx", level="WARNING"):
            self.node._handle_text_to_speech({})

    def test_empty_text_logs_warning(self):
        with self.assertLogs("audio_sfx", level="WARNING"):
            self.node._handle_text_to_speech({"text": ""})

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_logs_error(self):
        os.environ.pop("eleven_api_key", None)
        with self.assertLogs("audio_sfx", level="ERROR"):
            self.node._handle_text_to_speech({"text": "Hello"})

    @patch("pygame.mixer.Sound")
    @patch("src.audio_sfx.ElevenLabs")
    @patch.dict(os.environ, {"eleven_api_key": "test-key"})
    def test_tts_generates_and_plays_audio(self, mock_elevenlabs_class, mock_sound_class):
        # Set up ElevenLabs mock to return audio chunks
        mock_client = MagicMock()
        mock_elevenlabs_class.return_value = mock_client
        mock_client.text_to_speech.convert.return_value = [b"audio-chunk-1", b"audio-chunk-2"]
        mock_sound = MagicMock()
        mock_sound.get_length.return_value = 0.1
        mock_sound_class.return_value = mock_sound
        with patch("os.remove"):
            self.node._handle_text_to_speech({"text": "Hello world"})
        mock_elevenlabs_class.assert_called_once_with(api_key="test-key")
        mock_client.text_to_speech.convert.assert_called_once()
        mock_sound.play.assert_called_once()

    @patch("src.audio_sfx.ElevenLabs", side_effect=Exception("API error"))
    @patch.dict(os.environ, {"eleven_api_key": "test-key"})
    def test_tts_api_exception_is_caught(self, mock_elevenlabs_class):
        # Should not raise
        self.node._handle_text_to_speech({"text": "Hello"})

    @patch("pygame.mixer.Sound")
    @patch("src.audio_sfx.ElevenLabs")
    @patch.dict(os.environ, {"eleven_api_key": "test-key"})
    def test_tts_temp_file_is_deleted_after_playback(self, mock_elevenlabs_class, mock_sound_class):
        mock_client = MagicMock()
        mock_elevenlabs_class.return_value = mock_client
        mock_client.text_to_speech.convert.return_value = [b"data"]
        mock_sound = MagicMock()
        mock_sound.get_length.return_value = 0.01   # Very short so cleanup runs quickly
        mock_sound_class.return_value = mock_sound
        removed_files: list[str] = []
        original_remove = os.remove
        def capturing_remove(path):
            removed_files.append(path)
        with patch("os.remove", side_effect=capturing_remove):
            self.node._handle_text_to_speech({"text": "Delete me"})
            time.sleep(0.3) # Give cleanup thread time to run
        self.assertGreater(len(removed_files), 0)
        self.assertTrue(removed_files[0].endswith(".mp3"))


class TestZMQSetup(unittest.TestCase):
    @patch("src.audio_sfx.zmq.Context")
    def test_setup_zmq_creates_and_connects_sockets(self, mock_context_class):
        mock_context = MagicMock()
        mock_sub = MagicMock()
        mock_push = MagicMock()
        mock_context.socket.side_effect = [mock_sub, mock_push]
        mock_context_class.return_value = mock_context
        with patch("pygame.mixer"):
            node = AudioSFXNode.__new__(AudioSFXNode)
        node._catalogue = []
        node._running = threading.Event()
        node._zmq_ctx = None
        node._zmq_sub = None
        node._zmq_push = None
        node._setup_zmq()
        mock_context.socket.assert_any_call(zmq.SUB)
        mock_context.socket.assert_any_call(zmq.PUSH)
        mock_sub.connect.assert_called_with(audio_sfx.ZMQ_SUB_ADDRESS)
        mock_push.connect.assert_called_with(audio_sfx.ZMQ_PUSH_ADDRESS)
        for topic in audio_sfx.SUBSCRIBED_TOPICS:
            mock_sub.setsockopt.assert_any_call(zmq.SUBSCRIBE, topic)


class TestTeardown(unittest.TestCase):
    def test_teardown_closes_sockets_and_context(self):
        with patch("pygame.mixer"):
            node = AudioSFXNode.__new__(AudioSFXNode)
        node._running = threading.Event()
        node._zmq_ctx = MagicMock()
        node._zmq_sub = MagicMock()
        node._zmq_sub.closed = False
        node._zmq_push = MagicMock()
        node._zmq_push.closed = False
        node._catalogue = []
        with patch("pygame.mixer.quit"):
            node._teardown()
        node._zmq_sub.close.assert_called_once_with(linger=0)
        node._zmq_push.close.assert_called_once_with(linger=0)
        node._zmq_ctx.destroy.assert_called_once_with(linger=0)

    def test_teardown_skips_already_closed_sockets(self):
        with patch("pygame.mixer"):
            node = AudioSFXNode.__new__(AudioSFXNode)
        node._running = threading.Event()
        node._zmq_ctx = MagicMock()
        node._zmq_sub = MagicMock()
        node._zmq_sub.closed = True
        node._zmq_push = MagicMock()
        node._zmq_push.closed = True
        node._catalogue = []
        with patch("pygame.mixer.quit"):
            node._teardown()
        node._zmq_sub.close.assert_not_called()
        node._zmq_push.close.assert_not_called()


class TestSubscribedTopics(unittest.TestCase):
    def test_play_sound_effect_topic_in_subscribed(self):
        self.assertIn(audio_sfx.TOPIC_PLAY_SOUND_EFFECT, audio_sfx.SUBSCRIBED_TOPICS)

    def test_text_to_speech_topic_in_subscribed(self):
        self.assertIn(audio_sfx.TOPIC_TEXT_TO_SPEECH, audio_sfx.SUBSCRIBED_TOPICS)


if __name__ == "__main__":
    unittest.main()
