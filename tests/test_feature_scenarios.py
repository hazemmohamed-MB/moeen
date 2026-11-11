"""Behaviour of the features on SYNTHETIC movement sequences (see tests/synthetic.py).

Assertions compare scenarios against each other and check directions/orderings, so they
stay meaningful when thresholds are re-tuned. Absolute numbers only appear where they are
tied to a configured threshold. All sequences include small landmark jitter.
"""

import pytest

import synthetic as syn
from moeen.config import FeatureConfig
from moeen.features import FeatureExtractor, FeatureFrame, PostureLabel

CFG = FeatureConfig()
NOISE = 0.003  # landmark jitter, frame heights


def extract(fn, duration, fps=30.0, noise=NOISE, seed=1, **kw) -> list[FeatureFrame]:
    ex = FeatureExtractor(CFG)
    return [ex.update(p) for p in syn.render(fn, duration, fps, noise=noise, seed=seed, **kw)]


def between(frames, t0, t1):
    return [f for f in frames if t0 <= f.timestamp_ms / 1000 <= t1]


def vals(frames, field):
    return [getattr(f, field) for f in frames if getattr(f, field) is not None]


def peak_down(frames, field="hip_velocity"):
    return max(vals(frames, field))


def labels(frames):
    return {f.posture for f in frames}


@pytest.fixture(scope="module")
def runs():
    return {
        "standing": extract(syn.standing(8), 8),
        "bending": extract(syn.bending(), 8),
        "sitting": extract(syn.sitting(), 12),
        "fall": extract(syn.fall(), 8),
        "lie_down": extract(syn.lie_down_slowly(), 12),
        "recovery": extract(syn.fall_then_recover(), 12),
    }


# ---------------------------------------------------------------- standing
def test_standing_is_upright_and_still(runs):
    fr = between(runs["standing"], 1.0, 8.0)
    assert labels(fr) == {PostureLabel.UPRIGHT}
    assert not any(f.is_low_or_horizontal for f in fr)
    assert max(abs(v) for v in vals(fr, "hip_velocity")) < 0.3 * peak_down(runs["sitting"])
    assert min(vals(fr, "upright_score")) > 0.9
    assert max(abs(d) for d in vals(fr, "hip_drop")) < CFG.normal_hip_drop / 2


# ---------------------------------------------------------------- bending
def test_bending_tilts_torso_but_is_never_low_or_horizontal(runs):
    fr = runs["bending"]
    stand_angle = max(vals(between(fr, 0.5, 2.0), "torso_angle_deg"))
    bend_angle = max(vals(between(fr, 3.0, 4.5), "torso_angle_deg"))
    assert bend_angle > stand_angle + 45
    assert PostureLabel.TILTED in labels(fr)
    assert not any(f.is_low_or_horizontal for f in fr)
    assert max(vals(fr, "hip_drop")) < CFG.lying_min_hip_drop
    assert labels(between(fr, 7.0, 8.0)) == {PostureLabel.UPRIGHT}   # back to standing


def test_bending_moves_shoulders_much_more_than_hips(runs):
    fr = between(runs["bending"], 2.0, 4.5)
    assert peak_down(fr, "body_center_velocity") > 3 * peak_down(fr, "hip_velocity")


# ---------------------------------------------------------------- sitting
def test_sitting_on_chair_lowers_hips_but_stays_upright(runs):
    fr = runs["sitting"]
    seated = between(fr, 4.0, 12.0)
    assert labels(seated) == {PostureLabel.UPRIGHT}
    assert not any(f.is_low_or_horizontal for f in fr)
    standing_drop = sum(vals(between(fr, 1, 2), "hip_drop")) / len(between(fr, 1, 2))
    seated_drop = min(vals(seated, "hip_drop"))
    assert seated_drop > standing_drop + CFG.normal_hip_drop
    assert seated_drop < CFG.low_hip_drop


def test_hip_drop_increases_monotonically_while_sitting_down():
    fr = between(extract(syn.sitting(), 4, noise=0.0), 2.0, 3.4)
    drops = vals(fr[::3], "hip_drop")
    assert all(b >= a - 1e-9 for a, b in zip(drops, drops[1:]))


def test_standing_reference_does_not_drift_while_seated_for_long(runs):
    seated = between(runs["sitting"], 4.0, 12.0)
    early, late = seated[0].hip_drop, seated[-1].hip_drop
    assert late == pytest.approx(early, abs=0.05)


# ---------------------------------------------------------------- rapid downward movement
def test_fall_velocity_is_downward_and_much_larger_than_sitting(runs):
    fall_peak = peak_down(between(runs["fall"], 2.0, 3.0))
    assert fall_peak > 0                                   # + = downward
    assert fall_peak > 2.5 * peak_down(runs["sitting"])
    assert fall_peak > 2.5 * peak_down(runs["lie_down"])   # controlled lying down is slower
    assert fall_peak > 5 * peak_down(runs["bending"])


def test_fall_velocity_is_independent_of_camera_distance():
    near = peak_down(extract(syn.fall(), 4))
    far = peak_down(extract(syn.scaled(syn.fall(), 0.6), 4))
    assert far == pytest.approx(near, rel=0.15)
    # ...whereas the frame-normalized velocity scales with the person's size in the image
    near_fh = peak_down(extract(syn.fall(), 4), "body_center_velocity_fh")
    far_fh = peak_down(extract(syn.scaled(syn.fall(), 0.6), 4), "body_center_velocity_fh")
    assert far_fh == pytest.approx(0.6 * near_fh, rel=0.15)


@pytest.mark.parametrize("fps", [15, 24, 60])
def test_fall_velocity_is_consistent_across_frame_rates(fps):
    ref = peak_down(extract(syn.fall(), 4, fps=30))
    assert peak_down(extract(syn.fall(), 4, fps=fps)) == pytest.approx(ref, rel=0.2)


def test_faster_falls_give_larger_velocity():
    peaks = [peak_down(extract(syn.fall(fall_seconds=s), 5)) for s in (1.5, 1.0, 0.7, 0.5)]
    assert all(b > a for a, b in zip(peaks, peaks[1:]))


def test_fall_turns_posture_horizontal_and_low_score_rises(runs):
    fr = runs["fall"]
    assert labels(between(fr, 0.5, 2.0)) == {PostureLabel.UPRIGHT}
    after = between(fr, 3.0, 8.0)
    assert labels(after) == {PostureLabel.HORIZONTAL}
    assert all(f.is_low_or_horizontal for f in after)
    coarse = vals(between(fr, 1.9, 3.0)[::3], "low_posture_score")
    assert all(b >= a - 0.02 for a, b in zip(coarse, coarse[1:]))
    assert coarse[0] < 0.1 and coarse[-1] > 0.9
    angles = vals(between(fr, 1.9, 3.0)[::3], "torso_angle_deg")
    assert angles[-1] > angles[0] + 60


# ---------------------------------------------------------------- lying
def test_lying_still_is_horizontal_with_low_motion(runs):
    lying = between(runs["fall"], 5.0, 8.0)
    moving = between(runs["fall"], 2.0, 3.0)
    assert labels(lying) == {PostureLabel.HORIZONTAL}
    assert max(vals(lying, "motion_magnitude")) < 0.25 * max(vals(moving, "motion_magnitude"))
    assert min(vals(lying, "hip_drop")) > CFG.low_hip_drop


def test_lying_when_first_seen_is_horizontal_without_reference():
    fr = extract(syn.lying_only(), 3)
    assert labels(fr[1:]) == {PostureLabel.HORIZONTAL}
    assert all(f.hip_drop is None for f in fr)       # no standing reference was ever seen


def test_intentional_lying_down_passes_through_low_then_horizontal(runs):
    seq = [f.posture for f in runs["lie_down"]]
    first = {lab: seq.index(lab) for lab in (PostureLabel.LOW, PostureLabel.HORIZONTAL)}
    assert first[PostureLabel.LOW] < first[PostureLabel.HORIZONTAL]
    assert labels(between(runs["lie_down"], 8, 12)) == {PostureLabel.HORIZONTAL}


# ---------------------------------------------------------------- recovery
def test_recovery_moves_up_and_returns_to_upright(runs):
    fr = runs["recovery"]
    getting_up = between(fr, 6.0, 8.7)
    assert min(vals(getting_up, "hip_velocity")) < -0.5          # negative = upward
    assert labels(between(fr, 3.5, 6.0)) == {PostureLabel.HORIZONTAL}
    assert labels(between(fr, 9.5, 12.0)) == {PostureLabel.UPRIGHT}
    low_lying = sum(vals(between(fr, 4, 6), "low_posture_score")) / len(between(fr, 4, 6))
    low_after = sum(vals(between(fr, 10, 12), "low_posture_score")) / len(between(fr, 10, 12))
    assert low_after < 0.1 < 0.9 < low_lying
    assert abs(fr[-1].hip_drop) < CFG.normal_hip_drop / 2        # standing reference still valid


# ---------------------------------------------------------------- no alerting
def test_feature_frames_carry_no_alert_or_state_fields(runs):
    names = set(runs["fall"][-1].to_dict())
    assert not {n for n in names if "alert" in n or "state" in n or "severity" in n}
