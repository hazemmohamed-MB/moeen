"""Velocity tracker, motion magnitude, missing data handling and feature history."""

import pytest

import synthetic as syn
from moeen.config import FeatureConfig
from moeen.features import FeatureExtractor, FeatureHistory
from moeen.features.motion_features import (MotionSample, MotionTracker, VelocityTracker,
                                            regression_slope, rms_spread)
from moeen.features.posture_features import Vec

CFG = FeatureConfig()


def mean_motion(frames, skip=45):
    ex = FeatureExtractor(CFG)
    out = [ex.update(p) for p in frames]
    m = [f.motion_magnitude for f in out[skip:] if f.motion_magnitude is not None]
    return sum(m) / len(m)


# ---------------------------------------------------------------- velocity
def test_regression_slope_exact_and_degenerate():
    assert regression_slope([0, 1, 2], [1, 3, 5]) == pytest.approx(2.0)
    assert regression_slope([0], [1]) is None
    assert regression_slope([1, 1], [0, 5]) is None


def test_velocity_sign_convention():
    down, up = VelocityTracker(0.3, 0.5), VelocityTracker(0.3, 0.5)
    for i in range(10):
        t = i / 30
        v_down = down.update(t, 0.5 + 0.2 * t)    # y grows = moving down the image
        v_up = up.update(t, 0.5 - 0.2 * t)
    assert v_down == pytest.approx(0.2) and v_up == pytest.approx(-0.2)


def test_velocity_restarts_after_gap():
    vt = VelocityTracker(0.3, 0.5)
    for i in range(10):
        vt.update(i / 30, 0.5)
    vt.update(0.4, None)
    assert vt.update(2.0, 0.9) is None   # 1.6 s later: old samples dropped, no fake jump


def test_velocity_ignores_irregular_frame_spacing():
    vt = VelocityTracker(0.3, 0.5)
    ts = [0, 0.02, 0.07, 0.08, 0.15, 0.21, 0.22, 0.29]
    for t in ts:
        v = vt.update(t, 0.3 + 0.5 * t)
    assert v == pytest.approx(0.5)


# ---------------------------------------------------------------- motion magnitude
def test_rms_spread_zero_for_still_points_and_grows_with_movement():
    still = [MotionSample(i / 10, {0: Vec(0.5, 0.5)}) for i in range(5)]
    small = [MotionSample(i / 10, {0: Vec(0.5 + 0.01 * i, 0.5)}) for i in range(5)]
    large = [MotionSample(i / 10, {0: Vec(0.5 + 0.05 * i, 0.5)}) for i in range(5)]
    assert rms_spread(still) == 0 < rms_spread(small) < rms_spread(large)
    assert rms_spread(still[:2]) is None


def test_motion_grows_with_movement_amplitude():
    means = [mean_motion(syn.render(syn.arm_waving(amplitude_deg=a), 5, noise=0.003, seed=2))
             for a in (0, 15, 30, 60, 90)]
    assert all(b > a for a, b in zip(means, means[1:]))


def test_motion_of_still_person_with_jitter_is_far_below_real_movement():
    still = mean_motion(syn.render(syn.standing(5), 5, noise=0.003, seed=3))
    waving = mean_motion(syn.render(syn.arm_waving(amplitude_deg=45), 5, noise=0.003, seed=3))
    assert waving > 3 * still


@pytest.mark.parametrize("fps", [15, 60])
def test_motion_does_not_depend_on_frame_rate(fps):
    ref = mean_motion(syn.render(syn.arm_waving(), 5, 30, noise=0.003), skip=45)
    other = mean_motion(syn.render(syn.arm_waving(), 5, fps, noise=0.003), skip=int(1.5 * fps))
    assert other == pytest.approx(ref, rel=0.15)


def test_motion_is_unavailable_when_pose_mostly_missing():
    # person detected only in short flashes: coverage stays below the configured minimum
    frames = syn.render(syn.standing(4), 4, drop_frames=lambda t: (t % 1.0) > 0.2)
    ex = FeatureExtractor(CFG)
    out = [ex.update(p) for p in frames]
    assert all(f.motion_magnitude is None for f in out)
    assert max(f.motion_coverage for f in out) < CFG.motion_min_coverage


def test_reappearing_elsewhere_is_not_counted_as_motion():
    mt = MotionTracker(1.0, 0.5)
    for i in range(10):
        mt.update(i / 30, {0: Vec(0.2, 0.5)})
    mt.update(0.5, None)
    mag = None
    for i in range(10):
        mag, cov = mt.update(1.5 + i / 30, {0: Vec(0.8, 0.5)})   # 1.2 s gap, new place
    assert mag == pytest.approx(0.0)


# ---------------------------------------------------------------- missing frames
def test_dropped_frames_mid_fall_do_not_break_extraction():
    frames = syn.render(syn.fall(), 6, noise=0.003, drop_frames=lambda t: 2.3 < t < 2.45)
    ex = FeatureExtractor(CFG)
    out = [ex.update(p) for p in frames]
    missing = [f for f in out if not f.pose_present]
    assert missing and all(f.hip_velocity is None for f in missing)
    assert max(f.hip_velocity for f in out if f.hip_velocity is not None) > 1.5


def test_long_absence_does_not_shift_references():
    ex = FeatureExtractor(CFG)
    for p in syn.render(syn.standing(3), 3):
        ex.update(p)
    ref_before = ex.reference.standing_hip_y
    for i in range(100):            # 10 s with nobody in view
        ex.update(syn.PoseFrame(3100 + i * 100, 640, 480, None))
    assert ex.reference.standing_hip_y == ref_before


def test_reset_forgets_everything():
    ex = FeatureExtractor(CFG)
    for p in syn.render(syn.standing(2), 2):
        ex.update(p)
    ex.reset()
    assert ex.reference.torso_length is None and len(ex.history) == 0


# ---------------------------------------------------------------- history
def test_history_keeps_only_configured_window():
    ex = FeatureExtractor(FeatureConfig(history_seconds=2.0))
    for p in syn.render(syn.standing(5), 5):
        ex.update(p)
    span = ex.history.latest.timestamp_ms - next(iter(ex.history)).timestamp_ms
    assert span <= 2000 and len(ex.history) == pytest.approx(61, abs=2)


def test_history_window_values_and_fraction():
    ex = FeatureExtractor(CFG)
    for p in syn.render(syn.fall(), 6):
        ex.update(p)
    h = ex.history
    assert h.fraction(lambda f: f.is_low_or_horizontal, 2.0) == 1.0
    assert h.fraction(lambda f: f.is_upright, 2.0) == 0.0
    assert len(h.window(1.0)) < len(h.window(3.0))
    assert all(v is not None for v in h.values("torso_angle_deg", 2.0))


def test_history_rejects_bad_window():
    with pytest.raises(ValueError):
        FeatureHistory(0)
