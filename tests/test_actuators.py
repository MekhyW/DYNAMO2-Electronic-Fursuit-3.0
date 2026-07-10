import unittest
from unittest.mock import MagicMock, patch
import json
import zmq
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
from src.actuators import ActuatorState, ActuatorsNode, ServoId, normalised_to_angle, build_servo_command, parse_side, TOPIC_MOVE_EAR, TOPIC_STATE_SERVO

class TestActuators(unittest.TestCase):
    def test_normalised_to_angle(self):
        self.assertEqual(normalised_to_angle(ServoId.EAR_LEFT, 0.0), 0)
        self.assertEqual(normalised_to_angle(ServoId.EAR_LEFT, 0.5), 90)
        self.assertEqual(normalised_to_angle(ServoId.EAR_LEFT, 1.0), 180)
        self.assertEqual(normalised_to_angle(ServoId.EYEBROW_LEFT, 0.0), 30)
        self.assertEqual(normalised_to_angle(ServoId.EYEBROW_LEFT, 0.5), 90)
        self.assertEqual(normalised_to_angle(ServoId.EYEBROW_LEFT, 1.0), 150)

    def test_build_servo_command(self):
        cmd = build_servo_command(ServoId.EAR_LEFT, 0.5)
        self.assertEqual(cmd, {
            "servo": "ear_left",
            "angle": 90,
            "position": 0.5
        })

    def test_parse_side(self):
        self.assertEqual(parse_side({"side": "LEFT"}), "left")
        self.assertEqual(parse_side({"side": "right"}), "right")
        self.assertEqual(parse_side({"side": "both"}), "both")
        self.assertIsNone(parse_side({"side": "invalid"}))
        self.assertIsNone(parse_side({}))

    def test_actuator_state(self):
        state = ActuatorState()
        # Set normal position
        state.set(ServoId.EAR_LEFT, 0.7)
        self.assertEqual(state.positions[ServoId.EAR_LEFT], 0.7)
        # Set position exceeding limits (should clamp)
        state.set(ServoId.EAR_RIGHT, 1.5)
        self.assertEqual(state.positions[ServoId.EAR_RIGHT], 1.0)
        state.set(ServoId.EAR_RIGHT, -0.2)
        self.assertEqual(state.positions[ServoId.EAR_RIGHT], 0.0)
        # Set pose
        pose = {ServoId.MUZZLE: 0.5, ServoId.EYEBROW_LEFT: 0.8}
        state.set_pose(pose)
        self.assertEqual(state.positions[ServoId.MUZZLE], 0.5)
        self.assertEqual(state.positions[ServoId.EYEBROW_LEFT], 0.8)
        # Snapshot checks
        snapshot = state.snapshot()
        self.assertEqual(snapshot["muzzle"], 0.5)
        self.assertEqual(snapshot["eyebrow_left"], 0.8)

    @patch("src.actuators.zmq.Context")
    def test_node_zmq_setup(self, mock_context_class):
        mock_context = MagicMock()
        mock_sub = MagicMock()
        mock_push = MagicMock()
        mock_context.socket.side_effect = [mock_sub, mock_push]
        mock_context_class.return_value = mock_context
        node = ActuatorsNode()
        node._setup_zmq()
        mock_context.socket.assert_any_call(zmq.SUB)
        mock_context.socket.assert_any_call(zmq.PUSH)
        mock_sub.connect.assert_called_with("tcp://localhost:5555")
        mock_push.connect.assert_called_with("tcp://localhost:5556")

    def test_node_event_handling(self):
        node = ActuatorsNode()
        node._zmq_push = MagicMock()
        # 1. Ear move commands
        node._handle_move_ear({"side": "left", "position": 0.2})
        node._zmq_push.send_multipart.assert_called_once()
        topic, payload_bytes = node._zmq_push.send_multipart.call_args[0][0]
        self.assertEqual(topic, TOPIC_STATE_SERVO)
        payload = json.loads(payload_bytes)
        self.assertEqual(payload["servo"], "ear_left")
        self.assertEqual(payload["position"], 0.2)
        node._zmq_push.reset_mock()
        # 2. Eyebrow move commands
        node._handle_move_eyebrow({"side": "right", "position": 0.8})
        topic, payload_bytes = node._zmq_push.send_multipart.call_args[0][0]
        self.assertEqual(topic, TOPIC_STATE_SERVO)
        payload = json.loads(payload_bytes)
        self.assertEqual(payload["servo"], "eyebrow_right")
        self.assertEqual(payload["position"], 0.8)
        node._zmq_push.reset_mock()
        # 3. Muzzle move command
        node._handle_move_muzzle({"position": 0.4})
        topic, payload_bytes = node._zmq_push.send_multipart.call_args[0][0]
        self.assertEqual(topic, TOPIC_STATE_SERVO)
        payload = json.loads(payload_bytes)
        self.assertEqual(payload["servo"], "muzzle")
        self.assertEqual(payload["position"], 0.4)
        node._zmq_push.reset_mock()
        # 4. Set pose command
        node._handle_set_pose({"expression": "happy"})
        # Should push 5 commands (one for each of the 5 servos in the happy macro)
        self.assertEqual(node._zmq_push.send_multipart.call_count, 5)

    def test_event_loop_processing(self):
        node = ActuatorsNode()
        node._running.set()
        mock_sub = MagicMock()
        node._zmq_sub = mock_sub
        node._zmq_push = MagicMock()
        node._handle_move_ear = MagicMock()
        node._handlers[TOPIC_MOVE_EAR] = node._handle_move_ear
        def side_effect():
            if node._running.is_set():
                node._running.clear()
                return [TOPIC_MOVE_EAR, b'{"side": "left", "position": 0.5}']
            raise zmq.Again()
        mock_sub.recv_multipart.side_effect = side_effect
        node._event_loop()
        node._handle_move_ear.assert_called_once_with({"side": "left", "position": 0.5})

    def test_teardown(self):
        node = ActuatorsNode()
        node._zmq_ctx = MagicMock()
        node._zmq_sub = MagicMock()
        node._zmq_sub.closed = False
        node._zmq_push = MagicMock()
        node._zmq_push.closed = False
        node._teardown()
        node._zmq_sub.close.assert_called_once_with(linger=0)
        node._zmq_push.close.assert_called_once_with(linger=0)
        node._zmq_ctx.destroy.assert_called_once_with(linger=0)

if __name__ == "__main__":
    unittest.main()
