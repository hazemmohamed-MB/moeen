"""Structured feature objects produced by the feature-extraction layer.

Coordinate conventions
----------------------
* ``Point`` values are **normalized image coordinates**: x in [0, 1] left->right,
  y in [0, 1] top->bottom (same as MediaPipe). They are convenient for drawing.
* Geometric measurements (angles, lengths, speeds) are computed in **frame-height units**,
  where x is first multiplied by ``width / height``. This removes the image aspect-ratio
  distortion, so a 45 degree torso measures 45 degrees on a 4:3 or a 16:9 camera.
* "Torso lengths" divide a frame-height distance by the person's reference torso length
  (shoulder center to hip center), which makes speeds independent of camera distance.
* Vertical velocities are **positive when moving down** the image (towards the floor).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PostureLabel(str, Enum):
    """Coarse posture category derived from torso angle, hip drop and body shape."""

    UPRIGHT = "UPRIGHT"        # torso near vertical, hips not far below standing height
    TILTED = "TILTED"          # torso between upright and horizontal (bending, transitions)
    LOW = "LOW"                # hips far below standing height (crouching, sitting on the floor)
    HORIZONTAL = "HORIZONTAL"  # torso near horizontal and hips low (lying)
    UNKNOWN = "UNKNOWN"        # not enough reliable landmarks


class ScaleSource(str, Enum):
    """Where the body-scale (torso length) used for normalization came from."""

    REFERENCE = "reference"    # smoothed torso length from earlier upright frames (preferred)
    CURRENT = "current"        # this frame's torso length (no reference yet)
    DEFAULT = "default"        # configured fallback (no torso measurable yet)


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class FeatureFrame:
    """All features for one frame. Fields are ``None`` when they cannot be computed safely."""

    timestamp_ms: int
    pose_present: bool
    landmark_quality: float          # fraction of the 4 torso landmarks (shoulders, hips) usable

    # --- geometry (this frame) ---
    shoulder_center: Point | None
    hip_center: Point | None
    body_center: Point | None        # midpoint of shoulder and hip centers (torso centroid)
    body_center_y: float | None      # vertical position, frame heights from the top (0..1)
    torso_angle_deg: float | None    # 0 = upright, 90 = horizontal, 180 = upside down
    torso_length: float | None       # this frame's shoulder-hip distance, frame heights
    bbox_aspect: float | None        # width / height of the visible body keypoints

    # --- body scale ---
    scale: float                     # torso length used to normalize, frame heights
    scale_source: ScaleSource
    hip_drop: float | None           # torso lengths below the standing-height reference (+ = lower)

    # --- temporal ---
    body_center_velocity_fh: float | None  # frame heights / s, + = downward
    body_center_velocity: float | None     # torso lengths / s, + = downward
    hip_velocity: float | None             # torso lengths / s, + = downward
    motion_magnitude: float | None   # RMS keypoint displacement within the motion window, torso lengths
    motion_coverage: float           # fraction of the motion window covered by pose data (0..1)

    # --- posture indicators ---
    tilt_score: float | None         # 0 = torso upright .. 1 = torso horizontal
    drop_score: float | None         # 0 = hips at standing height .. 1 = hips at "low" depth
    low_posture_score: float | None  # 0..1, combined low/horizontal evidence
    upright_score: float | None      # 0..1, combined upright evidence
    posture: PostureLabel
    is_upright: bool
    is_low_or_horizontal: bool

    def to_dict(self) -> dict[str, Any]:
        """Flat, JSON/CSV-friendly representation."""
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Point):
                out[f"{f.name}_x"], out[f"{f.name}_y"] = value.x, value.y
            elif isinstance(value, Enum):
                out[f.name] = value.value
            else:
                out[f.name] = value
        for name in ("shoulder_center", "hip_center", "body_center"):
            out.setdefault(f"{name}_x", None)
            out.setdefault(f"{name}_y", None)
            out.pop(name, None)
        return out
