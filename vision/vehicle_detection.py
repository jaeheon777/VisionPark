"""YOLO vehicle detection and annotation for the local MP4 pipeline."""

import argparse
import math
from pathlib import Path
import sys

import cv2

from vision.video_input import play_video


VEHICLE_CLASSES = frozenset({"car", "motorcycle", "bus", "truck"})
DEFAULT_MODEL = "yolov8n.pt"


class VehicleDetector:
    """Load one detection model and annotate independent frames."""

    def __init__(self, model=DEFAULT_MODEL, confidence=0.25):
        if not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError("confidence는 0보다 크고 1 이하여야 합니다.")
        self.confidence = confidence
        try:
            from ultralytics import YOLO

            self.model = YOLO(str(model))
            if self.model.task != "detect":
                raise ValueError("객체 탐지(detect) 모델이 필요합니다.")
            self.names = self.model.names
            self.class_ids = [key for key, name in self.names.items() if name in VEHICLE_CLASSES]
            if {self.names[key] for key in self.class_ids} != VEHICLE_CLASSES:
                raise ValueError("car, motorcycle, bus, truck 클래스가 모두 있는 모델이 필요합니다.")
        except Exception as error:
            raise RuntimeError(
                f"YOLO 모델 로딩 실패 ({model}). 의존성, 모델 파일, 다운로드 연결 및 메모리를 확인하세요: {error}"
            ) from error

    def __call__(self, frame):
        try:
            results = self.model.predict(
                source=frame, classes=self.class_ids, conf=self.confidence,
                device="cpu", verbose=False, save=False,
            )
            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue
                for coords, score, class_id in zip(
                    boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), boxes.cls.cpu().tolist()
                ):
                    name = self.names.get(int(class_id))
                    if name not in VEHICLE_CLASSES or score < self.confidence:
                        continue
                    x1, y1, x2, y2 = map(int, coords)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        frame, f"{name} {score:.2f}", (max(0, x1), max(18, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA,
                    )
            return frame
        except Exception as error:
            raise RuntimeError(f"YOLO 차량 탐지 또는 시각화 실패: {error}") from error


def confidence_value(value):
    try:
        confidence = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("confidence는 숫자여야 합니다.") from error
    if not math.isfinite(confidence) or not 0 < confidence <= 1:
        raise argparse.ArgumentTypeError("confidence는 0보다 크고 1 이하여야 합니다.")
    return confidence


def main():
    parser = argparse.ArgumentParser(description="로컬 MP4 영상에서 YOLO로 차량을 탐지합니다.")
    parser.add_argument("video", type=Path, help="MP4 영상 파일 경로")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="YOLO 탐지 모델 파일 (기본: yolov8n.pt)")
    parser.add_argument("--confidence", type=confidence_value, default=0.25, help="최소 confidence (기본: 0.25)")
    args = parser.parse_args()
    return play_video(args.video, processor_factory=lambda: VehicleDetector(args.model, args.confidence))


if __name__ == "__main__":
    sys.exit(main())
