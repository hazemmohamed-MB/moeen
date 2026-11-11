"""MediaPipe Pose adapter (Tasks API).

MediaPipe >= 0.10.30 no longer ships the legacy ``mp.solutions.pose`` module. This adapter
uses the current API, verified against the installed package:

    mediapipe.tasks.python.BaseOptions(model_asset_path=...)
    mediapipe.tasks.python.vision.PoseLandmarker / PoseLandmarkerOptions / RunningMode.VIDEO
    PoseLandmarker.detect_for_video(mp.Image, timestamp_ms) -> PoseLandmarkerResult
    PoseLandmarkerResult.pose_landmarks: list[list[NormalizedLandmark]]

VIDEO mode is synchronous and uses temporal tracking between frames; it requires strictly
increasing integer timestamps, which :meth:`MediaPipePoseEstimator.detect` enforces.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from moeen.config import PROJECT_ROOT, PoseConfig
from moeen.pose.models import MODELS, model_path, validate_model_file
from moeen.types import Landmark, PoseFrame

log = logging.getLogger(__name__)


class PoseEstimatorError(RuntimeError):
    """MediaPipe could not be initialised or failed during inference."""


class ModelNotFoundError(PoseEstimatorError):
    """The .task model file is missing or invalid."""


class MediaPipeApiMismatch(PoseEstimatorError):
    """The installed MediaPipe does not expose the Tasks API this adapter relies on."""


# (dotted attribute path relative to the module given) checked by check_mediapipe_api()
_REQUIRED_VISION_ATTRS: tuple[str, ...] = (
    "PoseLandmarker",
    "PoseLandmarker.create_from_options",
    "PoseLandmarker.detect_for_video",
    "PoseLandmarkerOptions",
    "PoseLandmarkerResult",
    "PoseLandmarksConnections.POSE_LANDMARKS",
    "PoseLandmark",
    "RunningMode.VIDEO",
)
_REQUIRED_OPTION_FIELDS: tuple[str, ...] = (
    "base_options", "running_mode", "num_poses", "min_pose_detection_confidence",
    "min_pose_presence_confidence", "min_tracking_confidence", "output_segmentation_masks",
)


def _has_path(obj: Any, dotted: str) -> bool:
    for part in dotted.split("."):
        if not hasattr(obj, part):
            return False
        obj = getattr(obj, part)
    return True


def mediapipe_version() -> str:
    import mediapipe as mp
    return getattr(mp, "__version__", "unknown")


def check_mediapipe_api() -> list[str]:
    """Inspect the installed MediaPipe and list missing pieces of the expected Tasks API.

    Returns an empty list when everything this adapter needs is present.
    """
    problems: list[str] = []
    try:
        import mediapipe as mp
    except ImportError as exc:
        return [f"cannot import mediapipe: {exc}"]
    try:
        from mediapipe.tasks.python import BaseOptions, vision
    except ImportError as exc:
        return [f"cannot import mediapipe.tasks.python (vision / BaseOptions): {exc}"]

    for attr in ("Image", "ImageFormat"):
        if not hasattr(mp, attr):
            problems.append(f"mediapipe.{attr} is missing")
    if hasattr(mp, "ImageFormat") and not hasattr(mp.ImageFormat, "SRGB"):
        problems.append("mediapipe.ImageFormat.SRGB is missing")
    for attr in _REQUIRED_VISION_ATTRS:
        if not _has_path(vision, attr):
            problems.append(f"mediapipe.tasks.python.vision.{attr} is missing")
    if "model_asset_path" not in getattr(BaseOptions, "__dataclass_fields__", {}):
        problems.append("BaseOptions has no 'model_asset_path' field")
    opt_fields = getattr(getattr(vision, "PoseLandmarkerOptions", None), "__dataclass_fields__", {})
    for name in _REQUIRED_OPTION_FIELDS:
        if name not in opt_fields:
            problems.append(f"PoseLandmarkerOptions has no '{name}' field")
    return problems


def convert_result(result: Any, timestamp_ms: int, width: int, height: int) -> PoseFrame:
    """Convert a MediaPipe ``PoseLandmarkerResult`` into a library-independent ``PoseFrame``.

    Only the first detected person is kept (single-person MVP).
    """
    poses = getattr(result, "pose_landmarks", None) or []
    if not poses:
        return PoseFrame(timestamp_ms, width, height, None)
    landmarks = tuple(
        Landmark(
            x=float(lm.x), y=float(lm.y), z=float(lm.z if lm.z is not None else 0.0),
            visibility=None if lm.visibility is None else float(lm.visibility),
            presence=None if lm.presence is None else float(lm.presence),
        )
        for lm in poses[0]
    )
    return PoseFrame(timestamp_ms, width, height, landmarks)


class MediaPipePoseEstimator:
    """``PoseEstimator`` implementation backed by MediaPipe PoseLandmarker (VIDEO mode)."""

    name = "mediapipe-pose-landmarker"

    def __init__(self, config: PoseConfig, project_root: Path = PROJECT_ROOT,
                 landmarker_factory: Callable[[Any], Any] | None = None) -> None:
        """Create the landmarker.

        Args:
            config: pose section of the app config.
            project_root: base for a relative ``model_dir``.
            landmarker_factory: optional replacement for
                ``vision.PoseLandmarker.create_from_options`` (used by unit tests).

        Raises:
            MediaPipeApiMismatch: installed MediaPipe lacks the expected Tasks API.
            ModelNotFoundError: the model file is missing or not a valid bundle.
            PoseEstimatorError: MediaPipe failed to load the model.
        """
        problems = check_mediapipe_api()
        if problems:
            raise MediaPipeApiMismatch(
                f"Installed mediapipe {mediapipe_version()} does not match the expected Tasks "
                "API:\n  - " + "\n  - ".join(problems) +
                "\nInstall the pinned version: pip install -r requirements.txt")

        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self.config = config
        self.model_file = model_path(config.model_dir_path(project_root), config.model_variant)
        issues = validate_model_file(self.model_file)
        if issues:
            raise ModelNotFoundError(
                f"Pose model '{config.model_variant}' is not usable: {'; '.join(issues)}.\n"
                f"Download it with: python scripts/download_model.py --variant {config.model_variant}\n"
                f"(source: {MODELS[config.model_variant].url})")

        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self.model_file)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=config.num_poses,
            min_pose_detection_confidence=config.min_pose_detection_confidence,
            min_pose_presence_confidence=config.min_pose_presence_confidence,
            min_tracking_confidence=config.min_tracking_confidence,
            output_segmentation_masks=False,
        )
        factory = landmarker_factory or vision.PoseLandmarker.create_from_options
        try:
            self._landmarker = factory(options)
        except Exception as exc:
            raise PoseEstimatorError(
                f"MediaPipe failed to load {self.model_file}: {type(exc).__name__}: {exc}") from exc
        self._last_ts: int = -1
        log.info("MediaPipe %s PoseLandmarker ready (model=%s)", mediapipe_version(),
                 self.model_file.name)

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> PoseFrame:
        if frame_bgr is None or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError("frame_bgr must be an H x W x 3 image")
        # VIDEO mode rejects non-increasing timestamps; never send one.
        ts = int(timestamp_ms)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts

        height, width = frame_bgr.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._landmarker.detect_for_video(image, ts)
        except Exception as exc:
            raise PoseEstimatorError(f"Pose inference failed: {type(exc).__name__}: {exc}") from exc
        return convert_result(result, ts, width, height)

    def close(self) -> None:
        landmarker = getattr(self, "_landmarker", None)
        if landmarker is not None:
            landmarker.close()
            self._landmarker = None

    def __enter__(self) -> "MediaPipePoseEstimator":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
