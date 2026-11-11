"""Unit tests for sustained lying/low-posture and immobility detection (Phase 4).

Hand-built feature frames (tests/feature_builders.py) state exactly what the detector sees:
posture label + motion magnitude. ``STILL`` motion is below the stillness threshold,
``MOVING`` is clearly above it.
"""

import dataclasses
import json

import pytest

from feature_builders import FPS, HORIZONTAL, LOW, TILTED, UPRIGHT, Timeline, ff
from moeen.config import FallDetectionConfig, ImmobilityConfig
from moeen.detection import AssistanceDetector, Condition, Resolution, RiskLevel
from moeen.detection import DetectionState as S
from moeen.detection.immobility_detector import SustainTracker

FALL = FallDetectionConfig()
IM = ImmobilityConfig()
STILL, MOVING = 0.02, 0.20
TOL = 1.5 / FPS


def run(frames, im=IM, det=None):
    det = det or AssistanceDetector(FALL, im)
    return det, [det.update(f) for f in frames]


def visited(outs):
    return {o.state for o in outs}


def first(outs, state):
    return next((o for o in outs if o.state is state), None)


def t_of(o):
    return o.timestamp_ms / 1000


def alerts(outs):
    return [t for o in outs for t in o.transitions if t.to_state is S.ALERT]


# ---------------------------------------------------------------- sustained timers
def test_sustain_tracker_accumulates_and_tolerates_short_blips():
    tr = SustainTracker(tolerance_s=1.0)
    for t in range(0, 5000, 100):                       # 5 s true
        tr.update(t, True)
    assert tr.sustained_s == pytest.approx(4.9)
    tr.update(5500, False)                              # 0.6 s blip: keeps going
    tr.update(5800, True)
    assert tr.sustained_s == pytest.approx(5.8)
    tr.update(7000, None)                               # unknown for > 1 s: ends the run
    assert tr.sustained_s == 0.0
    tr.update(7100, True)
    tr.update(7600, True)
    assert tr.sustained_s == pytest.approx(0.5)


# ---------------------------------------------------------------- normal sitting
def test_sitting_and_moving_never_leaves_normal():
    _, outs = run(Timeline().hold(600.0, UPRIGHT, motion=MOVING))   # chair sitting = UPRIGHT
    assert visited(outs) == {S.NORMAL}


def test_sitting_still_for_minutes_is_not_an_emergency():
    _, outs = run(Timeline().hold(200.0, UPRIGHT, motion=STILL))
    assert visited(outs) == {S.NORMAL}                               # below the monitor time
    _, outs = run(Timeline().hold(400.0, UPRIGHT, motion=STILL).hold(3.0, UPRIGHT, motion=MOVING))
    mon = first(outs, S.MONITORING)
    assert mon.condition is Condition.IMMOBILITY and mon.risk_level is RiskLevel.LOW
    assert t_of(mon) == pytest.approx(IM.upright_still_monitor_seconds, abs=1.0)
    assert S.ALERT not in visited(outs)                              # upright stillness never alerts
    end = [t for o in outs for t in o.transitions if t.from_state is S.MONITORING][0]
    assert end.to_state is S.NORMAL and end.reason == "movement resumed"


def test_upright_stillness_monitor_can_be_disabled():
    im = dataclasses.replace(IM, upright_still_monitor_seconds=0.0)
    _, outs = run(Timeline().hold(400.0, UPRIGHT, motion=STILL), im)
    assert visited(outs) == {S.NORMAL}


def test_sitting_on_the_floor_and_moving_is_only_monitored():
    _, outs = run(Timeline().hold(2.0).hold(600.0, LOW, motion=MOVING))
    assert visited(outs) == {S.NORMAL, S.MONITORING}
    assert all(o.risk_level is RiskLevel.LOW for o in outs if o.state is S.MONITORING)


def test_bending_never_counts_as_lying_or_immobility():
    _, outs = run(Timeline().hold(2.0).hold(250.0, TILTED, motion=STILL).hold(5.0))
    assert visited(outs) == {S.NORMAL}


# ---------------------------------------------------------------- normal lying
def test_intentional_lying_with_movement_is_monitored_long_before_any_alert():
    _, outs = run(Timeline().hold(2.0).hold(320.0, HORIZONTAL, motion=MOVING))
    mon = first(outs, S.MONITORING)
    assert t_of(mon) - 2.0 == pytest.approx(IM.lying_monitor_seconds, abs=TOL)
    alert = first(outs, S.ALERT)
    assert alert.condition is Condition.LYING and alert.risk_level is RiskLevel.MEDIUM
    assert t_of(alert) - 2.0 == pytest.approx(IM.horizontal_alert_seconds, abs=TOL)


def test_lying_still_without_a_fall_raises_a_lower_severity_alert():
    _, outs = run(Timeline().hold(2.0).hold(80.0, HORIZONTAL, motion=STILL))
    alert = first(outs, S.ALERT)
    assert alert.condition is Condition.IMMOBILITY
    assert alert.risk_level is RiskLevel.MEDIUM                      # not HIGH: no fall candidate
    assert t_of(alert) - 2.0 == pytest.approx(IM.horizontal_still_alert_seconds, abs=TOL)
    assert not alert.incident.follows_fall_candidate


def test_clearly_horizontal_escalates_sooner_than_low():
    _, horiz = run(Timeline().hold(2.0).hold(150.0, HORIZONTAL, motion=STILL))
    _, low = run(Timeline().hold(2.0).hold(150.0, LOW, motion=STILL))
    assert t_of(first(horiz, S.ALERT)) < t_of(first(low, S.ALERT))
    assert t_of(first(low, S.ALERT)) - 2.0 == pytest.approx(IM.low_still_alert_seconds, abs=TOL)


# ---------------------------------------------------------------- brief transitions / brief immobility
def test_brief_lying_never_starts_monitoring():
    _, outs = run(Timeline().hold(2.0).hold(4.0, HORIZONTAL, motion=STILL).hold(10.0))
    assert visited(outs) == {S.NORMAL}


def test_brief_lying_still_is_monitored_but_not_alerted_then_recovers():
    _, outs = run(Timeline().hold(2.0).hold(30.0, HORIZONTAL, motion=STILL).hold(5.0, UPRIGHT))
    assert S.MONITORING in visited(outs) and S.ALERT not in visited(outs)
    assert outs[-1].state is S.NORMAL and outs[-1].incident.resolution is Resolution.RECOVERED


def test_brief_immobility_episodes_do_not_add_up():
    tl = Timeline().hold(2.0)
    for _ in range(4):                       # 40 s still, 3 s moving, repeated: never 60 s still
        tl.hold(40.0, HORIZONTAL, motion=STILL).hold(3.0, HORIZONTAL, motion=MOVING)
    _, outs = run(tl)
    assert not alerts(outs)


def test_single_frame_blips_do_not_reset_sustained_timers():
    tl = Timeline().hold(2.0)
    for _ in range(8):                       # a 1-frame posture/motion glitch every 10 s
        tl.hold(10.0, HORIZONTAL, motion=STILL).hold(1 / FPS, TILTED, motion=MOVING)
    _, outs = run(tl)
    alert = first(outs, S.ALERT)
    assert alert is not None
    assert t_of(alert) - 2.0 == pytest.approx(IM.horizontal_still_alert_seconds, abs=0.5)


# ---------------------------------------------------------------- after a fall candidate
def _candidate_then_low_still(seconds):
    """A fast drop into a low posture without torso rotation: a fall candidate that is NOT
    confirmed as a fall. Then the person stays low and does not move."""
    return Timeline().hold(2.0).hold(0.3, LOW, v=3.5, motion=0.5).hold(seconds, LOW, motion=STILL)


def test_immobility_after_a_fall_candidate_escalates_sooner_and_higher():
    _, after_cand = run(_candidate_then_low_still(150.0))
    _, slow = run(Timeline().hold(2.0).hold(150.3, LOW, motion=STILL))
    assert S.POSSIBLE_FALL in visited(after_cand) and S.RECOVERY_WINDOW not in visited(after_cand)
    a1, a2 = first(after_cand, S.ALERT), first(slow, S.ALERT)
    assert a1.incident.follows_fall_candidate and not a2.incident.follows_fall_candidate
    assert a1.risk_level is RiskLevel.HIGH and a2.risk_level is RiskLevel.MEDIUM
    assert t_of(a1) - 2.3 == pytest.approx(IM.low_still_alert_seconds * IM.recent_candidate_factor, abs=1.0)
    assert t_of(a2) - 2.0 == pytest.approx(IM.low_still_alert_seconds, abs=1.0)


def test_long_immobility_after_a_confirmed_fall_uses_the_fall_path():
    tl = Timeline().hold(2.0).fall().hold(30.0, HORIZONTAL, motion=STILL)
    _, outs = run(tl)
    alert = first(outs, S.ALERT)
    assert alert.condition is Condition.FALL and alert.risk_level is RiskLevel.HIGH
    assert S.MONITORING not in visited(outs)


def test_an_old_fall_candidate_does_not_strengthen_a_later_episode():
    tl = Timeline().hold(2.0).hold(0.3, LOW, v=3.5, motion=0.5).hold(3.0, UPRIGHT, motion=MOVING)
    tl.hold(70.0, UPRIGHT, motion=MOVING).hold(80.0, HORIZONTAL, motion=STILL)   # > 60 s later
    _, outs = run(tl)
    alert = first(outs, S.ALERT)
    assert not alert.incident.follows_fall_candidate and alert.risk_level is RiskLevel.MEDIUM


# ---------------------------------------------------------------- recovery
def test_monitoring_ends_when_the_person_stands_up():
    _, outs = run(Timeline().hold(2.0).hold(20.0, HORIZONTAL).hold(3.0, UPRIGHT))
    end = [t for o in outs for t in o.transitions if t.from_state is S.MONITORING][0]
    assert end.to_state is S.NORMAL and end.reason.startswith("recovered")


def test_monitoring_ends_when_posture_is_no_longer_low():
    _, outs = run(Timeline().hold(2.0).hold(20.0, LOW).hold(8.0, TILTED, motion=MOVING))
    end = [t for o in outs for t in o.transitions if t.from_state is S.MONITORING][0]
    assert end.to_state is S.NORMAL and "no longer low" in end.reason


def test_immobility_alert_resolves_after_sustained_upright_then_returns_to_normal():
    tl = Timeline().hold(2.0).hold(70.0, HORIZONTAL, motion=STILL)
    up_at = tl.t / 1000
    tl.hold(8.0, UPRIGHT, motion=MOVING)
    _, outs = run(tl)
    path = [t.to_state for o in outs for t in o.transitions]
    assert path == [S.MONITORING, S.ALERT, S.RESOLVED, S.NORMAL]
    assert t_of(first(outs, S.RESOLVED)) - up_at == pytest.approx(FALL.alert_clear_hold_seconds, abs=TOL)
    assert outs[-1].incident.resolution is Resolution.RECOVERED_AFTER_ALERT


def test_acknowledge_while_still_lying_does_not_re_alert_until_person_is_upright():
    det, outs = run(Timeline().hold(2.0).hold(70.0, HORIZONTAL, motion=STILL))
    assert det.state is S.ALERT
    out = det.acknowledge()
    assert out.state is S.RESOLVED and out.incident.resolution is Resolution.ASSISTANCE_RECORDED
    assert not det.monitors_armed
    t0 = outs[-1].timestamp_ms + 33
    later = [det.update(f) for f in Timeline(t0).hold(150.0, HORIZONTAL, motion=STILL)]
    assert S.MONITORING not in visited(later) and S.ALERT not in visited(later)
    # standing up re-arms the checks; lying down again is monitored again
    t1 = later[-1].timestamp_ms + 33
    again = [det.update(f) for f in Timeline(t1).hold(3.0, UPRIGHT).hold(10.0, HORIZONTAL)]
    assert det.monitors_armed and S.MONITORING in visited(again)


def test_rearm_policy_comes_from_config():
    im = dataclasses.replace(IM, rearm_requires_upright=False)
    det, outs = run(Timeline().hold(2.0).hold(70.0, HORIZONTAL, motion=STILL), im)
    det.acknowledge()
    t0 = outs[-1].timestamp_ms + 33
    later = [det.update(f) for f in Timeline(t0).hold(10.0, HORIZONTAL, motion=STILL)]
    # Without re-arming, the still-running lying timers re-alert as soon as RESOLVED ends
    # (MONITORING and ALERT on the same frame) - which is why re-arming is on by default.
    path = [t.to_state for o in later for t in o.transitions]
    assert path == [S.NORMAL, S.MONITORING, S.ALERT]


def test_acknowledge_during_monitoring():
    det, _ = run(Timeline().hold(2.0).hold(10.0, HORIZONTAL))
    assert det.state is S.MONITORING
    assert det.acknowledge().incident.resolution is Resolution.ASSISTANCE_RECORDED


# ---------------------------------------------------------------- integration with the state model
def test_upright_stillness_turns_into_lying_within_the_same_incident():
    _, outs = run(Timeline().hold(310.0, UPRIGHT, motion=STILL).hold(10.0, HORIZONTAL, motion=STILL))
    mons = [o for o in outs if o.state is S.MONITORING]
    assert mons[0].condition is Condition.IMMOBILITY and mons[-1].condition is Condition.LYING
    assert len({o.incident.incident_id for o in mons}) == 1


def test_a_fall_during_monitoring_supersedes_the_monitoring_incident():
    tl = Timeline().hold(310.0, UPRIGHT, motion=STILL).fall().hold(15.0, HORIZONTAL, motion=STILL)
    _, outs = run(tl)
    path = [t.to_state for o in outs for t in o.transitions]
    assert path[:3] == [S.MONITORING, S.POSSIBLE_FALL, S.RECOVERY_WINDOW]
    assert outs[-1].incident.condition is Condition.FALL and outs[-1].incident.incident_id == 2


def test_person_not_visible_during_monitoring_does_not_escalate():
    _, outs = run(Timeline().hold(2.0).hold(10.0, HORIZONTAL, motion=STILL)
                  .hold(120.0, present=False))
    assert outs[-1].state is S.MONITORING and S.ALERT not in visited(outs)
    assert "not visible" in outs[-1].status


def test_dashboard_fields_for_monitoring():
    _, outs = run(Timeline().hold(2.0).hold(50.0, HORIZONTAL, motion=STILL))
    mon = [o for o in outs if o.state is S.MONITORING]
    esc = [o.timers.escalation_in_s for o in mon]
    assert all(b <= a + 1e-9 for a, b in zip(esc, esc[1:])) and esc[-1] > 0
    assert all(o.timers.monitor_elapsed_s is not None and o.condition is Condition.LYING for o in mon)
    assert mon[-1].evidence.still_sustained_s > 40 and mon[-1].evidence.horizontal_sustained_s > 40
    assert all(0 <= o.score <= 1 for o in outs)
    assert mon[-1].score > mon[0].score
    d = json.loads(json.dumps(mon[-1].to_dict()))
    assert d["condition"] == "LYING" and d["incident"]["condition"] == "LYING"
