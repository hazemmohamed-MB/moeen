"""Stateful feature extractor: PoseFrame in, FeatureFrame out.

This layer only *measures*. It never decides that something is wrong and never raises an
alert; the temporal detector (Phase 3) consumes the ``FeatureFrame`` stream and history.

It is independent of the webcam, OpenCV and MediaPipe: feed it ``PoseFrame`` objects from
any source (live camera, a recording, or synthetic test sequences).
"""

from __future__ import annotations

import math

from moeen.config import FeatureConfig
from moeen.features.history import FeatureHistory
from moeen.features.models import FeatureFrame, Point, PostureLabel, ScaleSource
from moeen.features.motion_features import MotionTracker, VelocityTracker
from moeen.features.posture_features import (BODY_KEYPOINTS, TORSO_KEYPOINTS, Vec, bbox_aspect,
                                             pair_center, posture_indicators, torso_angle_deg,
                                             usable_points)
from moeen.pose import landmark_utils as lu
from moeen.types import PoseFrame

_MIN_TORSO_LENGTH = 0.02  # frame heights; shorter torsos are treated as unmeasurable


def _ema(old: float, new: float, dt: float, tau: float) -> float:
    alpha = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0
    return old + alpha * (new - old)


class BodyReference:
    """Person-specific references learned from upright frames.

    * ``torso_length`` - smoothed shoulder-hip distance while upright (body-scale unit).
    * ``standing_hip_y`` - hip height while upright. It follows the person upward quickly,
      downward only slowly, and downward only for small drops (``normal_hip_drop``), so
      sitting on a chair for a long time never redefines what "standing" means.
    """

    def __init__(self, cfg: FeatureConfig) -> None:
        self.cfg = cfg
        self.torso_length: float | None = None
        self.standing_hip_y: float | None = None

    def reset(self) -> None:
        self.torso_length = None
        self.standing_hip_y = None

    def update(self, dt: float, torso_length: float, hip_y: float) -> None:
        cfg = self.cfg
        if self.torso_length is None:
            self.torso_length = torso_length
        else:
            self.torso_length = _ema(self.torso_length, torso_length, dt,
                                     cfg.torso_reference_tau_seconds)
        if self.standing_hip_y is None:
            self.standing_hip_y = hip_y
        elif hip_y < self.standing_hip_y:          # person is higher than the reference
            self.standing_hip_y = _ema(self.standing_hip_y, hip_y, dt, cfg.standing_rise_tau_seconds)
        elif (hip_y - self.standing_hip_y) / self.torso_length < cfg.normal_hip_drop:
            self.standing_hip_y = _ema(self.standing_hip_y, hip_y, dt, cfg.standing_fall_tau_seconds)
        # else: a deep drop (sitting, crouching) - keep the standing reference unchanged


class FeatureExtractor:
    """Turns a stream of ``PoseFrame`` into ``FeatureFrame`` objects and keeps a history."""

    def __init__(self, config: FeatureConfig) -> None:
        self.cfg = config
        self.reference = BodyReference(config)
        self.history = FeatureHistory(config.history_seconds)
        self._center_velocity = VelocityTracker(config.velocity_window_seconds, config.max_gap_seconds)
        self._hip_velocity = VelocityTracker(config.velocity_window_seconds, config.max_gap_seconds)
        self._motion = MotionTracker(config.motion_window_seconds, config.max_gap_seconds)
        self._last_t: float | None = None
        self._last_scale = config.default_torso_length
        self._last_scale_source = ScaleSource.DEFAULT

    def reset(self) -> None:
        """Forget all references and history (e.g. when a different person appears)."""
        self.reference.reset()
        self.history.clear()
        self._center_velocity.reset()
        self._hip_velocity.reset()
        self._motion.reset()
        self._last_t = None
        self._last_scale = self.cfg.default_torso_length
        self._last_scale_source = ScaleSource.DEFAULT

    # ------------------------------------------------------------------ main entry
    def update(self, pose: PoseFrame) -> FeatureFrame:
        t = pose.timestamp_ms / 1000.0
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        dt = min(dt, self.cfg.max_gap_seconds)  # never let a long gap jump the references
        self._last_t = t

        frame = self._compute(pose, t, dt) if pose.has_pose and pose.image_height > 0 \
            else self._empty(pose, t)
        self.history.append(frame)
        return frame

    # ------------------------------------------------------------------ helpers
    def _empty(self, pose: PoseFrame, t: float) -> FeatureFrame:
        self._center_velocity.update(t, None)
        self._hip_velocity.update(t, None)
        _, coverage = self._motion.update(t, None)
        return FeatureFrame(
            timestamp_ms=pose.timestamp_ms, pose_present=False, landmark_quality=0.0,
            shoulder_center=None, hip_center=None, body_center=None, body_center_y=None,
            torso_angle_deg=None, torso_length=None, bbox_aspect=None,
            scale=self._last_scale, scale_source=self._last_scale_source, hip_drop=None,
            body_center_velocity_fh=None, body_center_velocity=None, hip_velocity=None,
            motion_magnitude=None, motion_coverage=coverage,
            tilt_score=None, drop_score=None, low_posture_score=None, upright_score=None,
            posture=PostureLabel.UNKNOWN, is_upright=False, is_low_or_horizontal=False,
        )

    def _compute(self, pose: PoseFrame, t: float, dt: float) -> FeatureFrame:
        cfg = self.cfg
        assert pose.landmarks is not None
        lms = pose.landmarks
        aspect = pose.image_width / pose.image_height

        torso_pts = usable_points(lms, TORSO_KEYPOINTS, cfg, aspect)
        quality = len(torso_pts) / len(TORSO_KEYPOINTS)
        shoulder = pair_center(lms, lu.LEFT_SHOULDER, lu.RIGHT_SHOULDER, cfg, aspect)
        hip = pair_center(lms, lu.LEFT_HIP, lu.RIGHT_HIP, cfg, aspect)
        # The body center is only defined when BOTH ends of the torso are seen; falling back
        # to one end would make the point jump (and fake a velocity) when landmarks drop out.
        body = Vec((shoulder.x + hip.x) / 2, (shoulder.y + hip.y) / 2) \
            if shoulder is not None and hip is not None else None

        angle = torso_angle_deg(shoulder, hip) if shoulder and hip else None
        torso_len = (shoulder - hip).norm() if shoulder and hip else None
        if torso_len is not None and torso_len < _MIN_TORSO_LENGTH:
            torso_len, angle = None, None
        body_pts = usable_points(lms, BODY_KEYPOINTS, cfg, aspect)
        aspect_ratio = bbox_aspect(list(body_pts.values()))

        # body scale used for normalization
        ref = self.reference
        if ref.torso_length is not None:
            scale, source = ref.torso_length, ScaleSource.REFERENCE
        elif torso_len is not None:
            scale, source = torso_len, ScaleSource.CURRENT
        else:
            scale, source = cfg.default_torso_length, ScaleSource.DEFAULT
        self._last_scale, self._last_scale_source = scale, source

        hip_drop = (hip.y - ref.standing_hip_y) / scale \
            if hip is not None and ref.standing_hip_y is not None else None

        center_v_fh = self._center_velocity.update(t, body.y if body else None)
        hip_v_fh = self._hip_velocity.update(t, hip.y if hip else None)
        motion_fh, coverage = self._motion.update(t, body_pts or None)
        motion = motion_fh / scale if motion_fh is not None and coverage >= cfg.motion_min_coverage \
            else None

        ind = posture_indicators(angle, hip_drop, aspect_ratio, cfg)

        # Learn references only from clean upright frames (all 4 torso landmarks visible).
        if ind.label is PostureLabel.UPRIGHT and quality == 1.0 and torso_len is not None \
                and hip is not None:
            ref.update(dt, torso_len, hip.y)

        def to_point(v: Vec | None) -> Point | None:
            return None if v is None else Point(v.x / aspect, v.y)

        return FeatureFrame(
            timestamp_ms=pose.timestamp_ms, pose_present=True, landmark_quality=quality,
            shoulder_center=to_point(shoulder), hip_center=to_point(hip),
            body_center=to_point(body), body_center_y=body.y if body else None,
            torso_angle_deg=angle, torso_length=torso_len, bbox_aspect=aspect_ratio,
            scale=scale, scale_source=source, hip_drop=hip_drop,
            body_center_velocity_fh=center_v_fh,
            body_center_velocity=None if center_v_fh is None else center_v_fh / scale,
            hip_velocity=None if hip_v_fh is None else hip_v_fh / scale,
            motion_magnitude=motion, motion_coverage=coverage,
            tilt_score=ind.tilt_score, drop_score=ind.drop_score,
            low_posture_score=ind.low_posture_score, upright_score=ind.upright_score,
            posture=ind.label, is_upright=ind.is_upright,
            is_low_or_horizontal=ind.is_low_or_horizontal,
        )
