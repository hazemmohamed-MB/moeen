"""Single-frame posture geometry (pure functions, no state, no OpenCV/MediaPipe).

All distances here are in frame-height units (x pre-multiplied by width/height); see
``moeen.features.models`` for the conventions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from moeen.config import FeatureConfig
from moeen.features.models import PostureLabel
from moeen.pose import landmark_utils as lu
from moeen.types import Landmark

# Keypoints used for the body bounding box and for motion magnitude (face/hand/foot detail
# points are skipped: they are noisy and add little).
BODY_KEYPOINTS: tuple[int, ...] = (
    lu.NOSE, lu.LEFT_SHOULDER, lu.RIGHT_SHOULDER, lu.LEFT_ELBOW, lu.RIGHT_ELBOW,
    lu.LEFT_WRIST, lu.RIGHT_WRIST, lu.LEFT_HIP, lu.RIGHT_HIP, lu.LEFT_KNEE, lu.RIGHT_KNEE,
    lu.LEFT_ANKLE, lu.RIGHT_ANKLE,
)
TORSO_KEYPOINTS: tuple[int, ...] = (lu.LEFT_SHOULDER, lu.RIGHT_SHOULDER, lu.LEFT_HIP, lu.RIGHT_HIP)


@dataclass(frozen=True)
class Vec:
    """2-D point/vector in frame-height units (x scaled by aspect ratio, y down)."""

    x: float
    y: float

    def __sub__(self, other: "Vec") -> "Vec":
        return Vec(self.x - other.x, self.y - other.y)

    def norm(self) -> float:
        return math.hypot(self.x, self.y)


def is_usable(lm: Landmark | None, cfg: FeatureConfig) -> bool:
    """A landmark is usable if it exists, has finite coordinates and passes both confidences.

    ``None`` visibility/presence values (not reported by the model) are accepted.
    """
    if lm is None or not (math.isfinite(lm.x) and math.isfinite(lm.y)):
        return False
    if lm.visibility is not None and lm.visibility < cfg.min_visibility:
        return False
    if lm.presence is not None and lm.presence < cfg.min_presence:
        return False
    return True


def to_vec(lm: Landmark, aspect: float) -> Vec:
    """Normalized landmark -> frame-height units (aspect = width / height)."""
    return Vec(lm.x * aspect, lm.y)


def usable_points(landmarks: Sequence[Landmark], indices: Sequence[int], cfg: FeatureConfig,
                  aspect: float) -> dict[int, Vec]:
    return {i: to_vec(landmarks[i], aspect) for i in indices
            if i < len(landmarks) and is_usable(landmarks[i], cfg)}


def pair_center(landmarks: Sequence[Landmark], left: int, right: int, cfg: FeatureConfig,
                aspect: float) -> Vec | None:
    """Midpoint of a left/right landmark pair; falls back to the single usable side; else None."""
    pts = usable_points(landmarks, (left, right), cfg, aspect)
    if not pts:
        return None
    return Vec(sum(p.x for p in pts.values()) / len(pts), sum(p.y for p in pts.values()) / len(pts))


def torso_angle_deg(shoulder_center: Vec, hip_center: Vec) -> float | None:
    """Angle between the hip->shoulder vector and straight up, in degrees [0, 180].

    0 = upright, 90 = horizontal (either side), 180 = upside down.
    Returns None for a degenerate (zero-length) torso.
    """
    v = shoulder_center - hip_center
    if v.norm() < 1e-6:
        return None
    # "up" in image coordinates is -y
    return math.degrees(math.atan2(abs(v.x), -v.y))


def bbox_aspect(points: Sequence[Vec]) -> float | None:
    """Width/height of the bounding box of ``points``; None with fewer than 4 points."""
    if len(points) < 4:
        return None
    xs, ys = [p.x for p in points], [p.y for p in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if h < 1e-6:
        return float("inf") if w > 1e-6 else None
    return w / h


def ramp(value: float, start: float, end: float) -> float:
    """Linear 0->1 ramp between ``start`` and ``end`` (clamped)."""
    if end == start:
        return 1.0 if value >= end else 0.0
    return min(1.0, max(0.0, (value - start) / (end - start)))


@dataclass(frozen=True)
class PostureIndicators:
    tilt_score: float | None
    drop_score: float | None
    low_posture_score: float | None
    upright_score: float | None
    label: PostureLabel

    @property
    def is_upright(self) -> bool:
        return self.label is PostureLabel.UPRIGHT

    @property
    def is_low_or_horizontal(self) -> bool:
        return self.label in (PostureLabel.LOW, PostureLabel.HORIZONTAL)


def posture_indicators(angle: float | None, hip_drop: float | None, aspect: float | None,
                       cfg: FeatureConfig) -> PostureIndicators:
    """Combine torso angle, hip drop and body shape into scores and a coarse label.

    Logic (all thresholds from config):

    * HORIZONTAL - torso beyond ``horizontal_min_angle_deg`` (or a wide body box while the
      torso is not upright) AND hips dropped at least ``lying_min_hip_drop`` (if a standing
      reference exists). The hip condition separates lying from a deep forward bend.
    * LOW        - hips at least ``low_hip_drop`` torso lengths below standing height.
    * UPRIGHT    - torso within ``upright_max_angle_deg`` of vertical.
    * TILTED     - anything in between (bending, getting up, sitting down).
    """
    if angle is None:
        return PostureIndicators(None, None, None, None, PostureLabel.UNKNOWN)

    tilt = ramp(angle, cfg.upright_max_angle_deg, cfg.horizontal_min_angle_deg)
    if aspect is not None and angle > cfg.upright_max_angle_deg:
        tilt = max(tilt, ramp(aspect, 1.0, cfg.horizontal_min_aspect))
    # Hip drops up to normal_hip_drop are ordinary variation (score 0); low_hip_drop scores 1.
    # Sitting on a chair (~0.9 torso lengths) therefore lands in the middle, not at "low".
    drop = None if hip_drop is None else ramp(hip_drop, cfg.normal_hip_drop, cfg.low_hip_drop)
    hips_low_enough = 1.0 if hip_drop is None else ramp(hip_drop, 0.0, cfg.lying_min_hip_drop)

    low_score = max(min(tilt, hips_low_enough), drop or 0.0)
    upright_score = (1.0 - tilt) * (1.0 - (drop or 0.0))

    horizontal_shape = angle >= cfg.horizontal_min_angle_deg or (
        aspect is not None and aspect >= cfg.horizontal_min_aspect
        and angle > cfg.upright_max_angle_deg)
    if horizontal_shape and (hip_drop is None or hip_drop >= cfg.lying_min_hip_drop):
        label = PostureLabel.HORIZONTAL
    elif hip_drop is not None and hip_drop >= cfg.low_hip_drop:
        label = PostureLabel.LOW
    elif angle <= cfg.upright_max_angle_deg:
        label = PostureLabel.UPRIGHT
    else:
        label = PostureLabel.TILTED
    return PostureIndicators(tilt, drop, low_score, upright_score, label)
