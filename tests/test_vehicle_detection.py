"""Detection contract tests without model downloads or desktop windows."""

import argparse
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from vision.vehicle_detection import VehicleDetector, confidence_value


class VehicleDetectionTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock(task="detect")
        # Deliberately use non-COCO IDs to verify name-based class selection.
        self.model.names = {0: "person", 10: "car", 11: "motorcycle", 12: "bus", 13: "truck"}
        self.yolo = Mock(return_value=self.model)
        patcher = patch.dict(sys.modules, {"ultralytics": SimpleNamespace(YOLO=self.yolo)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.frame = np.zeros((200, 300, 3), dtype=np.uint8)

    def results(self, classes, scores):
        boxes = Mock()
        boxes.xyxy.cpu.return_value.tolist.return_value = [[10, 30, 80, 90]] * len(classes)
        boxes.cls.cpu.return_value.tolist.return_value = classes
        boxes.conf.cpu.return_value.tolist.return_value = scores
        self.model.predict.return_value = [SimpleNamespace(boxes=boxes)]

    def test_only_vehicles_have_boxes_and_confidence_labels(self):
        self.results([0, 10, 11, 12, 13, 10], [0.99, 0.91, 0.82, 0.73, 0.64, 0.1])
        detector = VehicleDetector()
        with patch("cv2.rectangle") as rectangle, patch("cv2.putText") as text:
            self.assertIs(detector(self.frame), self.frame)
        self.assertEqual(rectangle.call_count, 4)
        self.assertEqual([call.args[1] for call in text.call_args_list],
                         ["car 0.91", "motorcycle 0.82", "bus 0.73", "truck 0.64"])
        self.assertEqual(rectangle.call_args.args[1:3], ((10, 30), (80, 90)))
        self.model.predict.assert_called_once_with(
            source=self.frame, classes=[10, 11, 12, 13], conf=0.25,
            device="cpu", verbose=False, save=False,
        )

    def test_no_detections_leaves_frame_unchanged(self):
        self.results([], [])
        detector = VehicleDetector()
        self.assertIs(detector(self.frame), self.frame)
        self.assertFalse(self.frame.any())

    def test_model_loaded_once_for_multiple_frames(self):
        self.results([], [])
        detector = VehicleDetector("local.pt", 0.5)
        detector(self.frame)
        detector(self.frame)
        self.yolo.assert_called_once_with("local.pt")
        self.assertEqual(self.model.predict.call_count, 2)

    def test_load_and_dependency_errors_are_explained(self):
        for error in (OSError("weights unavailable"), ImportError("torch missing"), MemoryError("memory")):
            with self.subTest(error=error):
                self.yolo.side_effect = error
                with self.assertRaisesRegex(RuntimeError, "YOLO 모델 로딩 실패"):
                    VehicleDetector()

    def test_wrong_task_or_missing_classes_rejected(self):
        self.model.task = "classify"
        with self.assertRaisesRegex(RuntimeError, "detect"):
            VehicleDetector()
        self.model.task = "detect"
        self.model.names = {0: "person"}
        with self.assertRaisesRegex(RuntimeError, "클래스"):
            VehicleDetector()

    def test_inference_error_is_explained(self):
        detector = VehicleDetector()
        self.model.predict.side_effect = RuntimeError("out of memory")
        with self.assertRaisesRegex(RuntimeError, "YOLO 차량 탐지 또는 시각화 실패"):
            detector(self.frame)

    def test_confidence_validation(self):
        for value in ("0", "-1", "1.1", "nan", "inf", "abc"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                confidence_value(value)
        self.assertEqual(confidence_value("0.5"), 0.5)


if __name__ == "__main__":
    unittest.main()
