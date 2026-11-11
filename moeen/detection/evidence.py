"""Pure evidence functions over a time-ordered window of FeatureFrames.

Every function here takes plain sequences and returns numbers, so each rule can be tested
on its own. None of them decide state; the state machine combines them.
"""

from __future__ import annotations

from typing import Callable, Sequence

from moeen.features.models import FeatureFrame, PostureLabel


def down_velocity(f: FeatureFrame) -> float | None:
    """Downward velocity used for fall evidence (torso lengths / s).

    The body center (torso centroid) is preferred, as specified; the hip velocity is the
    fallback when the shoulders are not visible.
    """
    return f.body_center_velocity if f.body_center_velocity is not None else f.hip_velocity


def frame_dt_s(frames: Sequence[FeatureFrame], i: int, max_dt_s: float) -> float:
    """Duration represented by frame ``i`` = time since the previous frame (capped)."""
    if i == 0:
        return 0.0
    return min(max_dt_s, max(0.0, (frames[i].timestamp_ms - frames[i - 1].timestamp_ms) / 1000))


def velocity_evidence(frames: Sequence[FeatureFrame], since_ms: int, threshold: float,
                      max_dt_s: float = 0.2) -> tuple[float | None, float, int | None]:
    """Downward-velocity evidence for frames at or after ``since_ms``.

    Returns (peak velocity, seconds spent above ``threshold``, timestamp of the first frame
    above it). Using accumulated *time* rather than a frame count keeps the rule
    independent of the camera frame rate, and a single spiking frame (dt ~ 33 ms) can
    never satisfy a 100 ms requirement on its own.
    """
    peak: float | None = None
    above_s = 0.0
    first_ms: int | None = None
    for i, f in enumerate(frames):
        if f.timestamp_ms < since_ms:
            continue
        v = down_velocity(f)
        if v is None:
            continue
        peak = v if peak is None else max(peak, v)
        if v >= threshold:
            above_s += frame_dt_s(frames, i, max_dt_s)
            if first_ms is None:
                first_ms = f.timestamp_ms
    return peak, above_s, first_ms


def torso_angle_rise(frames: Sequence[FeatureFrame], rise_after_ms: int) -> float | None:
    """Largest torso-angle increase a_j - a_i with i before j, and j at or after ``rise_after_ms``.

    Only *increases* count (falling over), so getting up (angle decreasing) never produces
    fall evidence. Returns None if fewer than two angles are available.
    """
    running_min: float | None = None
    best: float | None = None
    for f in frames:
        a = f.torso_angle_deg
        if a is None:
            continue
        if running_min is not None and f.timestamp_ms >= rise_after_ms:
            rise = a - running_min
            best = rise if best is None else max(best, rise)
        running_min = a if running_min is None else min(running_min, a)
    return best


def is_abnormal(f: FeatureFrame, pose_loss_counts: bool) -> bool:
    """Low/horizontal posture; optionally 'person not visible' also counts."""
    if not f.pose_present:
        return pose_loss_counts
    return f.is_low_or_horizontal


def fraction(frames: Sequence[FeatureFrame], predicate: Callable[[FeatureFrame], bool]) -> float | None:
    if not frames:
        return None
    return sum(1 for f in frames if predicate(f)) / len(frames)


def mean_motion(frames: Sequence[FeatureFrame]) -> float | None:
    vals = [f.motion_magnitude for f in frames if f.motion_magnitude is not None]
    return sum(vals) / len(vals) if vals else None


def hold_seconds(frames: Sequence[FeatureFrame], predicate: Callable[[FeatureFrame], bool],
                 max_dt_s: float = 0.5) -> float:
    """How long ``predicate`` has been continuously true up to the latest frame (seconds).

    Gaps larger than ``max_dt_s`` between frames break the hold.
    """
    if not frames or not predicate(frames[-1]):
        return 0.0
    start = frames[-1].timestamp_ms
    for i in range(len(frames) - 1, 0, -1):
        prev, cur = frames[i - 1], frames[i]
        if (cur.timestamp_ms - prev.timestamp_ms) / 1000 > max_dt_s or not predicate(prev):
            break
        start = prev.timestamp_ms
    return (frames[-1].timestamp_ms - start) / 1000


def is_upright(f: FeatureFrame) -> bool:
    return f.pose_present and f.posture is PostureLabel.UPRIGHT
