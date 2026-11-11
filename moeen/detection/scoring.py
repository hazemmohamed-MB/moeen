"""Rule-based system score in [0, 1].

The score summarizes how strongly the current evidence supports "a fall happened and the
person has not recovered". It is a weighted average of five components, each 0..1:

* velocity     - peak downward velocity relative to 2x the fall threshold
* angle        - torso-angle rise relative to 2x the significant-change threshold
* posture      - low/horizontal evidence (current score early on, lookback share later)
* stillness    - 1 when movement is well below the low-motion threshold, 0 when well above
* persistence  - how far through the recovery window the incident has progressed

It is NOT a medical probability and must not be presented as one.
"""

from __future__ import annotations

from moeen.config import FallDetectionConfig


def ramp(value: float | None, start: float, end: float) -> float:
    if value is None:
        return 0.0
    if end <= start:
        return 1.0 if value >= end else 0.0
    return min(1.0, max(0.0, (value - start) / (end - start)))


def components(cfg: FallDetectionConfig, *, peak_velocity: float | None,
               angle_rise_deg: float | None, posture: float | None,
               motion: float | None, motion_assessed: bool, persistence: float) -> dict[str, float]:
    stillness = 0.0
    if motion_assessed:
        stillness = 1.0 if motion is None else 1.0 - ramp(
            motion, 0.5 * cfg.low_motion_threshold, 2.0 * cfg.low_motion_threshold)
    return {
        "velocity": ramp(peak_velocity, 0.0, 2.0 * cfg.fall_velocity_threshold),
        "angle": ramp(angle_rise_deg, 0.0, 2.0 * cfg.torso_angle_change_deg),
        "posture": min(1.0, max(0.0, posture or 0.0)),
        "stillness": stillness,
        "persistence": min(1.0, max(0.0, persistence)),
    }


def weighted_score(cfg: FallDetectionConfig, comps: dict[str, float]) -> float:
    weights = cfg.weights()
    total = sum(weights.values())
    return sum(weights[k] * comps[k] for k in weights) / total
