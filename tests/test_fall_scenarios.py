"""End-to-end scenario tests: synthetic pose sequences -> FeatureExtractor -> AssistanceDetector.

The six required scenarios (Phase 3):
  1. normal standing                      -> NORMAL only
  2. sitting (normal and fast)            -> never confirmed
  3. bending (normal and deep/fast)       -> never confirmed
  4. false fall-like motion + recovery    -> POSSIBLE_FALL, then cancelled (not confirmed)
  5. genuine fall + recovery              -> RECOVERY_WINDOW, then cancelled (recovered), no ALERT
  6. genuine fall + persistent low motion -> ALERT after the recovery window

All sequences are deterministic (fixed noise seeds) and SYNTHETIC: they verify the decision
logic end to end, not real-world accuracy (see tests/synthetic.py).
"""

import pytest

import synthetic as syn
from moeen.config import load_config
from moeen.detection import DetectionState as S
from moeen.detection import AssistanceDetector, Resolution
from moeen.features import FeatureExtractor

CFG = load_config()
FD = CFG.fall_detection


def run(fn, duration, fps=30.0, seed=1, noise=0.003, **kw):
    ex, det = FeatureExtractor(CFG.features), AssistanceDetector(FD, CFG.immobility)
    return [det.update(ex.update(p))
            for p in syn.render(fn, duration, fps, noise=noise, seed=seed, **kw)]


def visited(outs):
    return {o.state for o in outs}


def transitions(outs):
    return [t for o in outs for t in o.transitions]


def path(outs):
    return [t.to_state for t in transitions(outs)]


def t_first(outs, state):
    return next((o.timestamp_ms / 1000 for o in outs if o.state is state), None)


# ---------------------------------------------------------------- 1. standing
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_1_normal_standing_never_leaves_normal(seed):
    outs = run(syn.standing(30), 30, seed=seed)
    assert visited(outs) == {S.NORMAL} and not transitions(outs)
    assert max(o.score for o in outs) < 0.2


# ---------------------------------------------------------------- 2. sitting
def test_2_normal_sitting_never_leaves_normal():
    outs = run(syn.sitting(30), 30)
    assert visited(outs) == {S.NORMAL}


def test_2_fast_sitting_is_never_confirmed():
    outs = run(syn.sitting(30, sit_seconds=0.6), 30)
    assert S.RECOVERY_WINDOW not in visited(outs) and S.ALERT not in visited(outs)


# ---------------------------------------------------------------- 3. bending
@pytest.mark.parametrize("depth", [60, 80, 95])
def test_3_bending_never_leaves_normal(depth):
    outs = run(syn.bending(depth_deg=depth), 8)
    assert visited(outs) == {S.NORMAL}


# ---------------------------------------------------------------- 4. false fall-like motion
@pytest.mark.parametrize("scenario", ["fast_squat", "stumble"])
def test_4_false_fall_like_motion_is_cancelled(scenario):
    fn, dur = {"fast_squat": (syn.fast_squat_and_stand(), 10),
               "stumble": (syn.stumble_and_catch(), 8)}[scenario]
    outs = run(fn, dur)
    assert path(outs) == [S.POSSIBLE_FALL, S.NORMAL]          # considered, then rejected
    assert transitions(outs)[-1].reason.startswith("not confirmed")
    assert outs[-1].incident.resolution is Resolution.NOT_CONFIRMED
    assert outs[-1].state is S.NORMAL


# ---------------------------------------------------------------- 5. fall + recovery
@pytest.mark.parametrize("fps", [15, 30])
def test_5_genuine_fall_then_recovery_cancels_without_alert(fps):
    outs = run(syn.fall_then_recover(15), 15, fps=fps)
    assert path(outs) == [S.POSSIBLE_FALL, S.RECOVERY_WINDOW, S.NORMAL]
    cancel = next(o for o in outs if any(t.to_state is S.NORMAL for t in o.transitions))
    assert "recovered" in cancel.transitions[0].reason
    assert cancel.incident.resolution is Resolution.RECOVERED and cancel.incident.alert_ms is None
    elapsed = (cancel.timestamp_ms - cancel.incident.confirmed_ms) / 1000
    assert elapsed < FD.recovery_window_seconds                 # recovered inside the window


# ---------------------------------------------------------------- 6. fall + persistent low movement
@pytest.mark.parametrize("fps", [15, 30])
def test_6_genuine_fall_with_persistent_low_movement_escalates(fps):
    outs = run(syn.fall(40), 40, fps=fps)
    assert path(outs) == [S.POSSIBLE_FALL, S.RECOVERY_WINDOW, S.ALERT]   # no flapping afterwards
    delay = t_first(outs, S.ALERT) - t_first(outs, S.RECOVERY_WINDOW)
    assert delay == pytest.approx(FD.recovery_window_seconds, abs=1.5 / fps)
    alert = next(o for o in outs if o.state is S.ALERT)
    assert alert.score >= FD.alert_score_threshold
    assert "no recovery" in alert.transitions[0].reason
    assert alert.evidence.abnormal_posture_fraction >= FD.abnormal_posture_fraction
    assert alert.evidence.mean_motion <= FD.low_motion_threshold
    assert all(o.state is S.ALERT for o in outs if o.timestamp_ms >= alert.timestamp_ms)


# ---------------------------------------------------------------- robustness across seeds
@pytest.mark.parametrize("seed", range(5))
def test_outcomes_are_stable_across_noise_seeds(seed):
    assert S.ALERT not in visited(run(syn.fall_then_recover(15), 15, seed=seed))
    assert S.ALERT in visited(run(syn.fall(20), 20, seed=seed))
    assert S.RECOVERY_WINDOW not in visited(run(syn.fast_squat_and_stand(), 10, seed=seed))


def test_runs_are_deterministic():
    a = [o.to_dict() for o in run(syn.fall(20), 20)]
    b = [o.to_dict() for o in run(syn.fall(20), 20)]
    assert a == b


# ---------------------------------------------------------------- additional behaviour
def test_intentional_slow_lying_down_does_not_use_the_fall_path():
    # sustained lying without a fall is the separate LYING condition (MONITORING), not a fall
    outs = run(syn.lie_down_slowly(30), 30)
    assert not visited(outs) & {S.POSSIBLE_FALL, S.RECOVERY_WINDOW, S.ALERT}
    assert S.MONITORING in visited(outs)


def test_fall_with_struggling_escalates_only_after_extension():
    outs = run(syn.fall_then_struggle(45), 45)
    delay = t_first(outs, S.ALERT) - t_first(outs, S.RECOVERY_WINDOW)
    assert delay == pytest.approx(FD.recovery_window_seconds + FD.max_extension_seconds, abs=0.1)


def test_alert_then_getting_up_resolves_then_returns_to_normal():
    outs = run(syn.fall_then_recover_late(32, get_up_at=20), 32)
    assert path(outs) == [S.POSSIBLE_FALL, S.RECOVERY_WINDOW, S.ALERT, S.RESOLVED, S.NORMAL]
    assert outs[-1].incident.resolution is Resolution.RECOVERED_AFTER_ALERT


def test_fall_out_of_view_escalates():
    outs = run(syn.fall(30), 30, drop_frames=lambda t: t > 3.5)
    assert S.ALERT in visited(outs)


@pytest.mark.parametrize("glitch_times", [[5.0], [4.0, 6.0, 8.0, 10.0]])
def test_isolated_glitch_frames_never_confirm_a_fall(glitch_times):
    # The pose estimator reports a "lying" skeleton for single frames while the person stands.
    def fn(t):
        return syn.LYING if any(abs(t - g) < 0.5 / 30 for g in glitch_times) else syn.STAND
    outs = run(fn, 14)
    assert S.RECOVERY_WINDOW not in visited(outs) and S.ALERT not in visited(outs)
