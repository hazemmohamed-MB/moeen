"""Unit tests of the fall state machine on hand-built feature frames (see feature_builders.py).

Each test states exactly what the detector sees, so every transition rule is checked in
isolation from the feature extractor.
"""

import dataclasses
import json

import pytest

from feature_builders import FPS, HORIZONTAL, LOW, TILTED, UPRIGHT, Timeline, ff
from moeen.config import FallDetectionConfig
from moeen.detection import DetectionState as S
from moeen.detection import AssistanceDetector, Resolution, RiskLevel
from moeen.detection import evidence as ev
from moeen.detection.states import ALLOWED_TRANSITIONS

CFG = FallDetectionConfig()


def run(frames, cfg=CFG, det=None):
    det = det or AssistanceDetector(cfg)
    return det, [det.update(f) for f in frames]


def states(outs):
    return [o.state for o in outs]


def visited(outs):
    return set(states(outs))


def first_time(outs, state):
    return next((o.timestamp_ms / 1000 for o in outs if o.state is state), None)


def fallen(lie_seconds=15.0, **fall_kw):
    """2 s standing, a fast fall, then lying still."""
    return Timeline().hold(2.0).fall(**fall_kw).hold(lie_seconds, HORIZONTAL, v=0.0, motion=0.02)


# ---------------------------------------------------------------- basics
def test_starts_normal_and_stays_normal_when_standing():
    _, outs = run(Timeline().hold(10.0))
    assert visited(outs) == {S.NORMAL}
    assert all(o.risk_level is RiskLevel.NONE and o.score < 0.05 for o in outs)
    assert all(not o.transitions for o in outs)


def test_timestamps_must_not_go_backwards():
    det = AssistanceDetector(CFG)
    det.update(ff(1000))
    det.update(ff(1000))        # equal is fine
    with pytest.raises(ValueError, match="must not decrease"):
        det.update(ff(999))


def test_transition_table_has_no_shortcuts():
    assert S.ALERT not in ALLOWED_TRANSITIONS[S.NORMAL]
    assert S.ALERT not in ALLOWED_TRANSITIONS[S.POSSIBLE_FALL]
    assert ALLOWED_TRANSITIONS[S.ALERT] == {S.RESOLVED}


# ---------------------------------------------------------------- no one-frame decisions
def test_single_extreme_frame_does_not_leave_normal():
    tl = Timeline().hold(2.0)
    tl.frames.append(ff(tl.t, HORIZONTAL, v=50.0, motion=1.0))   # one absurd frame
    tl.t += 1000 / FPS
    tl.hold(5.0)
    _, outs = run(tl)
    assert visited(outs) == {S.NORMAL}


def test_velocity_must_be_sustained_not_a_blip():
    blip = Timeline().hold(2.0).hold(2 / FPS, TILTED, v=3.0).hold(0.4, HORIZONTAL).hold(3.0)
    _, outs = run(blip)                                           # 2 frames = 0.067 s < 0.1 s
    assert S.POSSIBLE_FALL not in visited(outs)
    sustained = Timeline().hold(2.0).hold(5 / FPS, TILTED, v=3.0).hold(0.4, HORIZONTAL).hold(3.0)
    _, outs = run(sustained)
    assert S.POSSIBLE_FALL in visited(outs)


def test_velocity_without_posture_change_is_not_a_candidate():
    _, outs = run(Timeline().hold(2.0).hold(0.5, UPRIGHT, v=4.0).hold(3.0))   # e.g. jumping
    assert visited(outs) == {S.NORMAL}


def test_slow_posture_change_without_fast_motion_is_not_a_fall():
    _, outs = run(Timeline().hold(2.0).hold(1.0, TILTED, v=0.8).hold(20.0, HORIZONTAL, v=0.0))
    # intentional lying down: never the fall path (the lying monitor handles it - Phase 4)
    assert not visited(outs) & {S.POSSIBLE_FALL, S.RECOVERY_WINDOW}
    assert outs[-1].condition is None or outs[-1].condition.value != "FALL"


def test_brief_horizontal_is_not_confirmed():
    # fast + rotation, but horizontal only for 0.2 s (< 0.3 s), then back up
    tl = Timeline().hold(2.0).fall(0.3).hold(0.2, HORIZONTAL).hold(4.0, UPRIGHT)
    _, outs = run(tl)
    assert S.POSSIBLE_FALL in visited(outs) and S.RECOVERY_WINDOW not in visited(outs)
    end = [t for o in outs for t in o.transitions if t.to_state is S.NORMAL][0]
    assert "not confirmed" in end.reason
    assert outs[-1].incident.resolution is Resolution.NOT_CONFIRMED


def test_low_posture_without_torso_rotation_is_not_confirmed():
    # fast drop into a squat: low, but torso stays upright (rise < 35 deg)
    tl = Timeline().hold(2.0).hold(0.3, LOW, v=3.5).hold(1.0, LOW).hold(4.0, UPRIGHT)
    _, outs = run(tl)
    assert S.POSSIBLE_FALL in visited(outs) and S.RECOVERY_WINDOW not in visited(outs)


def test_cancelled_candidate_does_not_immediately_retrigger_on_same_motion():
    tl = Timeline().hold(2.0).hold(0.3, LOW, v=3.5).hold(3.0, LOW)
    _, outs = run(tl)
    assert sum(1 for o in outs for t in o.transitions if t.to_state is S.POSSIBLE_FALL) == 1


# ---------------------------------------------------------------- confirmation and escalation
def test_fall_and_lying_still_escalates_exactly_after_recovery_window():
    _, outs = run(fallen(15.0))
    assert [t.to_state for o in outs for t in o.transitions] == \
        [S.POSSIBLE_FALL, S.RECOVERY_WINDOW, S.ALERT]
    t_conf = first_time(outs, S.RECOVERY_WINDOW)
    t_alert = first_time(outs, S.ALERT)
    assert t_alert - t_conf == pytest.approx(CFG.recovery_window_seconds, abs=1.5 / FPS)
    alert = next(o for o in outs if o.state is S.ALERT)
    assert alert.risk_level is RiskLevel.HIGH and alert.score >= CFG.alert_score_threshold


def test_recovery_cancels_incident_without_alert():
    tl = fallen(4.0).hold(3.0, UPRIGHT, motion=0.2).hold(15.0, UPRIGHT)
    _, outs = run(tl)
    assert S.ALERT not in visited(outs)
    back = [t for o in outs for t in o.transitions if t.from_state is S.RECOVERY_WINDOW][0]
    assert back.to_state is S.NORMAL and "recovered" in back.reason
    assert outs[-1].incident.resolution is Resolution.RECOVERED


def test_recovery_needs_a_continuous_upright_hold():
    # up for 1.0 s (< 1.5 s), down again: the incident must NOT be cancelled
    tl = fallen(3.0).hold(1.0, UPRIGHT).hold(15.0, HORIZONTAL)
    _, outs = run(tl)
    assert S.ALERT in visited(outs)


def test_moving_while_down_is_not_recovery_and_escalates_after_extension():
    tl = Timeline().hold(2.0).fall().hold(35.0, HORIZONTAL, motion=0.3)   # struggling
    _, outs = run(tl)
    t_conf, t_alert = first_time(outs, S.RECOVERY_WINDOW), first_time(outs, S.ALERT)
    expected = CFG.recovery_window_seconds + CFG.max_extension_seconds
    assert t_alert - t_conf == pytest.approx(expected, abs=1.5 / FPS)
    reason = [t for o in outs for t in o.transitions if t.to_state is S.ALERT][0].reason
    assert "still down" in reason


def test_pose_loss_after_fall_counts_as_not_recovered():
    tl = Timeline().hold(2.0).fall().hold(0.5, HORIZONTAL).hold(15.0, present=False)
    _, outs = run(tl)
    assert S.ALERT in visited(outs)
    assert first_time(outs, S.ALERT) - first_time(outs, S.RECOVERY_WINDOW) == \
        pytest.approx(CFG.recovery_window_seconds, abs=1.5 / FPS)


def test_pose_loss_policy_comes_from_config():
    cfg = dataclasses.replace(CFG, pose_loss_counts_as_abnormal=False)
    tl = Timeline().hold(2.0).fall().hold(0.5, HORIZONTAL).hold(35.0, present=False)
    _, outs = run(tl, cfg)
    t_conf, t_alert = first_time(outs, S.RECOVERY_WINDOW), first_time(outs, S.ALERT)
    # no early escalation; only the forced one after the extension
    assert t_alert - t_conf == pytest.approx(cfg.recovery_window_seconds + cfg.max_extension_seconds,
                                             abs=1.5 / FPS)


def test_thresholds_come_from_config():
    strict = dataclasses.replace(CFG, fall_velocity_threshold=5.0)
    _, outs = run(fallen(15.0, peak_v=3.5), strict)
    assert not visited(outs) & {S.POSSIBLE_FALL, S.RECOVERY_WINDOW}
    short = dataclasses.replace(CFG, recovery_window_seconds=4.0, escalation_lookback_seconds=2.0)
    _, outs = run(fallen(15.0), short)
    assert first_time(outs, S.ALERT) - first_time(outs, S.RECOVERY_WINDOW) == \
        pytest.approx(4.0, abs=1.5 / FPS)


# ---------------------------------------------------------------- alert, acknowledge, resolve
def test_alert_resolves_only_after_sustained_upright():
    tl = fallen(13.0).hold(1.0, UPRIGHT).hold(1.0, HORIZONTAL)
    final_upright_starts_s = tl.t / 1000           # the 1.0 s flicker above must NOT resolve
    tl.hold(5.0, UPRIGHT).hold(5.0)
    _, outs = run(tl)
    seq = [t.to_state for o in outs for t in o.transitions]
    assert seq == [S.POSSIBLE_FALL, S.RECOVERY_WINDOW, S.ALERT, S.RESOLVED, S.NORMAL]
    t_res = first_time(outs, S.RESOLVED)
    assert t_res == pytest.approx(final_upright_starts_s + CFG.alert_clear_hold_seconds,
                                  abs=1.5 / FPS)
    assert outs[-1].incident.resolution is Resolution.RECOVERED_AFTER_ALERT
    back = next(o.timestamp_ms / 1000 for o in outs
                if o.state is S.NORMAL and o.timestamp_ms / 1000 > t_res)
    assert back - t_res == pytest.approx(CFG.resolved_hold_seconds, abs=1.5 / FPS)


def test_acknowledge_resolves_alert_with_assistance_recorded():
    det, outs = run(fallen(13.0))
    assert det.state is S.ALERT
    out = det.acknowledge(outs[-1].timestamp_ms + 10)
    assert out.state is S.RESOLVED and out.transitions[0].reason.startswith("assistance")
    assert out.incident.resolution is Resolution.ASSISTANCE_RECORDED
    later = [det.update(f) for f in Timeline(outs[-1].timestamp_ms + 40).hold(4.0, HORIZONTAL)]
    assert later[-1].state is S.NORMAL      # still lying, but no new fall: stays NORMAL
    assert S.ALERT not in visited(later)


def test_acknowledge_when_nothing_to_acknowledge():
    det, _ = run(Timeline().hold(2.0))
    assert det.acknowledge() is None and det.state is S.NORMAL


def test_new_incident_gets_new_id():
    tl = fallen(4.0).hold(4.0, UPRIGHT).hold(3.0).fall().hold(12.0, HORIZONTAL)
    _, outs = run(tl)
    ids = {o.incident.incident_id for o in outs if o.incident}
    assert ids == {1, 2} and outs[-1].state is S.ALERT


# ---------------------------------------------------------------- outputs for the dashboard
def test_timers_count_in_the_right_direction():
    _, outs = run(fallen(15.0))
    rw = [o for o in outs if o.state is S.RECOVERY_WINDOW]
    rem = [o.timers.recovery_remaining_s for o in rw]
    el = [o.timers.recovery_elapsed_s for o in rw]
    assert rem[0] == pytest.approx(CFG.recovery_window_seconds, abs=0.05) and rem[-1] < 0.1
    assert all(b <= a for a, b in zip(rem, rem[1:])) and all(b >= a for a, b in zip(el, el[1:]))
    assert all(o.timers.recovery_hold_required_s == CFG.recovery_hold_seconds for o in rw)
    al = [o.timers.alert_elapsed_s for o in outs if o.state is S.ALERT]
    assert al[0] == 0 and all(b > a for a, b in zip(al, al[1:]))
    pf = [o.timers.confirm_remaining_s for o in outs if o.state is S.POSSIBLE_FALL]
    assert all(0 < r <= CFG.confirm_window_seconds for r in pf)
    assert all(o.timers.recovery_remaining_s is None for o in outs if o.state is S.NORMAL)


def test_score_rises_while_lying_still_and_stays_in_unit_interval():
    _, outs = run(fallen(15.0))
    assert all(0.0 <= o.score <= 1.0 for o in outs)
    assert all(set(o.score_components) == {"velocity", "angle", "posture", "stillness", "persistence"}
               for o in outs)
    rw = [o.score for o in outs if o.state is S.RECOVERY_WINDOW][int(FPS * 3):]  # after lookback fills
    assert all(b >= a - 1e-9 for a, b in zip(rw, rw[1:]))
    normal = max(o.score for o in outs if o.state is S.NORMAL)
    alert = min(o.score for o in outs if o.state is S.ALERT)
    assert alert > normal and alert >= CFG.alert_score_threshold


def test_output_is_json_serializable_and_explains_itself():
    _, outs = run(fallen(13.0))
    for o in (outs[0], next(o for o in outs if o.state_changed), outs[-1]):
        d = json.loads(json.dumps(o.to_dict()))
        assert d["state"] in {s.value for s in S} and isinstance(d["status"], str)
        assert {"evidence", "timers", "score_components", "incident"} <= set(d)
    assert outs[-1].status.startswith("ALERT")
    assert outs[-1].incident.peak_down_velocity == pytest.approx(3.5)
    assert outs[-1].incident.torso_angle_rise_deg > CFG.torso_angle_change_deg


def test_reset_returns_to_initial_state():
    det, _ = run(fallen(13.0))
    det.reset()
    assert det.state is S.NORMAL and det.incident is None and det.last_output is None
    det.update(ff(0))                      # time may restart after reset


# ---------------------------------------------------------------- evidence helpers
def test_velocity_evidence_accumulates_time_not_frames():
    frames = [ff(i * 50, v=3.0 if 2 <= i <= 4 else 0.0) for i in range(8)]   # 20 fps
    peak, above, first = ev.velocity_evidence(frames, since_ms=0, threshold=2.0)
    assert peak == 3.0 and above == pytest.approx(0.15) and first == 100


def test_torso_angle_rise_counts_only_increases():
    up = [ff(i * 33, dataclasses.replace(UPRIGHT, angle=a)) for i, a in enumerate([5, 30, 60, 90])]
    down = [ff(i * 33, dataclasses.replace(UPRIGHT, angle=a)) for i, a in enumerate([90, 60, 30, 5])]
    assert ev.torso_angle_rise(up, 0) == pytest.approx(85)
    assert ev.torso_angle_rise(down, 0) <= 0


def test_hold_seconds_breaks_on_gap_or_predicate():
    frames = [ff(i * 100, HORIZONTAL) for i in range(10)]
    assert ev.hold_seconds(frames, ev.is_upright) == 0.0
    assert ev.hold_seconds(frames, lambda f: f.is_low_or_horizontal) == pytest.approx(0.9)
    gap = frames[:5] + [ff(2000 + i * 100, HORIZONTAL) for i in range(3)]
    assert ev.hold_seconds(gap, lambda f: f.is_low_or_horizontal, max_dt_s=0.5) == pytest.approx(0.2)
