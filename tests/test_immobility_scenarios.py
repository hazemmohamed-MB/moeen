"""End-to-end lying/immobility scenarios: synthetic pose -> FeatureExtractor -> AssistanceDetector.

Deterministic SYNTHETIC sequences (tests/synthetic.py) at 15 fps with landmark jitter. They
check the decision logic end to end - not real-world accuracy.
"""

import pytest

import synthetic as syn
from moeen.config import load_config
from moeen.detection import AssistanceDetector, Condition, RiskLevel
from moeen.detection import DetectionState as S
from moeen.features import FeatureExtractor

CFG = load_config()
IM = CFG.immobility
FPS = 15.0


def run(fn, duration, fps=FPS, seed=1, **kw):
    ex, det = FeatureExtractor(CFG.features), AssistanceDetector(CFG.fall_detection, IM)
    return [det.update(ex.update(p)) for p in syn.render(fn, duration, fps, noise=0.003, seed=seed, **kw)]


def visited(outs):
    return {o.state for o in outs}


def first(outs, state):
    return next((o for o in outs if o.state is state), None)


def t_of(o):
    return o.timestamp_ms / 1000


# ---------------------------------------------------------------- normal sitting
def test_sitting_still_on_a_chair_is_only_ever_monitored():
    outs = run(syn.sitting(330), 330)
    assert S.ALERT not in visited(outs) and S.POSSIBLE_FALL not in visited(outs)
    mon = first(outs, S.MONITORING)
    assert mon is not None and mon.condition is Condition.IMMOBILITY and mon.risk_level is RiskLevel.LOW


def test_sitting_on_the_floor_and_playing_is_not_an_emergency():
    outs = run(syn.floor_sit_and_play(200), 200)
    assert S.ALERT not in visited(outs)


@pytest.mark.parametrize("depth", [60, 95])
def test_bending_is_not_lying(depth):
    assert visited(run(syn.bending(depth_deg=depth), 8)) == {S.NORMAL}


# ---------------------------------------------------------------- normal lying
def test_lying_down_and_moving_now_and_then_is_monitored_without_alert():
    outs = run(syn.lie_down_and_rest(200, move_every=20), 200)
    assert S.MONITORING in visited(outs) and S.ALERT not in visited(outs)
    assert S.POSSIBLE_FALL not in visited(outs)


def test_lying_down_and_staying_still_gives_a_medium_immobility_alert():
    outs = run(syn.lie_down_and_rest(100), 100)
    alert = first(outs, S.ALERT)
    assert alert.condition is Condition.IMMOBILITY and alert.risk_level is RiskLevel.MEDIUM
    mon = first(outs, S.MONITORING)
    # the alert comes after the configured still-lying duration, never right away
    assert t_of(alert) - t_of(mon) > IM.horizontal_still_alert_seconds - IM.lying_monitor_seconds - 3


def test_brief_slow_lying_never_starts_monitoring():
    brief = syn.keyframes((0, syn.STAND), (2, syn.STAND), (4.5, syn.FLOOR_SIT), (6.5, syn.LYING),
                          (8.5, syn.LYING), (10.0, syn.FLOOR_SIT), (12.0, syn.STAND), (25, syn.STAND))
    outs = run(brief, 25)
    assert S.ALERT not in visited(outs) and S.RECOVERY_WINDOW not in visited(outs)


# ---------------------------------------------------------------- immobility after a fall candidate / fall
def test_staying_down_after_a_fall_candidate_alerts_sooner_and_higher():
    cand = run(syn.drop_low_and_stay(150), 150)
    slow = run(syn.lower_slowly_and_stay(150), 150)
    assert S.POSSIBLE_FALL in visited(cand) and S.POSSIBLE_FALL not in visited(slow)
    a_cand, a_slow = first(cand, S.ALERT), first(slow, S.ALERT)
    assert a_cand.risk_level is RiskLevel.HIGH and a_slow.risk_level is RiskLevel.MEDIUM
    assert a_cand.incident.follows_fall_candidate
    assert t_of(a_cand) < 0.6 * t_of(a_slow)


def test_long_immobility_after_a_fall_alerts_on_the_fall_path():
    outs = run(syn.fall(40), 40)
    alert = first(outs, S.ALERT)
    assert alert.condition is Condition.FALL and alert.risk_level is RiskLevel.HIGH
    assert S.MONITORING not in visited(outs)


# ---------------------------------------------------------------- recovery
def test_fall_then_recovery_returns_to_normal_without_monitoring():
    outs = run(syn.fall_then_recover(30), 30)
    assert S.ALERT not in visited(outs) and S.MONITORING not in visited(outs)
    assert outs[-1].state is S.NORMAL


def test_lying_still_alert_then_getting_up_resolves():
    get_up = 90.0
    fn = syn.keyframes((0, syn.STAND), (2, syn.STAND), (4.5, syn.FLOOR_SIT), (7, syn.LYING),
                       (get_up, syn.LYING), (get_up + 1.5, syn.FLOOR_SIT), (get_up + 3.5, syn.STAND),
                       (get_up + 15, syn.STAND))
    outs = run(fn, get_up + 15)
    path = [t.to_state for o in outs for t in o.transitions]
    assert path == [S.MONITORING, S.ALERT, S.RESOLVED, S.NORMAL]
