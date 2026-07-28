from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import signal
import string
import threading
import time
from typing import Any, Callable
import websockets
import zmq
from dotenv import load_dotenv
load_dotenv("../.env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] voicemod: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("voicemod")

ZMQ_SUB_ADDRESS:  str = "tcp://localhost:5555"   # connect to mqttbridge PUB bus
ZMQ_PUSH_ADDRESS: str = "tcp://localhost:5556"   # connect to mqttbridge PULL socket
STATUS_PUBLISH_INTERVAL: float = 5.0             # seconds between status pushes

TOPIC_STATUS = b"dynamo/status/voicemod"
TOPIC_DATA_VOICE_EFFECTS = b"dynamo/data/voice_effects"
TOPIC_DATA_SOUND_EFFECTS = b"dynamo/data/sound_effects"
TOPIC_SET_VOICE_EFFECT = b"dynamo/commands/set-voice-effect"
TOPIC_VOICE_CHANGER_TOGGLE = b"dynamo/commands/voice-changer-toggle"
TOPIC_MICROPHONE_TOGGLE = b"dynamo/commands/microphone-toggle"
TOPIC_BACKGROUND_SOUND_TOGGLE = b"dynamo/commands/background-sound-toggle"
TOPIC_PLAY_SOUND_EFFECT = b"dynamo/commands/play-sound-effect"
SUBSCRIBED_TOPICS: list[bytes] = [TOPIC_SET_VOICE_EFFECT, TOPIC_VOICE_CHANGER_TOGGLE, TOPIC_MICROPHONE_TOGGLE, TOPIC_BACKGROUND_SOUND_TOGGLE, TOPIC_PLAY_SOUND_EFFECT]

voicemod_key = os.environ.get("voicemod_key") or os.environ.get("VOICEMOD_KEY", "")

class VoicemodNode:
    """Voicemod node interfacing with Voicemod Desktop Client WebSocket."""
    def __init__(self) -> None:
        self._running = threading.Event()
        self._zmq_ctx: zmq.Context | None = None
        self._zmq_sub: zmq.Socket | None = None
        self._zmq_push: zmq.Socket | None = None
        self._handlers: dict[bytes, Callable[[dict[str, Any]], None]] = {
            TOPIC_SET_VOICE_EFFECT: self._handle_set_voice_effect,
            TOPIC_VOICE_CHANGER_TOGGLE: self._handle_voice_changer_toggle,
            TOPIC_MICROPHONE_TOGGLE: self._handle_microphone_toggle,
            TOPIC_BACKGROUND_SOUND_TOGGLE: self._handle_background_sound_toggle,
            TOPIC_PLAY_SOUND_EFFECT: self._handle_play_sound_effect,
        }
        self._ws_url = "ws://localhost:59129/v1"
        self._websocket: websockets.WebSocketClientProtocol | None = None
        self._ws_lock = asyncio.Lock()
        self._loop = asyncio.new_event_loop()
        self._async_thread: threading.Thread | None = None
        self._voices: list[dict[str, str]] = []
        self._sounds: list[dict[str, str]] = []
        self._valid_response_actions = {
            'getHearMyselfStatus': ['getHearMyselfStatus'],
            'getVoiceChangerStatus': ['getVoiceChangerStatus'],
            'getBackgroundEffectStatus': ['getBackgroundEffectStatus'],
            'toggleHearMyVoice': ['hearMySelfEnabledEvent', 'hearMySelfDisabledEvent'],
            'toggleVoiceChanger': ['voiceChangerEnabledEvent', 'voiceChangerDisabledEvent'],
            'toggleBackground': ['backgroundEffectsEnabledEvent', 'backgroundEffectsDisabledEvent'],
            'getVoices': ['getVoices'],
            'loadVoice': ['loadVoice', 'voiceLoadedEvent'],
            'getMemes': ['getMemes'],
            'getBitmap': ['getBitmap']
        }
        self._no_response_commands = ['playMeme', 'stopAllMemeSounds']

    def start(self) -> None:
        self._running.set()
        self._setup_zmq()
        self._async_thread = threading.Thread(target=self._run_async_loop, daemon=True, name="voicemod-async")
        self._async_thread.start()
        threading.Thread(target=self._status_loop, daemon=True, name="status-loop").start()
        log.info("Voicemod node started. SUB=%s PUSH=%s", ZMQ_SUB_ADDRESS, ZMQ_PUSH_ADDRESS)
        self._event_loop()

    def stop(self) -> None:
        log.info("Stopping voicemod node...")
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

    def _run_async_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._websocket_manager())

    async def _websocket_manager(self) -> None:
        while self._running.is_set():
            try:
                log.info("Connecting to Voicemod at %s...", self._ws_url)
                async with websockets.connect(self._ws_url, ping_interval=5, max_size=2**30) as ws:
                    self._websocket = ws
                    log.info("Voicemod connected! Registering client...")
                    reg_response = await self._send_message("registerClient", {"clientKey": voicemod_key})
                    log.info("Client registration response: %s", reg_response)
                    await self._fetch_voices_and_sounds()
                    while self._running.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            log.debug("Received background websocket message: %s", msg)
                        except asyncio.TimeoutError:
                            continue
            except (ConnectionRefusedError, OSError) as e:
                log.warning("Voicemod not running or connection failed: %s. Retrying in 5 seconds...", e)
                self._websocket = None
                await asyncio.sleep(5)
            except Exception as e:
                log.exception("Exception in Voicemod websocket manager: %s", e)
                self._websocket = None
                await asyncio.sleep(5)

    async def _send_message(self, command: str, payload: dict[str, Any]) -> Any:
        if self._websocket is None:
            log.warning("Cannot send message: Voicemod websocket is not connected.")
            return None
        message = {"action": command, "id": ''.join(random.choice(string.ascii_lowercase) for _ in range(36)), "payload": payload}
        async with self._ws_lock:
            try:
                await self._websocket.send(json.dumps(message))
                if command in self._no_response_commands:
                    return True
                start_time = time.time()
                while time.time() - start_time < 5.0:
                    try:
                        response_str = await asyncio.wait_for(self._websocket.recv(), timeout=2.0)
                        response = json.loads(response_str)
                        if command in self._valid_response_actions:
                            action = response.get('action')
                            if action not in self._valid_response_actions[command]:
                                continue
                        return response
                    except asyncio.TimeoutError:
                        break
            except Exception as e:
                log.error("Error communicating with Voicemod WebSocket: %s", e)
        return None

    async def _fetch_voices_and_sounds(self) -> None:
        self._voices = []
        response = await self._send_message('getVoices', {})
        if response and 'payload' in response and response['payload']:
            voices_list = response['payload'].get('voices', [])
            for voice in voices_list:
                self._voices.append({"name": voice.get("friendlyName", ""), "id": voice.get("id", "")})
            self._voices = sorted(self._voices, key=lambda k: k['name'])
            log.info("Loaded %d voice effects", len(self._voices))
            self._publish_voice_effects()
        self._sounds = []
        response = await self._send_message('getMemes', {})
        if response and 'actionObject' in response and response['actionObject']:
            memes = response['actionObject'].get('listOfMemes', [])
            for sound in memes:
                if sound.get("Type") == "PlayStop" and sound.get('Name', '').islower():
                    self._sounds.append({"name": sound.get("Name", ""), "id": sound.get("FileName", "")})
            self._sounds = sorted(self._sounds, key=lambda k: k['name'])
            log.info("Loaded %d soundboard memes", len(self._sounds))
            self._publish_sound_effects()

    def _publish_voice_effects(self) -> None:
        payload = [{"id": idx, "name": voice["name"], "type": "voicemod"} for idx, voice in enumerate(self._voices)]
        self._push(TOPIC_DATA_VOICE_EFFECTS, payload)

    def _publish_sound_effects(self) -> None:
        payload = [{"id": idx, "name": sound["name"], "filename": sound["id"]} for idx, sound in enumerate(self._sounds)]
        self._push(TOPIC_DATA_SOUND_EFFECTS, payload)

    def _resolve_voice_id(self, effect_id: Any) -> str | None:
        if effect_id is None:
            return None
        if isinstance(effect_id, int):
            if 0 <= effect_id < len(self._voices):
                return self._voices[effect_id]["id"]
            return None
        if isinstance(effect_id, str):
            for voice in self._voices:
                if voice["id"] == effect_id or voice["name"].lower() == effect_id.lower():
                    return voice["id"]
            if effect_id.isdigit():
                idx = int(effect_id)
                if 0 <= idx < len(self._voices):
                    return self._voices[idx]["id"]
            return effect_id  # fallback to raw string UUID
        return None

    def _resolve_sound_id(self, effect_id: Any) -> str | None:
        if effect_id is None:
            return None
        if isinstance(effect_id, int):
            if 0 <= effect_id < len(self._sounds):
                return self._sounds[effect_id]["id"]
            return None
        if isinstance(effect_id, str):
            for sound in self._sounds:
                if sound["id"] == effect_id or sound["name"].lower() == effect_id.lower():
                    return sound["id"]
            if effect_id.isdigit():
                idx = int(effect_id)
                if 0 <= idx < len(self._sounds):
                    return self._sounds[idx]["id"]
            return effect_id
        return None

    # ZMQ Handlers
    def _handle_set_voice_effect(self, payload: dict[str, Any]) -> None:
        effect_id = payload.get("effectId")
        resolved = self._resolve_voice_id(effect_id)
        if resolved:
            log.info("Setting voice effect: %s (resolved: %s)", effect_id, resolved)
            asyncio.run_coroutine_threadsafe(self._set_voice(resolved), self._loop)
        else:
            log.warning("Could not resolve voice effect ID: %s", effect_id)

    def _handle_voice_changer_toggle(self, payload: dict[str, Any]) -> None:
        enabled = payload.get("enabled", True)
        log.info("Setting voice changer: %s", enabled)
        asyncio.run_coroutine_threadsafe(self._toggle_voice_changer(enabled), self._loop)

    def _handle_microphone_toggle(self, payload: dict[str, Any]) -> None:
        enabled = payload.get("enabled", True)
        log.info("Setting hear my voice (microphone toggle): %s", enabled)
        asyncio.run_coroutine_threadsafe(self._toggle_hear_my_voice(enabled), self._loop)

    def _handle_background_sound_toggle(self, payload: dict[str, Any]) -> None:
        enabled = payload.get("enabled", False)
        log.info("Setting background sound: %s", enabled)
        asyncio.run_coroutine_threadsafe(self._toggle_background(enabled), self._loop)

    def _handle_play_sound_effect(self, payload: dict[str, Any]) -> None:
        effect_id = payload.get("effectId")
        if effect_id == "stop":
            log.info("Stopping all sound effects")
            asyncio.run_coroutine_threadsafe(self._stop_sounds(), self._loop)
            return
        resolved = self._resolve_sound_id(effect_id)
        if resolved:
            log.info("Playing sound effect: %s (resolved: %s)", effect_id, resolved)
            asyncio.run_coroutine_threadsafe(self._play_sound(resolved), self._loop)
        else:
            log.warning("Could not resolve sound effect ID: %s", effect_id)

    # Async operations executed in background loop
    async def _getStatus(self, command: str) -> bool | None:
        status = await self._send_message(command, {})
        if status and 'actionObject' in status and 'value' in status['actionObject']:
            return status['actionObject']['value']
        return None

    async def _toggle_hear_my_voice(self, desired_status: bool) -> None:
        status = await self._getStatus('getHearMyselfStatus')
        if status == desired_status:
            return
        await self._send_message('toggleHearMyVoice', {})

    async def _toggle_voice_changer(self, desired_status: bool) -> None:
        status = await self._getStatus('getVoiceChangerStatus')
        if status == desired_status:
            return
        await self._send_message('toggleVoiceChanger', {})

    async def _toggle_background(self, desired_status: bool) -> None:
        status = await self._getStatus('getBackgroundEffectStatus')
        if status == desired_status:
            return
        await self._send_message('toggleBackground', {})

    async def _set_voice(self, voice_id: str) -> None:
        await self._send_message('loadVoice', {"voiceId": voice_id})

    async def _play_sound(self, meme_id: str) -> None:
        await self._send_message('playMeme', {"FileName": meme_id, "IsKeyDown": True})

    async def _stop_sounds(self) -> None:
        await self._send_message('stopAllMemeSounds', {})

    # ZMQ Communications & Loop
    def _push(self, topic: bytes, payload: Any) -> None:
        if self._zmq_push is None:
            return
        try:
            self._zmq_push.send_multipart([topic, json.dumps(payload).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic)
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic, exc)

    def _push_status(self, online: bool) -> None:
        self._push(TOPIC_STATUS, {"status": "online" if online else "offline", "node": "voicemod"})

    def _status_loop(self) -> None:
        while self._running.is_set():
            self._push_status(online=True)
            time.sleep(STATUS_PUBLISH_INTERVAL)

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
                continue
            try:
                handler(payload)
            except Exception as exc:
                log.exception("Handler error for topic %s: %s", topic_bytes, exc)
        
        self._teardown()

    def _teardown(self) -> None:
        log.info("Tearing down connections...")
        self._push_status(online=False)
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._zmq_sub is not None and not self._zmq_sub.closed:
            self._zmq_sub.close(linger=0)
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=0)
        if self._zmq_ctx is not None:
            self._zmq_ctx.destroy(linger=0)
        log.info("Voicemod node stopped.")

def main() -> None:
    node = VoicemodNode()
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d -- shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()

if __name__ == "__main__":
    main()
