import base64
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


class _Encoded:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def tobytes(self) -> bytes:
        return self._data


class _Frame:
    """Small numpy-like frame used so these tests do not require numpy."""

    def __init__(self, shape=(2, 3, 3), means=(10.0, 20.0, 30.0)) -> None:
        self.shape = shape
        self.size = 1
        self._means = means

    def mean(self, axis=None):
        return self._means if axis is not None else sum(self._means) / len(self._means)


def _missing_module(name: str, **attrs):
    if importlib.util.find_spec(name) is not None:
        return None
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


_fake_cv2 = _missing_module("cv2", IMWRITE_JPEG_QUALITY=95, imencode=MagicMock(), VideoCapture=MagicMock())
_fake_ultralytics = _missing_module("ultralytics", YOLO=MagicMock(name="YOLO"))
_fake_zmq = _missing_module("zmq", PUSH=1, NOBLOCK=2, Again=type("Again", (Exception,), {}), ZMQError=type("ZMQError", (Exception,), {}))
_vision_modules = {}
if _fake_cv2 is not None:
    _vision_modules["cv2"] = _fake_cv2
if _fake_ultralytics is not None:
    _vision_modules["ultralytics"] = _fake_ultralytics
if _fake_zmq is not None:
    _vision_modules["zmq"] = _fake_zmq

with patch.dict(sys.modules, _vision_modules):
    from src import vision


class TestVisionHelpers(unittest.TestCase):
    def setUp(self):
        self.cv = SimpleNamespace(IMWRITE_JPEG_QUALITY=95, imencode=MagicMock(return_value=(True, _Encoded(b"jpeg-bytes"))))
        self.cv_original = vision.cv2
        vision.cv2 = self.cv

    def tearDown(self):
        vision.cv2 = self.cv_original

    def test_estimate_lighting_uses_perceptual_luminance_and_timestamp(self):
        frame = _Frame(means=(0.0, 100.0, 200.0))
        payload = vision.estimate_lighting(frame, timestamp=123.5)
        expected_luma = (0.114 * 0.0 + 0.587 * 100.0 + 0.299 * 200.0) / 255.0
        self.assertEqual(payload["timestamp"], 123.5)
        self.assertAlmostEqual(payload["brightness"], round(expected_luma, 4))
        self.assertEqual(payload["mean_luminance"], round(expected_luma, 4))

    def test_estimate_lighting_rejects_empty_frames(self):
        frame = _Frame()
        frame.size = 0
        with self.assertRaisesRegex(ValueError, "empty frame"):
            vision.estimate_lighting(frame)

    def test_estimate_lighting_supports_grayscale_frames(self):
        frame = _Frame(shape=(2, 3), means=(64.0,))
        payload = vision.estimate_lighting(frame, timestamp=1.0)
        self.assertEqual(payload["brightness"], round(64.0 / 255.0, 4))

    def test_encode_frame_returns_json_safe_base64_jpeg(self):
        frame = _Frame(shape=(4, 5, 3))
        payload = vision.encode_frame(frame, timestamp=10.0)
        self.assertEqual(payload["timestamp"], 10.0)
        self.assertEqual((payload["width"], payload["height"]), (5, 4))
        self.assertEqual(base64.b64decode(payload["data"]), b"jpeg-bytes")
        self.cv.imencode.assert_called_once_with(".jpg", frame, [self.cv.IMWRITE_JPEG_QUALITY, vision.JPEG_QUALITY])

    def test_encode_frame_rejects_failed_opencv_encoding(self):
        self.cv.imencode.return_value = (False, None)
        with self.assertRaisesRegex(ValueError, "could not encode"):
            vision.encode_frame(_Frame())


class TestCameraCapture(unittest.TestCase):
    def setUp(self):
        self.cv_original = vision.cv2
        self.cv = SimpleNamespace(VideoCapture=MagicMock())
        vision.cv2 = self.cv

    def tearDown(self):
        vision.cv2 = self.cv_original

    def test_start_read_and_stop_manage_capture(self):
        capture_handle = MagicMock()
        capture_handle.isOpened.return_value = True
        capture_handle.read.return_value = (True, "frame")
        self.cv.VideoCapture.return_value = capture_handle
        camera = vision.CameraCapture(2)
        camera.start()
        self.cv.VideoCapture.assert_called_once_with(2)
        self.assertEqual(camera.read(), "frame")
        camera.stop()
        capture_handle.release.assert_called_once_with()
        self.assertIsNone(camera._capture)

    def test_read_requires_started_camera(self):
        with self.assertRaisesRegex(RuntimeError, "not been started"):
            vision.CameraCapture().read()

    def test_start_releases_and_reports_unavailable_camera(self):
        capture_handle = MagicMock()
        capture_handle.isOpened.return_value = False
        self.cv.VideoCapture.return_value = capture_handle
        with self.assertRaisesRegex(RuntimeError, "Cannot open camera source"):
            vision.CameraCapture("camera").start()
        capture_handle.release.assert_called_once_with()


class TestVisionProcessor(unittest.TestCase):
    def _model_path(self, directory: Path) -> Path:
        path = directory / "object-detector-fh.pt"
        path.write_bytes(b"weights")
        return path

    def test_loads_existing_openvino_export_without_reexporting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = self._model_path(root)
            exported = root / "object-detector-fh_openvino_model"
            exported.mkdir()
            yolo = MagicMock(name="YOLO")
            with patch.object(vision, "YOLO", yolo):
                processor = vision.VisionProcessor(model_path)
            yolo.assert_called_once_with(str(exported))
            yolo.return_value.export.assert_not_called()
            self.assertEqual(processor.inference_model_path, exported)

    def test_exports_pt_model_to_openvino_when_export_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = self._model_path(root)
            exported = root / "object-detector-fh_openvino_model"
            pytorch_model = MagicMock(name="pytorch_model")
            pytorch_model.export.side_effect = lambda format: (exported.mkdir() or exported)
            yolo = MagicMock(name="YOLO", side_effect=[pytorch_model, MagicMock(name="openvino_model")])
            with patch.object(vision, "YOLO", yolo):
                processor = vision.VisionProcessor(model_path)
            self.assertEqual(yolo.call_args_list[0].args, (str(model_path),))
            pytorch_model.export.assert_called_once_with(format="openvino")
            self.assertEqual(yolo.call_args_list[1].args, (str(exported),))
            self.assertEqual(processor.inference_model_path, exported)

    def test_process_uses_persistent_bytetrack_and_serializes_boxes(self):
        boxes = SimpleNamespace(
            xyxy=[[1.234, 2.0, 30.0, 40.0], [5.0, 6.0, 50.0, 60.0]],
            conf=[0.98765, 0.5],
            cls=[0, 1],
            id=[7, None],
        )
        result = SimpleNamespace(boxes=boxes, names={0: "fursuit", 1: "human"})
        model = MagicMock()
        model.track.return_value = [result]
        processor = object.__new__(vision.VisionProcessor)
        processor.model = model
        processor.device = "intel:gpu"
        processor.confidence = 0.5
        returned_result, detections = processor.process("frame")
        self.assertIs(returned_result, result)
        self.assertEqual(detections, [
            {
                "bbox": [1.23, 2.0, 30.0, 40.0],
                "confidence": 0.9877,
                "class_id": 0,
                "label": "fursuit",
                "track_id": 7,
            },
            {
                "bbox": [5.0, 6.0, 50.0, 60.0],
                "confidence": 0.5,
                "class_id": 1,
                "label": "human",
                "track_id": None,
            },
        ])
        model.track.assert_called_once_with(
            source="frame",
            persist=True,
            tracker=vision.TRACKER_CONFIG,
            conf=0.5,
            device="intel:gpu",
            verbose=False,
        )

    def test_process_handles_results_without_boxes(self):
        result = SimpleNamespace(boxes=None)
        model = MagicMock()
        model.track.return_value = result
        processor = object.__new__(vision.VisionProcessor)
        processor.model = model
        processor.device = vision.OPENVINO_DEVICE
        processor.confidence = vision.DEFAULT_CONFIDENCE
        returned_result, detections = processor.process("frame")
        self.assertIs(returned_result, result)
        self.assertEqual(detections, [])

    def test_process_requires_loaded_model(self):
        processor = object.__new__(vision.VisionProcessor)
        processor.model = None
        with self.assertRaisesRegex(RuntimeError, "not loaded"):
            processor.process("frame")

    def test_annotate_uses_result_plot_or_original_frame(self):
        frame = object()
        result = MagicMock()
        result.plot.return_value = "annotated"
        self.assertEqual(vision.VisionProcessor.annotate(result, frame), "annotated")
        self.assertIs(vision.VisionProcessor.annotate(SimpleNamespace(), frame), frame)


class TestVisionNode(unittest.TestCase):
    def test_publish_frame_emits_raw_detection_and_lighting_topics(self):
        node = vision.VisionNode(1)
        node._processor = MagicMock()
        node._processor.process.return_value = (object(), [{"label": "human", "track_id": 3}])
        node._push = MagicMock()
        frame = _Frame()
        with patch.object(vision, "encode_frame", return_value={"encoding": "jpeg"}), patch.object(vision, "estimate_lighting", return_value={"brightness": 0.5}), patch.object(vision.time, "time", return_value=42.0):
            node._publish_frame(frame)
        self.assertEqual(node._frame_count, 1)
        topics = [call.args[0] for call in node._push.call_args_list]
        self.assertEqual(topics, [vision.TOPIC_RAW, vision.TOPIC_DETECTION, vision.TOPIC_LIGHTING, vision.TOPIC_STATUS])
        detection_payload = node._push.call_args_list[1].args[1]
        self.assertEqual(detection_payload["frame"], 1)
        self.assertEqual(detection_payload["detections"][0]["track_id"], 3)

    def test_push_serializes_json_with_nonblocking_send(self):
        node = vision.VisionNode()
        node._zmq_push = MagicMock()
        fake_zmq = SimpleNamespace(NOBLOCK=9, Again=Exception, ZMQError=Exception)
        with patch.object(vision, "zmq", fake_zmq):
            node._push(vision.TOPIC_STATUS, {"status": "online"})
        node._zmq_push.send_multipart.assert_called_once()
        topic, payload = node._zmq_push.send_multipart.call_args.args[0]
        self.assertEqual(topic, vision.TOPIC_STATUS)
        self.assertEqual(json.loads(payload), {"status": "online"})
        self.assertEqual(node._zmq_push.send_multipart.call_args.kwargs["flags"], 9)

    def test_teardown_stops_camera_publishes_offline_and_closes_zmq(self):
        node = vision.VisionNode()
        node._camera = MagicMock()
        push = MagicMock()
        node._zmq_push = push
        node._zmq_push.closed = False
        context = MagicMock()
        node._zmq_ctx = context
        node._publish_status = MagicMock()
        node._teardown()
        node._camera.stop.assert_called_once_with()
        node._publish_status.assert_called_once_with("offline")
        push.close.assert_called_once_with(linger=200)
        context.term.assert_called_once_with()
        self.assertIsNone(node._zmq_push)
        self.assertIsNone(node._zmq_ctx)


class TestVisionCli(unittest.TestCase):
    def test_manual_test_mode_passes_camera_and_model_options(self):
        with patch.object(vision, "run_manual_test") as manual_test:
            with patch.object(sys, "argv", ["vision.py", "--manual-test", "--camera", "3", "--device", "intel:gpu", "--confidence", "0.4"]):
                vision.main()
        manual_test.assert_called_once_with(3, model_path=Path(vision.MODEL_PATH), device="intel:gpu", confidence=0.4,)


if __name__ == "__main__":
    unittest.main()
