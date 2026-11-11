"""Hand-built FeatureFrame sequences for unit-testing the state machine in isolation.

Each helper produces frames at a fixed rate with explicit, readable feature values, so a
test can state exactly what the detector sees (e.g. "velocity 3.0 for 0.2 s, then
horizontal"). These are SYNTHETIC inputs for logic tests only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from moeen.features.models import FeatureFrame, Point, PostureLabel, ScaleSource

FPS = 30.0
DT_MS = 1000.0 / FPS


@dataclass(frozen=True)
class P:
    """A posture preset: torso angle, posture label and low-posture score."""

    angle: float
    label: PostureLabel
    low: float


UPRIGHT = P(3.0, PostureLabel.UPRIGHT, 0.0)
TILTED = P(50.0, PostureLabel.TILTED, 0.3)
LOW = P(15.0, PostureLabel.LOW, 1.0)
HORIZONTAL = P(88.0, PostureLabel.HORIZONTAL, 1.0)


def ff(t_ms: float, p: P = UPRIGHT, v: float | None = 0.0, motion: float | None = 0.02,
       present: bool = True) -> FeatureFrame:
    """One FeatureFrame. ``v`` = downward body-center velocity (torso lengths / s)."""
    t = int(round(t_ms))
    if not present:
        return FeatureFrame(
            timestamp_ms=t, pose_present=False, landmark_quality=0.0, shoulder_center=None,
            hip_center=None, body_center=None, body_center_y=None, torso_angle_deg=None,
            torso_length=None, bbox_aspect=None, scale=0.22, scale_source=ScaleSource.REFERENCE,
            hip_drop=None, body_center_velocity_fh=None, body_center_velocity=None,
            hip_velocity=None, motion_magnitude=None, motion_coverage=0.0, tilt_score=None,
            drop_score=None, low_posture_score=None, upright_score=None,
            posture=PostureLabel.UNKNOWN, is_upright=False, is_low_or_horizontal=False)
    low_or_h = p.label in (PostureLabel.LOW, PostureLabel.HORIZONTAL)
    return FeatureFrame(
        timestamp_ms=t, pose_present=True, landmark_quality=1.0,
        shoulder_center=Point(0.5, 0.3), hip_center=Point(0.5, 0.5), body_center=Point(0.5, 0.4),
        body_center_y=0.4, torso_angle_deg=p.angle, torso_length=0.22, bbox_aspect=0.4,
        scale=0.22, scale_source=ScaleSource.REFERENCE, hip_drop=1.6 if low_or_h else 0.0,
        body_center_velocity_fh=None if v is None else v * 0.22, body_center_velocity=v,
        hip_velocity=v, motion_magnitude=motion, motion_coverage=1.0,
        tilt_score=1.0 if p.label is PostureLabel.HORIZONTAL else 0.0, drop_score=p.low,
        low_posture_score=p.low, upright_score=1.0 - p.low, posture=p.label,
        is_upright=p.label is PostureLabel.UPRIGHT, is_low_or_horizontal=low_or_h)


class Timeline:
    """Builds a frame sequence segment by segment: ``tl.hold(2.0, UPRIGHT)`` etc."""

    def __init__(self, start_ms: float = 0.0) -> None:
        self.t = start_ms
        self.frames: list[FeatureFrame] = []

    def hold(self, seconds: float, p: P = UPRIGHT, v: float | None = 0.0,
             motion: float | None = 0.02, present: bool = True) -> "Timeline":
        n = int(round(seconds * FPS))
        for _ in range(n):
            self.frames.append(ff(self.t, p, v, motion, present))
            self.t += DT_MS
        return self

    def fall(self, seconds: float = 0.3, peak_v: float = 3.5) -> "Timeline":
        """Fast downward motion with the torso rotating from upright to horizontal."""
        n = max(2, int(round(seconds * FPS)))
        for i in range(n):
            u = i / (n - 1)
            angle = UPRIGHT.angle + u * (HORIZONTAL.angle - UPRIGHT.angle)
            label = PostureLabel.UPRIGHT if angle <= 30 else (
                PostureLabel.TILTED if angle < 60 else PostureLabel.HORIZONTAL)
            self.frames.append(ff(self.t, P(angle, label, min(1.0, u * 1.2)), v=peak_v, motion=0.5))
            self.t += DT_MS
        return self

    def __iter__(self) -> Iterator[FeatureFrame]:
        return iter(self.frames)
