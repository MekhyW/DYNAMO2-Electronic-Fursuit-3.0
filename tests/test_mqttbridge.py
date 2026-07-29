import unittest
from unittest.mock import MagicMock, patch
import zmq
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
from src.mqttbridge import MQTTBridgeNode, BridgeConfig

class TestMQTTBridge(unittest.TestCase):
    def setUp(self):
        self.config = BridgeConfig(
            hivemq_host="mock-cloud-host",
            hivemq_port=8883,
            hivemq_username="user",
            hivemq_password="password",
            local_mqtt_host="localhost",
            local_mqtt_port=1883,
            zmq_pub_address="inproc://test-pub",
            zmq_pull_address="inproc://test-pull",
            heartbeat_interval=0.1,
            health_check_interval=0.2,
            keepalive=15
        )
        self.mqtt_patcher = patch("src.mqttbridge.mqtt.Client")
        self.mock_mqtt_client_class = self.mqtt_patcher.start()
        self.mock_cloud_client = MagicMock()
        self.mock_local_client = MagicMock()
        def client_side_effect(client_id="", protocol=None):
            if "cloud" in client_id:
                return self.mock_cloud_client
            else:
                return self.mock_local_client
        self.mock_mqtt_client_class.side_effect = client_side_effect

    def tearDown(self):
        self.mqtt_patcher.stop()

    def test_config_loading_failure(self):
        from src.mqttbridge import load_config
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                load_config()

    def test_config_loading_success(self):
        from src.mqttbridge import load_config
        with patch.dict("os.environ", {
            "mqtt_host": "hive.com",
            "mqtt_port": "8883",
            "mqtt_username": "foo",
            "mqtt_password": "bar"
        }):
            cfg = load_config()
            self.assertEqual(cfg.hivemq_host, "hive.com")
            self.assertEqual(cfg.hivemq_port, 8883)
            self.assertEqual(cfg.hivemq_username, "foo")
            self.assertEqual(cfg.hivemq_password, "bar")

    def test_fan_out_rules(self):
        node = MQTTBridgeNode(self.config)
        node._cloud_connected.set()
        node._local_connected.set()        
        # Mock ZMQ pub call
        node._zmq_pub = MagicMock()
        node._publish_cloud = MagicMock()
        node._publish_local = MagicMock()
        # JSON validation check - invalid JSON should be dropped
        node._fan_out("dynamo/test", b"invalid json", "cloud")
        node._publish_local.assert_not_called()
        node._zmq_pub.assert_not_called()
        # 1. Cloud message -> local and ZMQ
        valid_payload = b'{"status": "ok"}'
        node._fan_out("dynamo/test", valid_payload, "cloud")
        node._publish_local.assert_called_once_with("dynamo/test", None, raw=valid_payload)
        node._zmq_pub.assert_called_once_with(b"dynamo/test", valid_payload)
        node._publish_cloud.assert_not_called()
        node._publish_local.reset_mock()
        node._zmq_pub.reset_mock()
        node._publish_cloud.reset_mock()
        # 2. Local message -> cloud and ZMQ
        node._fan_out("dynamo/test", valid_payload, "local")
        node._publish_cloud.assert_called_once_with("dynamo/test", None, raw=valid_payload, retain=False)
        node._zmq_pub.assert_called_once_with(b"dynamo/test", valid_payload)
        node._publish_local.assert_not_called()
        node._publish_local.reset_mock()
        node._zmq_pub.reset_mock()
        node._publish_cloud.reset_mock()
        # 3. ZMQ message -> cloud and local
        node._fan_out("dynamo/test", valid_payload, "zmq")
        node._publish_cloud.assert_called_once_with("dynamo/test", None, raw=valid_payload, retain=False)
        node._publish_local.assert_called_once_with("dynamo/test", None, raw=valid_payload)
        node._zmq_pub.assert_not_called()

    def test_publish_functions_respect_connection_status(self):
        node = MQTTBridgeNode(self.config)
        node._cloud_connected.clear()
        node._publish_cloud("dynamo/test", {"data": 1})
        self.mock_cloud_client.publish.assert_not_called()
        node._cloud_connected.set()
        node._publish_cloud("dynamo/test", {"data": 1})
        self.mock_cloud_client.publish.assert_called_once()
        node._local_connected.clear()
        node._publish_local("dynamo/test", {"data": 2})
        self.mock_local_client.publish.assert_not_called()
        node._local_connected.set()
        node._publish_local("dynamo/test", {"data": 2})
        self.mock_local_client.publish.assert_called_once()

    def test_zmq_pull_loop(self):
        node = MQTTBridgeNode(self.config)
        node._running.set()
        mock_ctx = MagicMock()
        mock_pull = MagicMock()
        node._zmq_ctx = mock_ctx
        node._pull = mock_pull
        node._fan_out = MagicMock()
        # Mock recv_multipart sequence:
        # First call: return valid 2 frames
        # Second call: raise zmq.Again to simulate timeout/empty queue
        # Third call: stop loop by clearing run event
        def side_effect():
            if node._running.is_set():
                # First iteration: return mock message
                node._running.clear() # clear to stop loop after this
                return [b"dynamo/test", b'{"value": 42}']
            raise zmq.Again()
        mock_pull.recv_multipart.side_effect = side_effect
        node._pull_loop()
        node._fan_out.assert_called_once_with("dynamo/test", b'{"value": 42}', "zmq")

    def test_teardown(self):
        node = MQTTBridgeNode(self.config)
        node._zmq_ctx = MagicMock()
        node._pub = MagicMock()
        node._pub.closed = False
        node._pull = MagicMock()
        node._pull.closed = False
        node._teardown()
        self.mock_cloud_client.loop_stop.assert_called_once()
        self.mock_local_client.loop_stop.assert_called_once()
        self.mock_cloud_client.disconnect.assert_called_once()
        self.mock_local_client.disconnect.assert_called_once()
        node._pub.close.assert_called_once_with(linger=0)
        node._pull.close.assert_called_once_with(linger=0)
        node._zmq_ctx.destroy.assert_called_once_with(linger=0)

if __name__ == "__main__":
    unittest.main()
