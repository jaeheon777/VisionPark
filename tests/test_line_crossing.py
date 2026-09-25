"""Virtual line geometry and tracking integration without weights or MP4 files."""

from contextlib import redirect_stdout
import argparse
import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from vision.line_crossing import LineCrossingDetector, NormalizedLine, bottom_center
from vision.vehicle_tracking import VehicleTracker, dead_zone_value, line_value


class LineCrossingTests(unittest.TestCase):
    def setUp(self):
        self.detector = LineCrossingDetector(NormalizedLine(0.1, 0.5, 0.9, 0.5))
        self.size = (101, 101)

    def update(self, track_id, x, y):
        return self.detector.update(track_id, (x, y), self.size)

    def test_same_side_and_near_line_do_not_cross(self):
        self.assertIsNone(self.update(3, 50, 40))
        self.assertIsNone(self.update(3, 50, 49.9))
        self.assertIsNone(self.update(3, 50, 50))
        self.assertIsNone(self.update(3, 50, 49.8))

    def test_both_directions_and_exact_line_observation(self):
        self.assertIsNone(self.update(3, 50, 40))
        self.assertIsNone(self.update(3, 50, 50))
        self.assertEqual(self.update(3, 50, 60), "B -> A")
        self.assertEqual(self.update(3, 50, 40), "A -> B")

    def test_track_ids_are_independent(self):
        self.assertIsNone(self.update(3, 30, 40))
        self.assertIsNone(self.update(7, 70, 60))
        self.assertEqual(self.update(3, 30, 60), "B -> A")
        self.assertEqual(self.update(7, 70, 40), "A -> B")

    def test_side_change_outside_finite_segment_is_not_crossing(self):
        self.assertIsNone(self.update(3, 95, 40))
        self.assertIsNone(self.update(3, 95, 60))
        self.assertIsNone(self.update(7, 95, 40))
        self.assertIsNone(self.update(7, 95, 50))
        self.assertIsNone(self.update(7, 50, 60))

    def test_jitter_in_dead_zone_emits_once_until_clear_reverse_crossing(self):
        self.assertIsNone(self.update(3, 50, 40))
        for y in (49, 50.5, 49.5, 51.5, 48.5, 51):
            self.assertIsNone(self.update(3, 50, y))
        self.assertEqual(self.update(3, 50, 55), "B -> A")
        for y in (51, 49, 50.5, 48.5, 52):
            self.assertIsNone(self.update(3, 50, y))
        self.assertEqual(self.update(3, 50, 45), "A -> B")

    def test_dead_zone_scales_with_frame_size(self):
        for size, offset in (((101, 101), 1.5), ((1001, 1001), 15)):
            with self.subTest(size=size):
                detector = LineCrossingDetector(NormalizedLine(0, 0.5, 1, 0.5))
                center = (size[1] - 1) / 2
                x = (size[0] - 1) / 2
                self.assertIsNone(detector.update(1, (x, center - 30 * size[1] / 101), size))
                self.assertIsNone(detector.update(1, (x, center + offset), size))
                self.assertEqual(detector.update(1, (x, center + 3 * size[1] / 101), size), "B -> A")

    def test_bottom_center_and_line_validation(self):
        self.assertEqual(bottom_center((10, 20, 30, 60)), (20, 60))
        self.assertEqual(line_value("0.1,0.2,0.9,0.8"), NormalizedLine(0.1, 0.2, 0.9, 0.8))
        for value in ("0,0,0,0", "-0.1,0,1,1", "nan,0,1,1", "0,1,1", "a,0,1,1"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    line_value(value)
        self.assertEqual(dead_zone_value("0.03"), 0.03)
        for value in ("-0.01", "1", "nan", "inf", "abc"):
            with self.subTest(dead_zone=value), self.assertRaises(argparse.ArgumentTypeError):
                dead_zone_value(value)


class CrossingTrackerIntegrationTests(unittest.TestCase):
    def test_tracked_bottom_center_emits_direction_and_draws_line(self):
        model = Mock(task="detect")
        model.names = {10: "car", 11: "motorcycle", 12: "bus", 13: "truck"}

        def result(y, confidence):
            boxes = Mock()
            boxes.xyxy.cpu.return_value.tolist.return_value = [[40, y - 20, 60, y]]
            boxes.cls.cpu.return_value.tolist.return_value = [10]
            boxes.conf.cpu.return_value.tolist.return_value = [confidence]
            boxes.id.int.return_value.cpu.return_value.tolist.return_value = [3]
            return [SimpleNamespace(boxes=boxes)]

        model.track.side_effect = [result(40, 0.9), result(60, 0.15)]
        frame = np.zeros((101, 101, 3), dtype=np.uint8)
        with patch.dict(sys.modules, {"ultralytics": SimpleNamespace(YOLO=Mock(return_value=model))}):
            tracker = VehicleTracker(confidence=0.25, line=NormalizedLine(0, 0.5, 1, 0.5))
        output = io.StringIO()
        with patch("cv2.line") as line, patch("cv2.circle") as circle, \
             patch("cv2.rectangle") as rectangle, patch("cv2.putText") as label, \
             redirect_stdout(output):
            tracker(frame)
            tracker(frame)
        self.assertEqual(line.call_count, 2)
        self.assertEqual(circle.call_count, 1)
        self.assertEqual(rectangle.call_count, 1)
        self.assertEqual(label.call_args.args[1], "car ID 3 0.90")
        self.assertEqual(output.getvalue().strip(), "Track ID 3: B -> A CROSS")
        self.assertEqual(model.track.call_args.kwargs["conf"], 0.1)


if __name__ == "__main__":
    unittest.main()
