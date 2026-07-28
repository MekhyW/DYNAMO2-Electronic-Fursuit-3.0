import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
import zmq
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
import src.windows as windows

class TestWindowsNode(unittest.TestCase):
    @patch("src.windows.psutil")
    def test_get_cpu_info(self, mock_psutil):
        mock_freq = MagicMock()
        mock_freq.max = 3500.0
        mock_freq.min = 800.0
        mock_freq.current = 2400.0
        mock_psutil.cpu_freq.return_value = mock_freq
        mock_psutil.cpu_count.side_effect = [4, 8]
        mock_psutil.cpu_percent.return_value = 15.5
        info = windows.get_cpu_info()
        self.assertEqual(info["physical_cores"], 4)
        self.assertEqual(info["total_cores"], 8)
        self.assertEqual(info["max_frequency"], 3500.0)
        self.assertEqual(info["current_frequency"], 2400.0)
        self.assertEqual(info["usage"], 15.5)

    @patch("src.windows.psutil")
    def test_get_memory_info(self, mock_psutil):
        mock_vm = MagicMock()
        mock_vm.total = 16000000000
        mock_vm.available = 8000000000
        mock_vm.used = 8000000000
        mock_vm.percent = 50.0
        mock_psutil.virtual_memory.return_value = mock_vm
        info = windows.get_memory_info()
        self.assertEqual(info["total"], 16000000000)
        self.assertEqual(info["available"], 8000000000)
        self.assertEqual(info["percent"], 50.0)

    @patch("src.windows.psutil")
    def test_get_disk_info(self, mock_psutil):
        mock_du = MagicMock()
        mock_du.total = 500000000000
        mock_du.used = 250000000000
        mock_du.free = 250000000000
        mock_du.percent = 50.0
        mock_psutil.disk_usage.return_value = mock_du
        info = windows.get_disk_info()
        self.assertEqual(info["total"], 500000000000)
        self.assertEqual(info["percent"], 50.0)

    @patch("src.windows.AudioUtilities")
    @patch("src.windows.comtypes")
    def test_get_system_volume(self, mock_comtypes, mock_audio):
        mock_interface = MagicMock()
        mock_volume = MagicMock()
        mock_volume.GetMasterVolumeLevelScalar.return_value = 0.75
        mock_audio.GetSpeakers.return_value.Activate.return_value = mock_interface
        with patch("src.windows.cast", return_value=mock_volume):
            vol = windows.get_system_volume()
            self.assertEqual(vol, 0.75)
            mock_comtypes.CoInitialize.assert_called_once()

    @patch("src.windows.AudioUtilities")
    @patch("src.windows.comtypes")
    def test_set_system_volume(self, mock_comtypes, mock_audio):
        mock_interface = MagicMock()
        mock_volume = MagicMock()
        mock_audio.GetSpeakers.return_value.Activate.return_value = mock_interface
        with patch("src.windows.cast", return_value=mock_volume):
            windows.set_system_volume(0.5)
            mock_volume.SetMasterVolumeLevelScalar.assert_called_once_with(0.5, None)
            # test clamping
            mock_volume.SetMasterVolumeLevelScalar.reset_mock()
            windows.set_system_volume(1.5)
            mock_volume.SetMasterVolumeLevelScalar.assert_called_once_with(1.0, None)
            mock_volume.SetMasterVolumeLevelScalar.reset_mock()
            windows.set_system_volume(-0.5)
            mock_volume.SetMasterVolumeLevelScalar.assert_called_once_with(0.0, None)

    @patch("src.windows.subprocess.run")
    @patch("src.windows.os.path.exists")
    def test_refresh_sound_devices(self, mock_exists, mock_run):
        mock_exists.return_value = True
        mock_data = [
            {"Type": "Device", "Device Name": "Test Speaker", "Item ID": "dev-123"},
            {"Type": "Application", "Device Name": "Discord", "Item ID": "discord-id"}
        ]
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
            devices = windows.refresh_sound_devices()
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["Name"], "Test Speaker")
            self.assertEqual(devices[0]["ID"], "dev-123")
            mock_run.assert_called_once_with(["SoundVolumeView.exe", "/sjson", "sound_volume.json"], shell=True, check=False)

    @patch("src.windows.refresh_sound_devices")
    def test_set_default_sound_device(self, mock_refresh):
        mock_refresh.return_value = [{"Name": "Test Speaker", "ID": "dev-123"}]
        windows.set_default_sound_device("Test Speaker", "output")
        with self.assertRaises(ValueError):
            windows.set_default_sound_device("Unknown Device", "output")

    @patch("src.windows.zmq.Context")
    def test_node_zmq_setup(self, mock_context_class):
        mock_context = MagicMock()
        mock_sub = MagicMock()
        mock_push = MagicMock()
        mock_context.socket.side_effect = [mock_sub, mock_push]
        mock_context_class.return_value = mock_context
        node = windows.WindowsNode()
        node._setup_zmq()
        mock_context.socket.assert_any_call(zmq.SUB)
        mock_context.socket.assert_any_call(zmq.PUSH)
        mock_sub.connect.assert_called_with(windows.ZMQ_SUB_ADDRESS)
        mock_push.connect.assert_called_with(windows.ZMQ_PUSH_ADDRESS)

    @patch("src.windows.subprocess.run")
    def test_handlers(self, mock_run):
        node = windows.WindowsNode()
        node._handle_shutdown({})
        mock_run.assert_called_with(["shutdown", "/s", "/t", "1"], check=False)
        mock_run.reset_mock()
        node._handle_reboot({})
        mock_run.assert_called_with(["shutdown", "/r", "/t", "1"], check=False)
        mock_run.reset_mock()
        node._handle_kill_software({})
        mock_run.assert_called_with(["taskkill", "/f", "/im", "DYNAMO-2.exe"], check=False)
        with patch("src.windows.set_system_volume") as mock_set_vol:
            node._handle_set_output_volume({"volume": 80.0})
            mock_set_vol.assert_called_once_with(80)
        with patch("src.windows.set_default_sound_device") as mock_set_device:
            node._handle_set_sound_device({"deviceName": "Speaker", "deviceType": "output"})
            mock_set_device.assert_called_once_with("Speaker", "output")

    def test_event_loop_processing(self):
        node = windows.WindowsNode()
        node._running.set()
        mock_sub = MagicMock()
        node._zmq_sub = mock_sub
        node._zmq_push = MagicMock()
        node._handle_set_output_volume = MagicMock()
        node._handlers[windows.TOPIC_SET_OUTPUT_VOLUME] = node._handle_set_output_volume
        def side_effect():
            if node._running.is_set():
                node._running.clear()
                return [windows.TOPIC_SET_OUTPUT_VOLUME, b'{"volume": 50.0}']
            raise zmq.Again()
        mock_sub.recv_multipart.side_effect = side_effect
        node._event_loop()
        node._handle_set_output_volume.assert_called_once_with({"volume": 50.0})

    def test_teardown(self):
        node = windows.WindowsNode()
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
