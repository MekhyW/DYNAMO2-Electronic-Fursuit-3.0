import json
import sys
import threading
import unittest
import zmq
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.unity import (
    EXPRESSION_INDEX,
    NUM_EMOTIONS,
    SUBSCRIBED_TOPICS,
    TOPIC_EYES_BRIGHTNESS,
    TOPIC_EYES_VIDEO,
    TOPIC_EYE_STATE,
    TOPIC_EYE_TRACKING,
    TOPIC_FACE_EXPRESSION_TRACKING,
    TOPIC_SET_EXPRESSION,
    TOPIC_STATUS,
    UNITY_HOST,
    UNITY_PORT,
    ZMQ_PUSH_ADDRESS,
    ZMQ_SUB_ADDRESS,
    UnityNode,
    UnityState,
)


def _make_node() -> UnityNode:
    """Create a UnityNode without touching any real sockets."""
    node = UnityNode.__new__(UnityNode)
    node._state = UnityState()
    node._running = threading.Event()
    node._zmq_ctx = None
    node._zmq_sub = None
    node._zmq_push = None
    node._sock = None
    node._sock_lock = threading.Lock()
    node._handlers = {
        TOPIC_FACE_EXPRESSION_TRACKING: node._handle_face_expression_tracking,
        TOPIC_EYE_TRACKING:              node._handle_eye_tracking,
        TOPIC_SET_EXPRESSION:            node._handle_set_expression,
        TOPIC_EYES_BRIGHTNESS:           node._handle_eyes_brightness,
        TOPIC_EYE_STATE:                 node._handle_eye_state,
        TOPIC_EYES_VIDEO:                node._handle_eyes_video,
    }
    return node


class TestUnityStateBuildMessage(unittest.TestCase):
    def test_default_state_produces_correct_format(self):
        state = UnityState()
        msg = state.build_message()
        parts = msg.split()
        # disp_x disp_y cl_left cl_right + NUM_EMOTIONS scores + manual_id + silly + brightness
        expected_len = 4 + NUM_EMOTIONS + 3
        self.assertEqual(len(parts), expected_len)

    def test_default_values(self):
        state = UnityState()
        msg = state.build_message()
        parts = msg.split()
        self.assertEqual(parts[0], "0.0")          # displacement_x
        self.assertEqual(parts[1], "0.0")          # displacement_y
        self.assertEqual(parts[2], "0.0")          # closeness_left
        self.assertEqual(parts[3], "0.0")          # closeness_right
        self.assertEqual(parts[-3], "-1")          # manual_id (tracking on → always -1)
        self.assertEqual(parts[-2], "0")           # silly_mode off
        self.assertEqual(parts[-1], "100")         # screen_brightness default

    def test_silly_mode_flag(self):
        state = UnityState()
        state.silly_mode = True
        msg = state.build_message()
        self.assertEqual(msg.split()[-2], "1")

    def test_screen_brightness_in_message(self):
        state = UnityState()
        state.screen_brightness = 42
        msg = state.build_message()
        self.assertEqual(msg.split()[-1], "42")

    def test_manual_id_sent_when_tracking_disabled(self):
        state = UnityState()
        state.face_expression_tracking = False
        state.manual_expression_id = 3
        msg = state.build_message()
        # manual_id is the third-from-last token
        self.assertEqual(msg.split()[-3], "3")

    def test_manual_id_minus_one_when_tracking_enabled(self):
        state = UnityState()
        state.face_expression_tracking = True
        state.manual_expression_id = 3
        msg = state.build_message()
        self.assertEqual(msg.split()[-3], "-1")

    def test_manual_id_minus_one_when_id_negative(self):
        state = UnityState()
        state.face_expression_tracking = False
        state.manual_expression_id = -1
        msg = state.build_message()
        self.assertEqual(msg.split()[-3], "-1")

    def test_scores_below_threshold_are_zeroed(self):
        state = UnityState()
        state.emotion_scores = [0.005] * NUM_EMOTIONS  # all below 0.01 threshold
        msg = state.build_message()
        score_tokens = msg.split()[4 : 4 + NUM_EMOTIONS]
        self.assertTrue(all(t == "0" for t in score_tokens))

    def test_scores_above_threshold_are_kept(self):
        state = UnityState()
        scores = [0.0] * NUM_EMOTIONS
        scores[2] = 0.75
        state.emotion_scores = scores
        msg = state.build_message()
        score_tokens = msg.split()[4 : 4 + NUM_EMOTIONS]
        self.assertEqual(score_tokens[2], "0.75")

    def test_comma_replaced_with_dot(self):
        # Simulate a locale that would format floats with commas
        state = UnityState()
        state.displacement_eye_x = 0.5
        msg = state.build_message()
        self.assertNotIn(",", msg)

    def test_displacement_values_in_message(self):
        state = UnityState()
        state.displacement_eye_x = 0.3
        state.displacement_eye_y = -0.7
        parts = state.build_message().split()
        self.assertEqual(parts[0], "0.3")
        self.assertEqual(parts[1], "-0.7")

    def test_closeness_values_in_message(self):
        state = UnityState()
        state.closeness_left = 0.4
        state.closeness_right = 0.9
        parts = state.build_message().split()
        self.assertEqual(parts[2], "0.4")
        self.assertEqual(parts[3], "0.9")


class TestZMQSetup(unittest.TestCase):
    @patch("src.unity.zmq.Context")
    def test_setup_creates_and_connects_sockets(self, mock_context_class):
        mock_ctx = MagicMock()
        mock_sub = MagicMock()
        mock_push = MagicMock()
        mock_ctx.socket.side_effect = [mock_sub, mock_push]
        mock_context_class.return_value = mock_ctx
        node = _make_node()
        node._setup_zmq()
        mock_ctx.socket.assert_any_call(zmq.SUB)
        mock_ctx.socket.assert_any_call(zmq.PUSH)
        mock_sub.connect.assert_called_with(ZMQ_SUB_ADDRESS)
        mock_push.connect.assert_called_with(ZMQ_PUSH_ADDRESS)

    @patch("src.unity.zmq.Context")
    def test_setup_subscribes_to_all_topics(self, mock_context_class):
        mock_ctx = MagicMock()
        mock_sub = MagicMock()
        mock_push = MagicMock()
        mock_ctx.socket.side_effect = [mock_sub, mock_push]
        mock_context_class.return_value = mock_ctx

        node = _make_node()
        node._setup_zmq()

        for topic in SUBSCRIBED_TOPICS:
            mock_sub.setsockopt.assert_any_call(zmq.SUBSCRIBE, topic)


class TestUnityConnection(unittest.TestCase):
    @patch("src.unity.socket.socket")
    def test_connect_success(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        node = _make_node()
        result = node._connect_unity()
        self.assertTrue(result)
        mock_sock.connect.assert_called_once_with((UNITY_HOST, UNITY_PORT))
        self.assertIs(node._sock, mock_sock)

    @patch("src.unity.socket.socket")
    def test_connect_refused_returns_false(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError
        mock_socket_class.return_value = mock_sock
        node = _make_node()
        result = node._connect_unity()
        self.assertFalse(result)
        self.assertIsNone(node._sock)

    @patch("src.unity.socket.socket")
    def test_connect_closes_existing_socket_first(self, mock_socket_class):
        old_sock = MagicMock()
        new_sock = MagicMock()
        mock_socket_class.return_value = new_sock
        node = _make_node()
        node._sock = old_sock
        node._connect_unity()
        old_sock.close.assert_called_once()
        self.assertIs(node._sock, new_sock)

    @patch("src.unity.socket.socket")
    def test_connect_os_error_returns_false(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("network error")
        mock_socket_class.return_value = mock_sock
        node = _make_node()
        result = node._connect_unity()
        self.assertFalse(result)
        self.assertIsNone(node._sock)


class TestSendState(unittest.TestCase):
    def test_sends_message_and_reads_response(self):
        node = _make_node()
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"OK"
        node._sock = mock_sock
        node._send_state()
        mock_sock.sendall.assert_called_once()
        sent = mock_sock.sendall.call_args[0][0].decode()
        self.assertIsInstance(sent, str)
        self.assertGreater(len(sent.split()), 0)

    def test_no_send_when_socket_is_none(self):
        node = _make_node()
        node._sock = None
        # Should not raise
        node._send_state()

    def test_os_error_clears_socket_and_reconnects(self):
        node = _make_node()
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"OK"
        mock_sock.sendall.side_effect = OSError("broken pipe")
        node._sock = mock_sock
        node._connect_unity = MagicMock(return_value=False)
        node._send_state()
        node._connect_unity.assert_called_once()

    def test_invalid_message_format_response_logs_error(self):
        node = _make_node()
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"Invalid message format!"
        node._sock = mock_sock

        with self.assertLogs("unity", level="ERROR"):
            node._send_state()


class TestSendVideoCommand(unittest.TestCase):
    def test_sends_message_and_logs_response(self):
        node = _make_node()
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"OK"
        node._sock = mock_sock
        with self.assertLogs("unity", level="INFO"):
            node._send_video_command("VIDEO PLAY http://example.com/vid.mp4")
        mock_sock.sendall.assert_called_once_with(b"VIDEO PLAY http://example.com/vid.mp4")

    def test_drops_command_when_not_connected(self):
        node = _make_node()
        node._sock = None
        with self.assertLogs("unity", level="WARNING"):
            node._send_video_command("VIDEO STOP")

    def test_os_error_clears_socket(self):
        node = _make_node()
        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = OSError("broken pipe")
        node._sock = mock_sock
        node._send_video_command("VIDEO STOP")
        self.assertIsNone(node._sock)


class TestHandleFaceExpressionTracking(unittest.TestCase):
    def test_enables_tracking(self):
        node = _make_node()
        node._state.face_expression_tracking = False
        node._handle_face_expression_tracking({"enabled": True})
        self.assertTrue(node._state.face_expression_tracking)

    def test_disables_tracking(self):
        node = _make_node()
        node._state.face_expression_tracking = True
        node._handle_face_expression_tracking({"enabled": False})
        self.assertFalse(node._state.face_expression_tracking)

    def test_missing_enabled_logs_warning(self):
        node = _make_node()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_face_expression_tracking({})

    def test_invalid_type_logs_warning(self):
        node = _make_node()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_face_expression_tracking({"enabled": "yes"})


class TestHandleEyeTracking(unittest.TestCase):
    def test_enables_eye_tracking(self):
        node = _make_node()
        node._state.eye_tracking = False
        node._handle_eye_tracking({"enabled": True})
        self.assertTrue(node._state.eye_tracking)

    def test_disables_eye_tracking(self):
        node = _make_node()
        node._state.eye_tracking = True
        node._handle_eye_tracking({"enabled": False})
        self.assertFalse(node._state.eye_tracking)

    def test_missing_enabled_logs_warning(self):
        node = _make_node()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_eye_tracking({})


class TestHandleSetExpression(unittest.TestCase):
    def test_known_expression_sets_scores(self):
        node = _make_node()
        for name, idx in EXPRESSION_INDEX.items():
            node._handle_set_expression({"expression": name})
            self.assertEqual(node._state.emotion_scores[idx], 1.0)
            other_scores = [s for i, s in enumerate(node._state.emotion_scores) if i != idx]
            self.assertTrue(all(s == 0.0 for s in other_scores))

    def test_known_expression_sets_manual_id(self):
        node = _make_node()
        node._handle_set_expression({"expression": "happy"})
        self.assertEqual(node._state.manual_expression_id, EXPRESSION_INDEX["happy"])

    def test_expression_is_case_insensitive(self):
        node = _make_node()
        node._handle_set_expression({"expression": "HAPPY"})
        self.assertEqual(node._state.manual_expression_id, EXPRESSION_INDEX["happy"])

    def test_unknown_expression_logs_warning(self):
        node = _make_node()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_set_expression({"expression": "confused"})

    def test_missing_expression_logs_warning(self):
        node = _make_node()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_set_expression({})

    def test_scores_vector_length_matches_num_emotions(self):
        node = _make_node()
        node._handle_set_expression({"expression": "sad"})
        self.assertEqual(len(node._state.emotion_scores), NUM_EMOTIONS)


class TestHandleEyesBrightness(unittest.TestCase):
    def test_sets_brightness(self):
        node = _make_node()
        node._handle_eyes_brightness({"brightness": 75})
        self.assertEqual(node._state.screen_brightness, 75)

    def test_clamps_above_100(self):
        node = _make_node()
        node._handle_eyes_brightness({"brightness": 150})
        self.assertEqual(node._state.screen_brightness, 100)

    def test_clamps_below_0(self):
        node = _make_node()
        node._handle_eyes_brightness({"brightness": -10})
        self.assertEqual(node._state.screen_brightness, 0)

    def test_accepts_float_brightness(self):
        node = _make_node()
        node._handle_eyes_brightness({"brightness": 66.7})
        self.assertEqual(node._state.screen_brightness, 66)

    def test_missing_brightness_logs_warning(self):
        node = _make_node()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_eyes_brightness({})

    def test_non_numeric_brightness_logs_warning(self):
        node = _make_node()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_eyes_brightness({"brightness": "full"})


class TestHandleEyeState(unittest.TestCase):
    def test_updates_displacement(self):
        node = _make_node()
        node._handle_eye_state({"displacement_x": 0.3, "displacement_y": -0.5})
        self.assertAlmostEqual(node._state.displacement_eye_x, 0.3)
        self.assertAlmostEqual(node._state.displacement_eye_y, -0.5)

    def test_updates_closeness(self):
        node = _make_node()
        node._handle_eye_state({"closeness_left": 0.6, "closeness_right": 0.8})
        self.assertAlmostEqual(node._state.closeness_left, 0.6)
        self.assertAlmostEqual(node._state.closeness_right, 0.8)

    def test_updates_emotion_scores(self):
        node = _make_node()
        scores = [float(i) / NUM_EMOTIONS for i in range(NUM_EMOTIONS)]
        node._handle_eye_state({"emotion_scores": scores})
        self.assertEqual(node._state.emotion_scores, scores)

    def test_ignores_wrong_length_scores(self):
        node = _make_node()
        original = list(node._state.emotion_scores)
        node._handle_eye_state({"emotion_scores": [0.5, 0.5]})  # wrong length
        self.assertEqual(node._state.emotion_scores, original)

    def test_updates_silly_mode(self):
        node = _make_node()
        node._handle_eye_state({"silly_mode": True})
        self.assertTrue(node._state.silly_mode)
        node._handle_eye_state({"silly_mode": False})
        self.assertFalse(node._state.silly_mode)

    def test_partial_update_leaves_other_fields_unchanged(self):
        node = _make_node()
        node._state.closeness_left = 0.9
        node._handle_eye_state({"displacement_x": 0.1})
        self.assertAlmostEqual(node._state.closeness_left, 0.9)

    def test_empty_payload_is_a_noop(self):
        node = _make_node()
        before = node._state.build_message()
        node._handle_eye_state({})
        after = node._state.build_message()
        self.assertEqual(before, after)


class TestHandleEyesVideo(unittest.TestCase):
    def test_play_sends_play_command(self):
        node = _make_node()
        node._send_video_command = MagicMock()
        node._handle_eyes_video({"url": "http://example.com/video.mp4"})
        node._send_video_command.assert_called_once_with("VIDEO PLAY http://example.com/video.mp4")

    def test_stop_sends_stop_command(self):
        node = _make_node()
        node._send_video_command = MagicMock()
        node._handle_eyes_video({"url": "stop"})
        node._send_video_command.assert_called_once_with("VIDEO STOP")

    def test_stop_is_case_insensitive(self):
        node = _make_node()
        node._send_video_command = MagicMock()
        node._handle_eyes_video({"url": "STOP"})
        node._send_video_command.assert_called_once_with("VIDEO STOP")

    def test_missing_url_logs_warning(self):
        node = _make_node()
        node._send_video_command = MagicMock()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_eyes_video({})
        node._send_video_command.assert_not_called()

    def test_empty_url_logs_warning(self):
        node = _make_node()
        node._send_video_command = MagicMock()
        with self.assertLogs("unity", level="WARNING"):
            node._handle_eyes_video({"url": "  "})
        node._send_video_command.assert_not_called()


class TestEventLoop(unittest.TestCase):
    def test_dispatches_message_to_correct_handler(self):
        node = _make_node()
        node._running.set()
        mock_sub = MagicMock()
        node._zmq_sub = mock_sub
        node._zmq_push = MagicMock()
        node._handle_eyes_brightness = MagicMock()
        node._handlers[TOPIC_EYES_BRIGHTNESS] = node._handle_eyes_brightness
        def side_effect():
            node._running.clear()
            return [TOPIC_EYES_BRIGHTNESS, b'{"brightness": 50}']
        mock_sub.recv_multipart.side_effect = side_effect
        node._event_loop()
        node._handle_eyes_brightness.assert_called_once_with({"brightness": 50})

    def test_skips_malformed_frames(self):
        node = _make_node()
        node._running.set()
        mock_sub = MagicMock()
        node._zmq_sub = mock_sub
        node._zmq_push = MagicMock()
        call_count = 0
        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [b"only-one-frame"]   # malformed
            node._running.clear()
            raise zmq.Again()
        mock_sub.recv_multipart.side_effect = side_effect
        node._event_loop()   # should not raise

    def test_skips_invalid_json(self):
        node = _make_node()
        node._running.set()
        mock_sub = MagicMock()
        node._zmq_sub = mock_sub
        node._zmq_push = MagicMock()
        call_count = 0
        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [TOPIC_EYES_BRIGHTNESS, b"not-json"]
            node._running.clear()
            raise zmq.Again()
        mock_sub.recv_multipart.side_effect = side_effect
        node._event_loop()   # should not raise

    def test_again_continues_loop(self):
        node = _make_node()
        node._running.set()
        mock_sub = MagicMock()
        node._zmq_sub = mock_sub
        node._zmq_push = MagicMock()
        call_count = 0
        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise zmq.Again()
            node._running.clear()
            raise zmq.Again()
        mock_sub.recv_multipart.side_effect = side_effect
        node._event_loop()
        self.assertGreaterEqual(call_count, 3)


class TestTeardown(unittest.TestCase):
    def test_closes_sockets_and_context(self):
        node = _make_node()
        node._zmq_ctx = MagicMock()
        node._zmq_sub = MagicMock()
        node._zmq_sub.closed = False
        node._zmq_push = MagicMock()
        node._zmq_push.closed = False
        node._teardown()
        node._zmq_sub.close.assert_called_once_with(linger=0)
        node._zmq_push.close.assert_called_once_with(linger=0)
        node._zmq_ctx.destroy.assert_called_once_with(linger=0)

    def test_skips_already_closed_sockets(self):
        node = _make_node()
        node._zmq_ctx = MagicMock()
        node._zmq_sub = MagicMock()
        node._zmq_sub.closed = True
        node._zmq_push = MagicMock()
        node._zmq_push.closed = True
        node._teardown()
        node._zmq_sub.close.assert_not_called()
        node._zmq_push.close.assert_not_called()

    def test_closes_unity_socket(self):
        node = _make_node()
        node._zmq_ctx = MagicMock()
        node._zmq_sub = MagicMock()
        node._zmq_sub.closed = False
        node._zmq_push = MagicMock()
        node._zmq_push.closed = False
        mock_sock = MagicMock()
        node._sock = mock_sock
        node._teardown()
        mock_sock.close.assert_called_once()
        self.assertIsNone(node._sock)

    def test_pushes_offline_status(self):
        node = _make_node()
        node._zmq_ctx = MagicMock()
        node._zmq_sub = MagicMock()
        node._zmq_sub.closed = False
        node._zmq_push = MagicMock()
        node._zmq_push.closed = False
        node._teardown()
        sent = node._zmq_push.send_multipart.call_args_list
        self.assertGreater(len(sent), 0)
        topic, payload_bytes = sent[0][0][0]
        self.assertEqual(topic, TOPIC_STATUS)
        payload = json.loads(payload_bytes)
        self.assertEqual(payload["status"], "offline")


class TestTopicsAndConstants(unittest.TestCase):
    def test_all_command_topics_in_subscribed(self):
        for topic in [TOPIC_FACE_EXPRESSION_TRACKING, TOPIC_EYE_TRACKING, TOPIC_SET_EXPRESSION, TOPIC_EYES_BRIGHTNESS, TOPIC_EYE_STATE, TOPIC_EYES_VIDEO]:
            self.assertIn(topic, SUBSCRIBED_TOPICS)

    def test_expression_index_covers_expected_expressions(self):
        required = {"angry", "happy", "sad", "neutral", "surprised"}
        self.assertTrue(required.issubset(EXPRESSION_INDEX.keys()))

    def test_num_emotions_matches_expression_index(self):
        self.assertEqual(NUM_EMOTIONS, len(EXPRESSION_INDEX))

    def test_expression_indices_are_unique_and_contiguous(self):
        indices = sorted(EXPRESSION_INDEX.values())
        self.assertEqual(indices, list(range(NUM_EMOTIONS)))


if __name__ == "__main__":
    unittest.main()
