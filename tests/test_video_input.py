"""Pipeline checks without opening desktop windows or requiring test media."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from vision import video_input


class VideoInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="data/videos")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sample.mp4"
        writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (64, 48))
        self.assertTrue(writer.isOpened())
        try:
            for value in (0, 80, 160):
                writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
        finally:
            writer.release()

    def run_player(self, key=-1, fps=None, display_error=False, clock=None, processor_factory=None):
        capture = cv2.VideoCapture(str(self.path))
        self.addCleanup(capture.release)
        wrapped = Mock(wraps=capture)
        if fps is not None:
            wrapped.get.return_value = fps
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(cv2, "VideoCapture", return_value=wrapped))
            stack.enter_context(patch.object(cv2, "namedWindow"))
            show = stack.enter_context(patch.object(cv2, "imshow"))
            if display_error:
                show.side_effect = cv2.error("display failed")
            wait = stack.enter_context(patch.object(cv2, "waitKey", return_value=key))
            stack.enter_context(patch.object(cv2, "getWindowProperty", return_value=1))
            close = stack.enter_context(patch.object(cv2, "destroyAllWindows"))
            stack.enter_context(patch.object(video_input.time, "perf_counter", side_effect=clock or [0, 0, 1, 1, 2, 2, 3]))
            result = video_input.play_video(self.path, processor_factory=processor_factory)
        self.assertFalse(capture.isOpened())
        wrapped.release.assert_called_once()
        close.assert_called_once()
        return result, show.call_count, wait

    def test_actual_mp4_decode_to_end(self):
        result, frames, wait = self.run_player()
        self.assertEqual((result, frames), (0, 3))
        self.assertEqual(wait.call_args_list[0].args, (40,))

    def test_q_releases_resources_early(self):
        result, frames, _ = self.run_player(key=ord("q"))
        self.assertEqual((result, frames), (0, 1))

    def test_processing_time_is_subtracted(self):
        result, _, wait = self.run_player(key=ord("q"), clock=[0, 0.015])
        self.assertEqual(result, 0)
        self.assertEqual(wait.call_args.args, (25,))

    def test_unreadable_first_frame(self):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 25
        capture.read.return_value = (False, None)
        with patch.object(cv2, "VideoCapture", return_value=capture), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(video_input.play_video(self.path), 1)
            self.assertIn("프레임을 읽을 수 없습니다", errors.getvalue())
        capture.release.assert_called_once()

    def test_invalid_fps_falls_back(self):
        for fps in (0, -1, float("nan"), float("inf")):
            with self.subTest(fps=fps):
                result, frames, wait = self.run_player(fps=fps)
                self.assertEqual((result, frames), (0, 3))
                self.assertEqual(wait.call_args_list[0].args, (34,))

    def test_display_error_releases_resources(self):
        result, _, _ = self.run_player(display_error=True)
        self.assertEqual(result, 1)

    def test_invalid_inputs(self):
        broken = self.path.parent / "broken.mp4"
        broken.write_bytes(b"not a video")
        wrong_type = self.path.parent / "video.txt"
        wrong_type.write_text("not a video")
        for path in (self.path.parent / "missing.mp4", self.path.parent, broken, wrong_type):
            with self.subTest(path=path), redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(video_input.play_video(path), 1)
                self.assertIn("오류:", errors.getvalue())

    def test_processor_runs_for_each_decoded_frame(self):
        processor = Mock(side_effect=lambda frame: frame)
        factory = Mock(return_value=processor)
        result, frames, _ = self.run_player(processor_factory=factory)
        self.assertEqual((result, frames, processor.call_count), (0, 3, 3))
        factory.assert_called_once_with()

    def test_inference_time_is_subtracted(self):
        result, _, wait = self.run_player(
            key=ord("q"), clock=[0, 0.025],
            processor_factory=lambda: lambda frame: frame,
        )
        self.assertEqual(result, 0)
        self.assertEqual(wait.call_args.args, (15,))

    def test_slow_inference_still_polls_q(self):
        result, frames, wait = self.run_player(
            key=ord("q"), clock=[0, 1],
            processor_factory=lambda: lambda frame: frame,
        )
        self.assertEqual((result, frames), (0, 1))
        self.assertEqual(wait.call_args.args, (1,))

    def test_inference_failure_cleans_up(self):
        result, frames, _ = self.run_player(
            processor_factory=lambda: Mock(side_effect=RuntimeError("inference failed")),
        )
        self.assertEqual((result, frames), (1, 0))

    def test_model_failure_releases_capture_before_window_creation(self):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 25
        capture.read.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
        with patch.object(cv2, "VideoCapture", return_value=capture), patch.object(cv2, "namedWindow") as window, redirect_stderr(io.StringIO()) as errors:
            result = video_input.play_video(self.path, processor_factory=Mock(side_effect=RuntimeError("YOLO 모델 로딩 실패")))
        self.assertEqual(result, 1)
        self.assertIn("YOLO 모델 로딩 실패", errors.getvalue())
        capture.release.assert_called_once()
        window.assert_not_called()

    def test_invalid_video_does_not_load_model(self):
        factory = Mock()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(video_input.play_video(self.path.parent / "missing.mp4", processor_factory=factory), 1)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
