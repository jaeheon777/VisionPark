"""Tracking integration checks without downloading weights or opening windows."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from vision import vehicle_tracking


class VehicleTrackingTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock(task="detect")
        self.model.names = {0: "person", 10: "car", 11: "motorcycle", 12: "bus", 13: "truck"}
        self.yolo = Mock(return_value=self.model)
        patcher = patch.dict(sys.modules, {"ultralytics": SimpleNamespace(YOLO=self.yolo)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.frame = np.zeros((200, 300, 3), dtype=np.uint8)

    def result(self, coords, classes, scores, ids):
        boxes = Mock()
        boxes.xyxy.cpu.return_value.tolist.return_value = coords
        boxes.cls.cpu.return_value.tolist.return_value = classes
        boxes.conf.cpu.return_value.tolist.return_value = scores
        if ids is None:
            boxes.id = None
        else:
            boxes.id.int.return_value.cpu.return_value.tolist.return_value = ids
        return SimpleNamespace(boxes=boxes)

    def test_track_ids_and_boxes_follow_successive_frames(self):
        first = self.result(
            [[10, 30, 80, 90], [100, 40, 170, 100]], [10, 13], [0.91, 0.82], [4, 9]
        )
        second = self.result(
            [[20, 30, 90, 90], [110, 40, 180, 100]], [10, 13], [0.88, 0.78], [4, 9]
        )
        self.model.track.side_effect = [[first], [second]]
        tracker = vehicle_tracking.VehicleTracker("local.pt", 0.3)
        with patch("cv2.rectangle") as rectangle, patch("cv2.putText") as label:
            self.assertIs(tracker(self.frame), self.frame)
            self.assertIs(tracker(self.frame), self.frame)

        self.yolo.assert_called_once_with("local.pt")
        self.assertEqual(self.model.track.call_count, 2)
        for call in self.model.track.call_args_list:
            self.assertEqual(call.kwargs, {
                "source": self.frame, "classes": [10, 11, 12, 13], "conf": 0.1,
                "device": "cpu", "verbose": False, "save": False,
                "persist": True, "tracker": "bytetrack.yaml",
            })
        self.assertEqual([call.args[1:3] for call in rectangle.call_args_list], [
            ((10, 30), (80, 90)), ((100, 40), (170, 100)),
            ((20, 30), (90, 90)), ((110, 40), (180, 100)),
        ])
        self.assertEqual([call.args[1] for call in label.call_args_list], [
            "car ID 4 0.91", "truck ID 9 0.82", "car ID 4 0.88", "truck ID 9 0.78",
        ])

    def test_only_tracked_vehicle_classes_above_threshold_are_drawn(self):
        self.model.track.return_value = [self.result(
            [[1, 2, 10, 20]] * 6, [0, 10, 11, 12, 13, 10],
            [0.99, 0.90, 0.81, 0.72, 0.63, 0.1], [1, 2, 3, 4, 5, 6]
        )]
        tracker = vehicle_tracking.VehicleTracker()
        with patch("cv2.rectangle") as rectangle, patch("cv2.putText") as label:
            tracker(self.frame)
        self.assertEqual(rectangle.call_count, 4)
        self.assertEqual([call.args[1] for call in label.call_args_list], [
            "car ID 2 0.90", "motorcycle ID 3 0.81",
            "bus ID 4 0.72", "truck ID 5 0.63",
        ])

    def test_no_tracks_leaves_frame_unchanged(self):
        tracker = vehicle_tracking.VehicleTracker()
        for boxes in (None, self.result([], [], [], None).boxes):
            with self.subTest(boxes=boxes), patch("cv2.rectangle") as rectangle:
                self.model.track.return_value = [SimpleNamespace(boxes=boxes)]
                self.assertIs(tracker(self.frame), self.frame)
                rectangle.assert_not_called()
        self.assertFalse(self.frame.any())

    def test_tracking_and_display_thresholds_are_independent(self):
        self.model.track.return_value = [self.result(
            [[10, 20, 50, 60], [60, 20, 100, 60]], [10, 10], [0.15, 0.85], [1, 2]
        )]
        for display_threshold, expected_labels in (
            (0.05, ["car ID 1 0.15", "car ID 2 0.85"]),
            (0.5, ["car ID 2 0.85"]),
        ):
            with self.subTest(display_threshold=display_threshold), \
                 patch("cv2.rectangle") as rectangle, patch("cv2.putText") as label:
                tracker = vehicle_tracking.VehicleTracker(confidence=display_threshold)
                tracker(self.frame)
                self.assertEqual(self.model.track.call_args.kwargs["conf"],
                                 vehicle_tracking.TRACKING_CONFIDENCE)
                self.assertEqual(rectangle.call_count, len(expected_labels))
                self.assertEqual([call.args[1] for call in label.call_args_list], expected_labels)

    def test_tracking_error_is_reported(self):
        tracker = vehicle_tracking.VehicleTracker()
        self.model.track.side_effect = RuntimeError("tracker failed")
        with self.assertRaisesRegex(RuntimeError, "vehicle tracking or annotation failed"):
            tracker(self.frame)

    def test_cli_uses_existing_video_pipeline(self):
        with patch.object(sys, "argv", ["vehicle_tracking", "sample.mp4", "--confidence", "0.4"]), \
             patch.object(vehicle_tracking, "play_video", return_value=0) as play:
            self.assertEqual(vehicle_tracking.main(), 0)
        self.assertEqual(play.call_args.args, (vehicle_tracking.Path("sample.mp4"),))
        tracker = play.call_args.kwargs["processor_factory"]()
        self.assertIsInstance(tracker, vehicle_tracking.VehicleTracker)
        self.assertEqual(tracker.confidence, 0.4)


if __name__ == "__main__":
    unittest.main()
