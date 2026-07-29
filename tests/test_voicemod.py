import unittest
from unittest.mock import MagicMock, patch
import zmq
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
import src.voicemod as voicemod

class TestVoicemodNode(unittest.TestCase):
    def setUp(self):
        self.node = voicemod.VoicemodNode()
        # Mock voices and sounds data
        self.node._voices = [
            {"name": "Astronaut", "id": "uuid-astro-123"},
            {"name": "Custom Voice", "id": "uuid-custom-456"},
            {"name": "Robot", "id": "uuid-robot-789"}
        ]
        self.node._sounds = [
            {"name": "applause", "id": "applause.mp3"},
            {"name": "laughter", "id": "laughter.mp3"}
        ]

    def test_resolve_voice_id(self):
        self.assertEqual(self.node._resolve_voice_id(0), "uuid-astro-123")
        self.assertEqual(self.node._resolve_voice_id(2), "uuid-robot-789")
        self.assertIsNone(self.node._resolve_voice_id(10))
        self.assertEqual(self.node._resolve_voice_id("uuid-custom-456"), "uuid-custom-456")
        self.assertEqual(self.node._resolve_voice_id("robot"), "uuid-robot-789")
        self.assertEqual(self.node._resolve_voice_id("ASTRONAUT"), "uuid-astro-123")
        self.assertEqual(self.node._resolve_voice_id("1"), "uuid-custom-456")
        self.assertEqual(self.node._resolve_voice_id("unknown-uuid"), "unknown-uuid")
        self.assertIsNone(self.node._resolve_voice_id(None))

    def test_resolve_sound_id(self):
        self.assertEqual(self.node._resolve_sound_id(0), "applause.mp3")
        self.assertEqual(self.node._resolve_sound_id(1), "laughter.mp3")
        self.assertIsNone(self.node._resolve_sound_id(5))
        self.assertEqual(self.node._resolve_sound_id("laughter.mp3"), "laughter.mp3")
        self.assertEqual(self.node._resolve_sound_id("applause"), "applause.mp3")
        self.assertEqual(self.node._resolve_sound_id("LAUGHTER"), "laughter.mp3")
        self.assertEqual(self.node._resolve_sound_id("0"), "applause.mp3")
        self.assertEqual(self.node._resolve_sound_id("custom.mp3"), "custom.mp3")
        self.assertIsNone(self.node._resolve_sound_id(None))

    @patch("src.voicemod.zmq.Context")
    def test_node_zmq_setup(self, mock_context_class):
        mock_context = MagicMock()
        mock_sub = MagicMock()
        mock_push = MagicMock()
        mock_context.socket.side_effect = [mock_sub, mock_push]
        mock_context_class.return_value = mock_context
        node = voicemod.VoicemodNode()
        node._setup_zmq()
        mock_context.socket.assert_any_call(zmq.SUB)
        mock_context.socket.assert_any_call(zmq.PUSH)
        mock_sub.connect.assert_called_with(voicemod.ZMQ_SUB_ADDRESS)
        mock_push.connect.assert_called_with(voicemod.ZMQ_PUSH_ADDRESS)
        for topic in voicemod.SUBSCRIBED_TOPICS:
            mock_sub.setsockopt.assert_any_call(zmq.SUBSCRIBE, topic)

    def test_publish_voice_effects(self):
        node = voicemod.VoicemodNode()
        node._voices = self.node._voices
        node._push = MagicMock()
        node._publish_voice_effects()
        expected_payload = [
            {"id": 'uuid-astro-123', "name": "Astronaut", "type": "modulation"},
            {"id": 'uuid-custom-456', "name": "Custom Voice", "type": "modulation"},
            {"id": 'uuid-robot-789', "name": "Robot", "type": "modulation"}
        ]
        node._push.assert_called_once_with(voicemod.TOPIC_DATA_VOICE_EFFECTS, expected_payload)

    def test_publish_sound_effects(self):
        node = voicemod.VoicemodNode()
        node._sounds = self.node._sounds
        node._push = MagicMock()
        node._publish_sound_effects()
        expected_payload = [
            {"id": "applause.mp3", "name": "applause"},
            {"id": "laughter.mp3", "name": "laughter"}
        ]
        node._push.assert_called_once_with(voicemod.TOPIC_DATA_SOUND_EFFECTS, expected_payload)

    @patch("src.voicemod.asyncio.run_coroutine_threadsafe")
    def test_handlers_dispatch(self, mock_run_coro):
        self.node._loop = MagicMock()
        self.node._set_voice = MagicMock()
        self.node._toggle_voice_changer = MagicMock()
        self.node._toggle_hear_my_voice = MagicMock()
        self.node._toggle_background = MagicMock()
        self.node._play_sound = MagicMock()
        self.node._stop_sounds = MagicMock()
        self.node._handle_set_voice_effect({"effectId": "Robot"})
        mock_run_coro.assert_called_once()
        mock_run_coro.reset_mock()
        self.node._handle_voice_changer_toggle({"enabled": True})
        mock_run_coro.assert_called_once()
        mock_run_coro.reset_mock()
        self.node._handle_microphone_toggle({"enabled": False})
        mock_run_coro.assert_called_once()
        mock_run_coro.reset_mock()
        self.node._handle_background_sound_toggle({"enabled": True})
        mock_run_coro.assert_called_once()
        mock_run_coro.reset_mock()
        self.node._handle_play_sound_effect({"effectId": "laughter"})
        mock_run_coro.assert_called_once()
        mock_run_coro.reset_mock()
        self.node._handle_play_sound_effect({"effectId": "stop"})
        mock_run_coro.assert_called_once()
        mock_run_coro.reset_mock()

    def test_teardown(self):
        self.node._zmq_ctx = MagicMock()
        self.node._zmq_sub = MagicMock()
        self.node._zmq_sub.closed = False
        self.node._zmq_push = MagicMock()
        self.node._zmq_push.closed = False
        self.node._loop = MagicMock()
        self.node._teardown()
        self.node._zmq_sub.close.assert_called_once_with(linger=0)
        self.node._zmq_push.close.assert_called_once_with(linger=0)
        self.node._zmq_ctx.destroy.assert_called_once_with(linger=0)

if __name__ == "__main__":
    unittest.main()
