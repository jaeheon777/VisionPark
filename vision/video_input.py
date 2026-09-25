"""Play a local MP4 video in an OpenCV window."""

import argparse
import math
from pathlib import Path
import sys
import time

import cv2


WINDOW_NAME = "VisionPark - Video Input (q: quit)"
DEFAULT_FPS = 30.0


def play_video(path: Path, *, processor_factory=None) -> int:
    """Play frames, optionally processed by a callable from processor_factory.

    Return 0 on completion/user exit and 1 on input or processing failure.
    The factory runs once after validation, outside the playback timer.
    """
    if not path.is_file():
        print(f"오류: 영상 파일이 없거나 일반 파일이 아닙니다: {path}", file=sys.stderr)
        return 1
    if path.suffix.lower() != ".mp4":
        print("오류: 로컬 MP4 파일을 지정해 주세요.", file=sys.stderr)
        return 1

    capture = None
    window_created = False
    try:
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            print(f"오류: 영상을 열 수 없습니다. 파일 손상, 접근 권한 또는 코덱을 확인해 주세요: {path}", file=sys.stderr)
            return 1

        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = DEFAULT_FPS
            print("안내: FPS 정보를 읽을 수 없어 30 FPS로 재생합니다.")

        ok, frame = capture.read()
        if not ok:
            print("오류: 영상에서 프레임을 읽을 수 없습니다. 비어 있거나 손상된 파일인지 확인해 주세요.", file=sys.stderr)
            return 1

        # Initialize optional processing only after validating the video.
        processor = processor_factory() if processor_factory is not None else None
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        window_created = True
        print(f"재생: {path} ({fps:.2f} FPS). 영상 창에서 q를 누르면 종료합니다.")
        deadline = time.perf_counter()
        while True:
            if processor is not None:
                frame = processor(frame)
            cv2.imshow(WINDOW_NAME, frame)
            deadline += 1.0 / fps
            # Poll frequently so even low-FPS videos respond promptly to q.
            while True:
                remaining = deadline - time.perf_counter()
                delay_ms = max(1, min(50, math.ceil(remaining * 1000)))
                if cv2.waitKey(delay_ms) & 0xFF == ord("q"):
                    return 0
                if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    return 0
                if time.perf_counter() >= deadline:
                    break
            ok, frame = capture.read()
            if not ok:
                # OpenCV uses the same result for EOF and a decoding failure.
                print("재생 종료: 더 이상 읽을 수 있는 프레임이 없습니다.")
                return 0
    except cv2.error as error:
        print(f"오류: 영상 처리 또는 OpenCV 창 표시에 실패했습니다: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"오류: 영상 파일에 접근할 수 없습니다: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, ImportError, MemoryError) as error:
        print(f"오류: 영상 처리에 필요한 리소스를 사용할 수 없습니다: {error}", file=sys.stderr)
        return 1
    finally:
        if capture is not None:
            capture.release()
        if window_created:
            cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 MP4 영상을 원본 FPS에 맞춰 재생합니다.")
    parser.add_argument("video", type=Path, help="MP4 영상 파일 경로")
    args = parser.parse_args()
    return play_video(args.video)


if __name__ == "__main__":
    sys.exit(main())
