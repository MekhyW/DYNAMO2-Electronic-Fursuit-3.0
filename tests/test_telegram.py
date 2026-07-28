import unittest
from unittest.mock import MagicMock, patch, mock_open
import zmq
from pathlib import Path
import sys
import os
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
import src.telegram as telegram


class TestTelegramNode(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {"fursuitbot_token": "mock-token-123", "fursuitbot_ownerID": "123456789"})
        self.env_patcher.start()
        self.bot_patcher = patch("src.telegram.telepot.Bot")
        self.mock_bot_class = self.bot_patcher.start()
        self.mock_bot = MagicMock()
        self.mock_bot_class.return_value = self.mock_bot
        self.node = telegram.TelegramNode()
        self.node._bot = self.mock_bot

    def tearDown(self):
        self.env_patcher.stop()
        self.bot_patcher.stop()

    @patch("src.telegram.zmq.Context")
    def test_setup_zmq(self, mock_context_class):
        mock_context = MagicMock()
        mock_sub = MagicMock()
        mock_push = MagicMock()
        mock_context.socket.side_effect = [mock_sub, mock_push]
        mock_context_class.return_value = mock_context
        self.node._setup_zmq()
        mock_context.socket.assert_any_call(zmq.SUB)
        mock_context.socket.assert_any_call(zmq.PUSH)
        mock_sub.connect.assert_called_with(telegram.ZMQ_SUB_ADDRESS)
        mock_push.connect.assert_called_with(telegram.ZMQ_PUSH_ADDRESS)
        for topic in telegram.SUBSCRIBED_TOPICS:
            mock_sub.setsockopt.assert_any_call(zmq.SUBSCRIBE, topic)

    def test_handle_send_text(self):
        payload = {"text": "Hello world", "chat_id": 98765, "parse_mode": "HTML"}
        self.node._handle_send_text(payload)
        self.mock_bot.sendMessage.assert_called_with(98765, "Hello world", parse_mode="HTML")
        payload_no_chat = {"text": "Hello owner"}
        self.node._handle_send_text(payload_no_chat)
        self.mock_bot.sendMessage.assert_called_with("123456789", "Hello owner", parse_mode="HTML")

    def test_handle_send_media_remote(self):
        payload = {"media_type": "photo", "media": "https://example.com/image.jpg", "chat_id": 98765, "caption": "My photo"}
        self.node._handle_send_media(payload)
        self.mock_bot.sendPhoto.assert_called_with(98765, "https://example.com/image.jpg", caption="My photo", parse_mode="HTML")

    @patch("src.telegram.os.path.exists")
    @patch("src.telegram.open", new_callable=mock_open, read_data=b"file content")
    def test_handle_send_media_local(self, mock_file, mock_exists):
        mock_exists.return_value = True
        payload = {"media_type": "video", "media": "/path/to/video.mp4", "chat_id": 98765, "caption": "My video"}
        self.node._handle_send_media(payload)
        mock_file.assert_called_with("/path/to/video.mp4", "rb")
        self.mock_bot.sendVideo.assert_called_once()

    @patch("src.telegram.telepot.glance")
    @patch("src.telegram.get_privacy_content")
    def test_handle_telegram_message_privacy(self, mock_get_privacy, mock_glance):
        mock_glance.return_value = ('text', 'private', 98765)
        mock_get_privacy.return_value = "Mock Privacy Statement Content"
        
        msg = {"text": "/privacy", "message_id": 111}
        self.node._handle_telegram_message(msg)
        self.mock_bot.sendMessage.assert_called_with(98765, "Mock Privacy Statement Content", parse_mode="HTML")

    @patch("src.telegram.telepot.glance")
    def test_handle_telegram_message_menu(self, mock_glance):
        mock_glance.return_value = ('text', 'private', 98765)
        msg = {"text": "hello", "message_id": 111}
        self.node._handle_telegram_message(msg)
        args, kwargs = self.mock_bot.sendMessage.call_args
        self.assertEqual(args[0], 98765)
        self.assertIn("Open the App", args[1])
        self.assertIn("inline_keyboard", kwargs["reply_markup"])

    @patch("src.telegram.telepot.glance")
    @patch("src.telegram.os.path.abspath")
    def test_handle_telegram_message_audio(self, mock_abspath, mock_glance):
        mock_glance.return_value = ('voice', 'private', 98765)
        mock_abspath.return_value = "/absolute/path/to/111.ogg"
        msg = {"voice": {"file_id": "voice-file-id-abc"}, "message_id": 111, "from": {"first_name": "Felipe"}}
        self.node._push = MagicMock()
        self.node._handle_telegram_message(msg)
        self.mock_bot.download_file.assert_called_with("voice-file-id-abc", "111.ogg")
        self.mock_bot.sendMessage.assert_any_call(98765, '<b>Done!</b>\n<i>>>Playing now</i>', parse_mode='HTML')
        self.node._push.assert_called_with(
            telegram.TOPIC_PLAY_SOUND_EFFECT,
            {
                "effectId": "/absolute/path/to/111.ogg",
                "user": {"id": 98765, "first_name": "Felipe"}
            }
        )


if __name__ == "__main__":
    unittest.main()
