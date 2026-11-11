"""Tests for the MediaPipe adapter.

Conversion tests use MediaPipe's own result container classes from the installed package.
Model-loading error paths call the real MediaPipe loader. Real inference on camera images
is covered by scripts/selftest.py and the live preview, which need the downloaded model.
"""

import numpy as np
import pytest
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark

from fakes import make_fake_bundle
from moeen.config import PoseConfig
from moeen.pose.models import MODELS, model_path, validate_model_file
from moeen.pose.pose_estimator import (MediaPipePoseEstimator, ModelNotFoundError,
                                       PoseEstimatorError, check_mediapipe_api, convert_result)


def make_result(n_people: int = 1) -> vision.PoseLandmarkerResult:
    people = [[NormalizedLandmark(x=i / 33, y=1 - i / 33, z=-0.1, visibility=0.95, presence=0.9)
               for i in range(33)] for _ in range(n_people)]
    return vision.PoseLandmarkerResult(pose_landmarks=people, pose_world_landmarks=[],
                                       segmentation_masks=None)


def test_installed_mediapipe_has_expected_tasks_api():
    assert check_mediapipe_api() == []


def test_convert_result_keeps_first_person():
    frame = convert_result(make_result(2), timestamp_ms=123, width=640, height=480)
    assert frame.has_pose
    assert len(frame.landmarks) == 33
    assert (frame.timestamp_ms, frame.image_width, frame.image_height) == (123, 640, 480)
    lm = frame.landmarks[3]
    assert lm.x == pytest.approx(3 / 33) and lm.y == pytest.approx(1 - 3 / 33)
    assert lm.visibility == pytest.approx(0.95) and lm.presence == pytest.approx(0.9)


def test_convert_empty_result_means_no_person():
    empty = vision.PoseLandmarkerResult(pose_landmarks=[], pose_world_landmarks=[],
                                        segmentation_masks=None)
    frame = convert_result(empty, 5, 640, 480)
    assert not frame.has_pose and frame.landmarks is None


def test_missing_model_gives_download_instructions(tmp_path):
    cfg = PoseConfig(model_dir=str(tmp_path), model_variant="lite")
    with pytest.raises(ModelNotFoundError) as err:
        MediaPipePoseEstimator(cfg)
    assert "scripts/download_model.py --variant lite" in str(err.value)
    assert MODELS["lite"].url in str(err.value)


def test_non_zip_model_rejected(tmp_path):
    (tmp_path / MODELS["full"].filename).write_bytes(b"html error page")
    assert validate_model_file(model_path(tmp_path, "full"))
    with pytest.raises(ModelNotFoundError, match="not a valid .task bundle"):
        MediaPipePoseEstimator(PoseConfig(model_dir=str(tmp_path)))


def test_corrupt_bundle_is_reported_by_real_mediapipe_loader(tmp_path):
    make_fake_bundle(model_path(tmp_path, "full"))
    with pytest.raises(PoseEstimatorError, match="MediaPipe failed to load"):
        MediaPipePoseEstimator(PoseConfig(model_dir=str(tmp_path)))


class RecordingLandmarker:
    """Stands in for the loaded model; records what the adapter sends to MediaPipe."""

    def __init__(self):
        self.images, self.timestamps, self.closed = [], [], False

    def detect_for_video(self, image, timestamp_ms):
        self.images.append(image.numpy_view().copy())
        self.timestamps.append(timestamp_ms)
        return make_result()

    def close(self):
        self.closed = True


@pytest.fixture
def estimator(tmp_path):
    make_fake_bundle(model_path(tmp_path, "full"))
    seen = {}
    landmarker = RecordingLandmarker()

    def factory(options):
        seen["options"] = options
        return landmarker

    est = MediaPipePoseEstimator(PoseConfig(model_dir=str(tmp_path), num_poses=1,
                                            min_tracking_confidence=0.7),
                                 landmarker_factory=factory)
    return est, landmarker, seen


def test_options_use_video_mode_and_config_values(estimator):
    _, _, seen = estimator
    opts = seen["options"]
    assert opts.running_mode == vision.RunningMode.VIDEO
    assert opts.num_poses == 1
    assert opts.min_tracking_confidence == pytest.approx(0.7)
    assert opts.output_segmentation_masks is False
    assert opts.base_options.model_asset_path.endswith("pose_landmarker_full.task")


def test_frames_are_converted_bgr_to_rgb(estimator):
    est, lmk, _ = estimator
    frame = np.zeros((4, 5, 3), np.uint8)
    frame[..., 0] = 255  # pure blue in BGR
    pose = est.detect(frame, 10)
    assert pose.has_pose and (pose.image_width, pose.image_height) == (5, 4)
    assert tuple(lmk.images[0][0, 0]) == (0, 0, 255)  # blue is last channel in RGB


def test_timestamps_forced_strictly_increasing(estimator):
    est, lmk, _ = estimator
    frame = np.zeros((4, 4, 3), np.uint8)
    for ts in (100, 100, 90, 200):
        est.detect(frame, ts)
    assert lmk.timestamps == [100, 101, 102, 200]


def test_bad_frame_shape_rejected(estimator):
    est, _, _ = estimator
    with pytest.raises(ValueError):
        est.detect(np.zeros((4, 4), np.uint8), 0)


def test_close_releases_landmarker(estimator):
    est, lmk, _ = estimator
    est.close()
    est.close()
    assert lmk.closed
