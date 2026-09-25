"""Track YOLO vehicle detections across frames of a local MP4 video."""

import argparse
from pathlib import Path
import sys

import cv2

from vision.vehicle_detection import DEFAULT_MODEL, VEHICLE_CLASSES, VehicleDetector, confidence_value
from vision.video_input import play_video


TRACKING_CONFIDENCE = 0.1


class VehicleTracker(VehicleDetector):
    """Keep one Ultralytics ByteTrack session for the video's successive frames."""

    def __call__(self, frame):
        try:
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
                    if name not in VEHICLE_CLASSES or score < self.confidence:
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
    args = parser.parse_args()
    return play_video(args.video, processor_factory=lambda: VehicleTracker(args.model, args.confidence))


if __name__ == "__main__":
    sys.exit(main())
