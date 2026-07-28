from __future__ import annotations
import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Callable
import urllib3
import zmq
import telepot
from telepot.loop import MessageLoop
from dotenv import load_dotenv
load_dotenv("../.env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] telegram: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("telegram")

try:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception as e:
    log.warning("Could not disable SSL context/warnings: %s", e)

ZMQ_SUB_ADDRESS: str = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"
STATUS_PUBLISH_INTERVAL: float = 5.0

TOPIC_STATUS = b"dynamo/status/telegram"
TOPIC_SEND_TEXT = b"dynamo/commands/telegram/send-text"
TOPIC_SEND_MEDIA = b"dynamo/commands/telegram/send-media"
TOPIC_PLAY_SOUND_EFFECT = b"dynamo/commands/play-sound-effect"
SUBSCRIBED_TOPICS: list[bytes] = [TOPIC_SEND_TEXT, TOPIC_SEND_MEDIA]

APP_PATH = 'https://t.me/mekhybot?startapp'
REFSHEET_PATH = 'https://i.postimg.cc/Y25LSW-z2/refsheet.png'
STICKER_PACK = 'https://t.me/addstickers/MekhyW'
MY_CHAT_PATH = 'https://t.me/MekhyW'


def get_privacy_content() -> str:
    return """
This Telegram Bot is an integral part of the Dynamo project, designed to assist in control-related tasks. 
I (Felipe Catapano Emrich Melo, known as Mekhy) am committed to protecting your privacy and ensuring that your data is secure.

<b>No data collection</b>
The bot does NOT store any data about users or chats in a non-volatile manner. The only data collected by the bot is the last message sent by the user, which is temporarily stored in memory as cache to facilitate the bot's logic and functionality.

<b>Non-Cloud Operation</b>
The Dynamo Telegram Bot does not run on cloud servers, it only operates on a local edge machine and is intended to be physically close to users. The cache is not stored permanently and is cleared when the system is shut down.

<b>Open Source</b>
The bot is part of the Dynamo project, an open-source initiative aimed at enhancing control systems. The project's codebase is publicly available for review and contribution at github.com/MekhyW/DYNAMO2-Electronic-Fursuit-3.0.

<b>Changes to This Privacy Statement</b>
I may update this privacy statement from time to time to reflect changes in my practices or for other operational, legal, or regulatory reasons. Any changes will be posted on my GitHub repository.

<b>Contact</b>
Message me on Telegram at @MekhyW for more information or to report any issues.

<i>By using the Dynamo Telegram Bot, you acknowledge that you have read and understood this privacy statement and agree to its terms.</i>
    """


class TelegramNode:
    """Telegram bot integration node using ZeroMQ for the DYNAMO system runtime."""
    def __init__(self) -> None:
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._handlers: dict[bytes, Callable[[dict[str, Any]], None]] = {
            TOPIC_SEND_TEXT: self._handle_send_text,
            TOPIC_SEND_MEDIA: self._handle_send_media,
        }
        self._bot_token = os.environ.get("fursuitbot_token")
        self._owner_id = os.environ.get("fursuitbot_ownerID")
        self._bot: telepot.Bot | None = None

    def start(self) -> None:
        self._running.set()
        if not self._bot_token:
            log.error("fursuitbot_token is not set in environment variables. Telegram bot cannot start.")
            return
        try:
            import telepot.api as _telepot_api
            _no_ssl_pool_params = dict(num_pools=3, maxsize=10, retries=3, timeout=30, cert_reqs='NONE', assert_hostname=False)
            _no_ssl_onetime_params = dict(num_pools=1, maxsize=1, retries=3, timeout=30, cert_reqs='NONE', assert_hostname=False)
            _telepot_api._pools['default'] = urllib3.PoolManager(**_no_ssl_pool_params)
            _telepot_api._onetime_pool_spec = (urllib3.PoolManager, _no_ssl_onetime_params)
        except Exception as e:
            log.warning("Failed to patch telepot SSL pools: %s", e)
        self._bot = telepot.Bot(self._bot_token)
        log.info("Telegram Bot instance initialized.")
        self._setup_zmq()
        threading.Thread(target=self._status_loop, daemon=True, name="telegram-status-loop").start()
        try:
            self._discard_previous_updates()
            MessageLoop(self._bot, {'chat': self._handle_telegram_message}).run_as_thread()
            log.info("Telegram bot MessageLoop started.")
            if self._owner_id:
                try:
                    self._bot.sendMessage(self._owner_id, ">>> TELEGRAM NODE READY! <<<")
                except Exception as e:
                    log.warning("Could not send startup message to owner %s: %s", self._owner_id, e)
        except Exception as e:
            log.error("Failed to start Telegram bot message loop: %s", e)
            return
        log.info("Telegram node started. SUB=%s PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping telegram node...")
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
        assert self._zmq_sub is not None
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
                payload = json.loads(payload_bytes)
            except json.JSONDecodeError as exc:
                log.warning("Could not decode JSON payload on topic %s: %s", topic_bytes, exc)
                continue
            handler = self._handlers.get(topic_bytes)
            if handler is None:
                log.debug("No handler for topic %s", topic_bytes)
                continue
            try:
                handler(payload)
            except Exception as exc:
                log.exception("Handler error for topic %s: %s", topic_bytes, exc)
        self._teardown()

    def _teardown(self) -> None:
        log.info("Tearing down ZMQ sockets...")
        if self._zmq_sub:
            self._zmq_sub.close(linger=0)
        if self._zmq_push:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx:
            self._zmq_ctx.term()

    def _status_loop(self) -> None:
        while self._running.is_set():
            status_payload = {"node": "telegram", "status": "online"}
            self._push(TOPIC_STATUS, status_payload)
            time.sleep(STATUS_PUBLISH_INTERVAL)

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        if not self._zmq_push:
            return
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _discard_previous_updates(self) -> None:
        if not self._bot:
            return
        try:
            updates = self._bot.getUpdates(timeout=-29)
            if updates:
                last_update_id = updates[-1]['update_id']
                self._bot.getUpdates(offset=last_update_id + 1)
                log.info("Discarded previous updates up to ID: %s", last_update_id)
        except Exception as e:
            log.warning("Could not discard previous updates: %s", e)

    def _handle_telegram_message(self, msg: dict[str, Any]) -> None:
        try:
            content_type, chat_type, chat_id = telepot.glance(msg)
            log.info("Telegram message: content_type=%s chat_type=%s chat_id=%s msg_id=%s", content_type, chat_type, chat_id, msg.get('message_id'))
            if content_type == 'text':
                text = msg.get('text', '').strip()
                if text.startswith('/privacy'):
                    privacy_text = get_privacy_content()
                    self._bot.sendMessage(chat_id, privacy_text, parse_mode='HTML')
                else:
                    menu_markup = {
                        'inline_keyboard': [
                            [{'text': 'OPEN APP', 'url': APP_PATH}],
                            [{'text': 'Check out my Refsheet!', 'url': REFSHEET_PATH}],
                            [{'text': 'Check out my Stickers!', 'url': STICKER_PACK}],
                            [{'text': 'Send me a private message', 'url': MY_CHAT_PATH}]
                        ]
                    }
                    info_text = (
                        "Open the App to control the fursuit by pressing the button below!\n"
                        "Don't know how to use me? Click on 'Tutorial' on the bottom left corner"
                    )
                    self._bot.sendMessage(chat_id, info_text, reply_markup=menu_markup)
            elif content_type in ['voice', 'audio']:
                self._handle_audio_message(chat_id, msg)
            else:
                self._bot.sendMessage(chat_id, 'I currently do not support this type of input :(')
        except Exception as e:
            log.exception("Error handling telegram message: %s", e)
            if self._owner_id:
                try:
                    self._bot.sendMessage(self._owner_id, f"Telegram bot error: {e}")
                except Exception:
                    pass

    def _handle_audio_message(self, chat_id: int, msg: dict[str, Any]) -> None:
        if not self._bot:
            return
        try:
            self._bot.sendMessage(chat_id, '<i>>>Downloading sound...</i>', parse_mode='HTML')
            file_name = f"{msg['message_id']}.ogg"
            if 'voice' in msg:
                self._bot.download_file(msg['voice']['file_id'], file_name)
            elif 'audio' in msg:
                self._bot.download_file(msg['audio']['file_id'], file_name)
            abs_path = os.path.abspath(file_name)
            self._bot.sendMessage(chat_id, '<b>Done!</b>\n<i>>>Playing now</i>', parse_mode='HTML')
            user_info = {"id": chat_id, "first_name": msg.get("from", {}).get("first_name", "Unknown")}
            play_payload = {"effectId": abs_path, "user": user_info}
            self._push(TOPIC_PLAY_SOUND_EFFECT, play_payload)
            log.info("Pushed voice/audio message playback request for %s", abs_path)
        except Exception as e:
            log.exception("Error in PlayAudioMessage handler: %s", e)
            self._bot.sendMessage(chat_id, 'An error occurred while downloading/playing audio, please try again')

    def _handle_send_text(self, payload: dict[str, Any]) -> None:
        if not self._bot:
            return
        text = payload.get("text")
        if not text:
            log.warning("send-text command received, but 'text' is missing")
            return
        chat_id = payload.get("chat_id") or self._owner_id
        if not chat_id:
            log.warning("send-text: no chat_id specified and no owner ID available")
            return
        parse_mode = payload.get("parse_mode", "HTML")
        try:
            self._bot.sendMessage(chat_id, text, parse_mode=parse_mode)
            log.info("Successfully sent text to %s", chat_id)
        except Exception as e:
            log.error("Failed to send text message to %s: %s", chat_id, e)

    def _handle_send_media(self, payload: dict[str, Any]) -> None:
        if not self._bot:
            return
        media_type = payload.get("media_type")
        media = payload.get("media")
        if not media_type or not media:
            log.warning("send-media: missing 'media_type' or 'media' fields")
            return
        chat_id = payload.get("chat_id") or self._owner_id
        if not chat_id:
            log.warning("send-media: no chat_id specified and no owner ID available")
            return
        caption = payload.get("caption")
        parse_mode = payload.get("parse_mode", "HTML")
        try:
            media_file = media
            is_local_file = False
            if isinstance(media, str) and os.path.exists(media):
                media_file = open(media, "rb")
                is_local_file = True
            try:
                if media_type == "photo":
                    self._bot.sendPhoto(chat_id, media_file, caption=caption, parse_mode=parse_mode)
                elif media_type == "video":
                    self._bot.sendVideo(chat_id, media_file, caption=caption, parse_mode=parse_mode)
                elif media_type == "voice":
                    self._bot.sendVoice(chat_id, media_file, caption=caption, parse_mode=parse_mode)
                elif media_type == "audio":
                    self._bot.sendAudio(chat_id, media_file, caption=caption, parse_mode=parse_mode)
                elif media_type == "document":
                    self._bot.sendDocument(chat_id, media_file, caption=caption, parse_mode=parse_mode)
                else:
                    log.warning("Unsupported media type: %s", media_type)
                    return
                log.info("Successfully sent %s media to %s", media_type, chat_id)
            finally:
                if is_local_file:
                    media_file.close()
        except Exception as e:
            log.error("Failed to send media (%s) to %s: %s", media_type, chat_id, e)


def main() -> None:
    node = TelegramNode()
    def signal_handler(sig: Any, frame: Any) -> None:
        log.info("Signal received, stopping...")
        node.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        node.start()
    except KeyboardInterrupt:
        log.info("Keyboard interrupt, stopping...")
        node.stop()


if __name__ == "__main__":
    main()
