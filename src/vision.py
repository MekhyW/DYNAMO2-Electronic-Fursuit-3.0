from __future__ import annotations
import argparse
import base64
import json
import logging
import signal
import threading
import time
from pathlib import Path
from typing import Any
import cv2
from ultralytics import YOLO
import zmq
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] vision: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("vision")

ZMQ_SUB_ADDRESS = "tcp://localhost:5555"
ZMQ_PUSH_ADDRESS = "tcp://localhost:5556"
STATUS_PUBLISH_INTERVAL = 5.0

TOPIC_STATUS = b"dynamo/camera/status"
TOPIC_RAW = b"dynamo/camera/raw"
TOPIC_DETECTION = b"dynamo/camera/detection"
TOPIC_LIGHTING = b"dynamo/camera/lighting"

MODEL_PATH = "models/object-detector-fh.pt"
OPENVINO_DEVICE = "intel:gpu"
OPENVINO_BACKEND = "openvino"
TRACKER_CONFIG = "bytetrack.yaml"
JPEG_QUALITY = 80
DEFAULT_CAMERA_SOURCE = 0
DEFAULT_CONFIDENCE = 0.5


def estimate_lighting(frame: Any, timestamp: float | None = None) -> dict[str, Any]:
    """Estimate scene brightness from the frame's perceptual luminance."""
    if frame is None or getattr(frame, "size", 0) == 0:
        raise ValueError("Cannot estimate lighting from an empty frame")
    if len(frame.shape) == 2:
        mean_luma = float(frame.mean())
    else:
        means = frame.mean(axis=(0, 1))
        mean_bgr = [float(value) for value in means[:3]]
        mean_luma = 0.114 * mean_bgr[0] + 0.587 * mean_bgr[1] + 0.299 * mean_bgr[2]
    brightness = max(0.0, min(1.0, mean_luma / 255.0))
    return {
        "timestamp": time.time() if timestamp is None else timestamp,
        "brightness": round(brightness, 4),
        "mean_luminance": round(mean_luma / 255.0, 4),
    }


def encode_frame(frame: Any, timestamp: float | None = None) -> dict[str, Any]:
    """Encode a captured frame as a JSON-safe JPEG payload."""
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("OpenCV could not encode the camera frame as JPEG")
    height, width = frame.shape[:2]
    return {
        "timestamp": time.time() if timestamp is None else timestamp,
        "width": int(width),
        "height": int(height),
        "data": base64.b64encode(encoded.tobytes()).decode("ascii"),
    }


class CameraCapture:
    """Small wrapper around OpenCV's camera capture with explicit cleanup."""
    def __init__(self, source: int | str = DEFAULT_CAMERA_SOURCE) -> None:
        self.source = source
        self._capture: Any = None

    def start(self) -> None:
        self._capture = cv2.VideoCapture(self.source)
        if self._capture is None or not self._capture.isOpened():
            self.stop()
            raise RuntimeError(f"Cannot open camera source {self.source!r}")

    def read(self) -> Any | None:
        if self._capture is None:
            raise RuntimeError("Camera has not been started")
        ok, frame = self._capture.read()
        return frame if ok else None

    def stop(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def _as_list(values: Any) -> list[Any]:
    """Convert an Ultralytics tensor or array-like value to a Python list."""
    if values is None:
        return []
    if hasattr(values, "detach"):
        values = values.detach()
    if hasattr(values, "cpu"):
        values = values.cpu()
    if hasattr(values, "numpy"):
        values = values.numpy()
    if hasattr(values, "tolist"):
        values = values.tolist()
    return list(values)


def _class_name(names: Any, class_id: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_id, names.get(str(class_id), class_id)))
    if isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


class VisionProcessor:
    """YOLO detector configured for OpenVINO and persistent ByteTrack state."""
    def __init__(self, model_path: str | Path = MODEL_PATH, *, device: str = OPENVINO_DEVICE, confidence: float = DEFAULT_CONFIDENCE,) -> None:
        self.model_path = Path(model_path)
        self.device = device
        self.confidence = confidence
        self.model: Any = None
        self.inference_model_path: Path | None = None
        self._load_model()

    def _load_model(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(f"YOLO model not found: {self.model_path}")
        exported_dir = self.model_path.with_name(f"{self.model_path.stem}_openvino_model")
        if exported_dir.is_dir():
            self.inference_model_path = exported_dir
            self.model = YOLO(str(exported_dir))
            log.info("Loaded existing OpenVINO model %s", exported_dir)
            return
        log.info("Exporting %s to OpenVINO (one-time operation)...", self.model_path)
        pytorch_model = YOLO(str(self.model_path))
        exported = pytorch_model.export(format=OPENVINO_BACKEND)
        exported_path = Path(exported) if exported is not None else exported_dir
        if exported_path.is_file():
            exported_path = exported_path.parent
        if not exported_path.is_dir():
            exported_path = exported_dir # Ultralytics versions differ in whether export() returns the directory, the XML file, or no value at all.
        if not exported_path.is_dir():
            raise RuntimeError(f"OpenVINO export did not produce a model directory: {exported_path}")
        self.inference_model_path = exported_path
        self.model = YOLO(str(exported_path))
        log.info("Loaded OpenVINO model %s", exported_path)

    def process(self, frame: Any) -> tuple[Any, list[dict[str, Any]]]:
        """Run one tracked inference and return the raw result plus JSON detections."""
        if self.model is None:
            raise RuntimeError("Vision model is not loaded")
        results = self.model.track(source=frame, persist=True, tracker=TRACKER_CONFIG, conf=self.confidence, device=self.device, verbose=False)
        result = results[0] if isinstance(results, (list, tuple)) else results
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return result, []
        xyxy = _as_list(getattr(boxes, "xyxy", None))
        confidences = _as_list(getattr(boxes, "conf", None))
        class_ids = _as_list(getattr(boxes, "cls", None))
        track_ids = _as_list(getattr(boxes, "id", None))
        names = getattr(result, "names", getattr(self.model, "names", {}))
        detections: list[dict[str, Any]] = []
        for index, coordinates in enumerate(xyxy):
            if len(coordinates) < 4:
                continue
            class_id = int(class_ids[index]) if index < len(class_ids) else -1
            track_id: int | None = None
            if index < len(track_ids) and track_ids[index] is not None:
                track_id = int(track_ids[index])
            detections.append({
                "bbox": [round(float(value), 2) for value in coordinates[:4]],
                "confidence": round(float(confidences[index]), 4) if index < len(confidences) else None,
                "class_id": class_id,
                "label": _class_name(names, class_id),
                "track_id": track_id,
            })
        return result, detections

    @staticmethod
    def annotate(result: Any, frame: Any) -> Any:
        plot = getattr(result, "plot", None)
        if callable(plot):
            return plot()
        return frame


class VisionNode:
    """Capture, infer, and publish camera data on the local ZeroMQ bus."""
    def __init__(self, source: int | str = DEFAULT_CAMERA_SOURCE, *, model_path: str | Path = MODEL_PATH, device: str = OPENVINO_DEVICE, confidence: float = DEFAULT_CONFIDENCE,) -> None:
        self.source = source
        self.model_path = Path(model_path)
        self.device = device
        self.confidence = confidence
        self._running = threading.Event()
        self._push_lock = threading.Lock()
        self._zmq_ctx: Any = None
        self._zmq_push: Any = None
        self._camera = CameraCapture(source)
        self._processor: VisionProcessor | None = None
        self._frame_count = 0
        self._started_at = 0.0
        self._last_status = 0.0
        self._last_error: str | None = None

    def start(self) -> None:
        """Run until stop() is called or the camera fails."""
        self._running.set()
        try:
            self._setup_zmq()
            self._processor = VisionProcessor(self.model_path, device=self.device, confidence=self.confidence)
            self._camera.start()
            self._started_at = time.time()
            self._publish_status("online")
            log.info("Vision node started — camera=%r model=%s", self.source, self.model_path)
            while self._running.is_set():
                frame = self._camera.read()
                if frame is None:
                    raise RuntimeError("Camera stopped returning frames")
                self._publish_frame(frame)
        except Exception as exc:
            self._last_error = str(exc)
            log.exception("Vision node failed")
        finally:
            self._teardown()

    def stop(self) -> None:
        log.info("Stopping vision node...")
        self._running.clear()

    def _setup_zmq(self) -> None:
        self._zmq_ctx = zmq.Context()
        self._zmq_push = self._zmq_ctx.socket(zmq.PUSH)
        self._zmq_push.connect(ZMQ_PUSH_ADDRESS)

    def _publish_frame(self, frame: Any) -> None:
        assert self._processor is not None
        timestamp = time.time()
        result, detections = self._processor.process(frame)
        self._frame_count += 1
        self._push(TOPIC_RAW, encode_frame(frame, timestamp))
        self._push(TOPIC_DETECTION, {
            "timestamp": timestamp,
            "frame": self._frame_count,
            "backend": OPENVINO_BACKEND,
            "detections": detections,
        })
        self._push(TOPIC_LIGHTING, estimate_lighting(frame, timestamp))
        if timestamp - self._last_status >= STATUS_PUBLISH_INTERVAL:
            self._publish_status("online")
        if __name__ == "__main__":
            labels = ", ".join(f"{d['label']}#{d['track_id']}" for d in detections)
            log.info("frame=%d detections=%d%s", self._frame_count, len(detections), f" ({labels})" if labels else "")

    def _publish_status(self, state: str) -> None:
        now = time.time()
        payload: dict[str, Any] = {
            "status": state,
            "node": "vision",
            "camera": str(self.source),
            "frames": self._frame_count,
        }
        if self._started_at:
            elapsed = max(now - self._started_at, 1e-9)
            payload["fps"] = round(self._frame_count / elapsed, 2)
        if self._last_error:
            payload["error"] = self._last_error
        self._push(TOPIC_STATUS, payload)
        self._last_status = now

    def _push(self, topic: bytes, payload: dict[str, Any]) -> None:
        if self._zmq_push is None:
            return
        try:
            with self._push_lock:
                self._zmq_push.send_multipart([topic, json.dumps(payload, separators=(",", ":")).encode()], flags=zmq.NOBLOCK)
        except zmq.Again:
            log.warning("PUSH dropped (no receiver): %s", topic.decode(errors="replace"))
        except zmq.ZMQError as exc:
            log.error("PUSH error on %s: %s", topic.decode(errors="replace"), exc)

    def _teardown(self) -> None:
        self._running.clear()
        self._camera.stop()
        if self._zmq_push is not None:
            self._publish_status("offline")
        if self._zmq_push is not None and not self._zmq_push.closed:
            self._zmq_push.close(linger=200)
        if self._zmq_ctx is not None:
            self._zmq_ctx.term()
        self._zmq_push = None
        self._zmq_ctx = None
        log.info("Vision node stopped.")


def run_manual_test(source: int | str = DEFAULT_CAMERA_SOURCE, *, model_path: str | Path = MODEL_PATH, device: str = OPENVINO_DEVICE, confidence: float = DEFAULT_CONFIDENCE) -> None:
    """Display an annotated live preview without starting the MQTT bridge."""
    camera = CameraCapture(source)
    processor = VisionProcessor(model_path, device=device, confidence=confidence)
    camera.start()
    log.info("Manual test started — press q or Escape to quit")
    try:
        while True:
            frame = camera.read()
            if frame is None:
                raise RuntimeError("Camera stopped returning frames")
            result, detections = processor.process(frame)
            preview = processor.annotate(result, frame)
            lighting = estimate_lighting(frame)
            cv2.putText(preview, f"{lighting['brightness']:.2f} | objects: {len(detections)}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
            cv2.imshow("DYNAMO camera vision", preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        camera.stop()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", "--source", default=str(DEFAULT_CAMERA_SOURCE), help="Camera index or video source path (default: 0).")
    parser.add_argument("--model", type=Path, default=MODEL_PATH, help="Path to the YOLO .pt model.")
    parser.add_argument("--device", default=OPENVINO_DEVICE, help="OpenVINO device, e.g. intel:cpu or intel:gpu.")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE, help="Minimum detection confidence.")
    parser.add_argument("--manual-test", "--test", "--monitor", action="store_true", help="Show a local annotated camera preview instead of publishing to ZeroMQ.")
    args = parser.parse_args()
    source = int(args.camera) if args.camera.isdigit() else args.camera
    if args.manual_test:
        run_manual_test(source, model_path=args.model, device=args.device, confidence=args.confidence)
        return
    node = VisionNode(source, model_path=args.model, device=args.device, confidence=args.confidence)
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received signal %d — shutting down", signum)
        node.stop()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    node.start()


if __name__ == "__main__":
    main()
