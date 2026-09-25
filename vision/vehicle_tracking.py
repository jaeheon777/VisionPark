"""Track YOLO vehicle detections across frames of a local MP4 video."""

import argparse
import math
from pathlib import Path
import sys

import cv2

from vision.vehicle_detection import DEFAULT_MODEL, VEHICLE_CLASSES, VehicleDetector, confidence_value
from vision.line_crossing import LineCrossingDetector, NormalizedLine, bottom_center
from vision.video_input import play_video


TRACKING_CONFIDENCE = 0.1
DEFAULT_LINE_DEAD_ZONE = 0.02


class VehicleTracker(VehicleDetector):
    """Keep one Ultralytics ByteTrack session for the video's successive frames."""

    def __init__(self, model=DEFAULT_MODEL, confidence=0.25, line=None,
                 line_dead_zone=DEFAULT_LINE_DEAD_ZONE):
        super().__init__(model, confidence)
        self.crossing = LineCrossingDetector(line, line_dead_zone) if line is not None else None

    def __call__(self, frame):
        try:
            if self.crossing is not None:
                height, width = frame.shape[:2]
                start, end = self.crossing.line.pixels(width, height)
                cv2.line(frame, tuple(map(round, start)), tuple(map(round, end)), (0, 255, 255), 2)
            results = self.model.track(
                source=frame, classes=self.class_ids,
                conf=TRACKING_CONFIDENCE,
                device="cpu", verbose=False, save=False,
                persist=True, tracker="bytetrack.yaml",
            )
            for result in results:
                boxes = result.boxes
                if boxes is None or boxes.id is None:
                    continue
                for coords, score, class_id, track_id in zip(
                    boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(),
                    boxes.cls.cpu().tolist(), boxes.id.int().cpu().tolist(),
                ):
                    name = self.names.get(int(class_id))
                    if name not in VEHICLE_CLASSES:
                        continue
                    if self.crossing is not None:
                        point = bottom_center(coords)
                        direction = self.crossing.update(int(track_id), point, (width, height))
                        if score >= self.confidence:
                            cv2.circle(frame, tuple(map(round, point)), 4, (255, 0, 255), -1)
                        if direction is not None:
                            print(f"Track ID {track_id}: {direction} CROSS")
                    if score < self.confidence:
                        continue
                    x1, y1, x2, y2 = map(int, coords)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        frame, f"{name} ID {track_id} {score:.2f}",
                        (max(0, x1), max(18, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA,
                    )
            return frame
        except Exception as error:
            raise RuntimeError(f"YOLO vehicle tracking or annotation failed: {error}") from error


def main():
    parser = argparse.ArgumentParser(description="Track vehicles in a local MP4 video with YOLO and ByteTrack")
    parser.add_argument("video", type=Path, help="Path to a local MP4 video")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="YOLO detection model (default: yolov8n.pt)")
    parser.add_argument("--confidence", type=confidence_value, default=0.25,
                        help="Minimum displayed confidence (default: 0.25)")
    parser.add_argument("--line", type=line_value, metavar="X1,Y1,X2,Y2",
                        help="Virtual line endpoints as frame fractions from 0 to 1")
    parser.add_argument("--line-dead-zone", type=dead_zone_value, default=DEFAULT_LINE_DEAD_ZONE,
                        metavar="FRACTION", help="Half-width of crossing dead zone as a fraction of the shorter frame dimension (default: 0.02)")
    args = parser.parse_args()
    return play_video(args.video, processor_factory=lambda: VehicleTracker(
        args.model, args.confidence, args.line, args.line_dead_zone))


def line_value(value):
    try:
        coordinates = [float(part) for part in value.split(",")]
        if len(coordinates) != 4:
            raise ValueError("expected four coordinates")
        return NormalizedLine(*coordinates)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"--line requires X1,Y1,X2,Y2 in [0,1]: {error}") from error


def dead_zone_value(value):
    try:
        fraction = float(value)
        if not math.isfinite(fraction) or not 0 <= fraction < 1:
            raise ValueError("expected a fraction from 0 to less than 1")
        return fraction
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"--line-dead-zone: {error}") from error


if __name__ == "__main__":
    sys.exit(main())
