"""Calibration tooling: scenario observations, the report, the calibrate script, the debug
overlay, and a regression guard for the shipped calibration values.

All sequences here are SIMULATED (stick figure + webcam-like jitter). They check logic and
margins; they are not evidence about real people.
"""

import dataclasses
import sys
from pathlib import Path

import numpy as np
import pytest

import webcam_scenarios as ws
from moeen.calibration import FAIL, PASS, WARN, markdown_report, observe, scenario_for
from moeen.config import load_config
from moeen.detection import AssistanceDetector
from moeen.features import FeatureExtractor
from moeen.pose.debug_overlay import HEADER, debug_lines, draw_debug_panel, evidence_rows
from moeen.pose.recording import PoseRecorder

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate  # noqa: E402

CFG = load_config()
GOOD = ws.Condition(30.0, "near", "good")
HARD = ws.Condition(15.0, "far", "dim")


def run(key, cond=GOOD, seed=1, cfg=CFG, **kw):
    frames, land, variant = ws.render_scenario(key, cond, seed, **kw)
    return observe(frames, cfg, key, variant, landing_s=land)


# ---------------------------------------------------------------- shipped calibration guard
@pytest.mark.parametrize("cond", [GOOD, HARD], ids=lambda c: c.tag)
@pytest.mark.parametrize("key", list(ws.SCENARIO_FNS))
def test_shipped_calibration_meets_every_scenario_rule(key, cond):
    """If a calibration edit breaks one of the 7 demo scenarios, this fails first."""
    speeds = ws.FALL_SPEEDS if key == "fall_still" else (None,)
    for fs in speeds:
        o = run(key, cond, **({"fall_s": fs} if fs else {}))
        assert o.verdict != FAIL, f"{key} [{o.variant}]: {o.reason} ({o.state_path})"


def test_fall_alert_comes_about_one_recovery_window_after_landing():
    o = run("fall_still", fall_s=0.9)
    rw = CFG.fall_detection.recovery_window_seconds
    assert o.verdict == PASS and o.sounds >= 1
    assert rw - 1 <= o.alert_after_landing_s <= rw + 1.5


# ---------------------------------------------------------------- judging
def test_a_fall_that_never_alerts_is_reported_as_fail_with_the_evidence():
    strict = CFG.with_overrides({"fall_detection": {"fall_velocity_threshold": 9.0}})
    o = run("fall_still", cfg=strict, fall_s=0.9)
    assert o.verdict == FAIL and "no fall alert" in o.reason and "peak speed" in o.reason


def test_false_alert_in_a_normal_scenario_is_a_fail():
    # an absurd calibration that calls sitting "low posture" quickly
    loose = CFG.with_overrides({"features": {"low_hip_drop": 0.7},
                                "immobility": {"lying_monitor_seconds": 2.0}})
    o = run("sitting", cfg=loose)
    assert o.verdict == FAIL and "event would be stored" in o.reason


def test_brief_possible_fall_check_is_a_warning_not_a_failure():
    o = run("bending", seed=2)               # fast squat-and-lean pick-up
    assert o.verdict == WARN and o.possible_fall_s > 0 and "MONITORING" not in o.states


@pytest.mark.parametrize("name,key", [
    ("fall_still_01", "fall_still"), ("fall then get up quickly", "fall_recover"),
    ("Walking around", "walking"), ("sit on chair", "sitting"), ("pick up a pen", "bending"),
    ("lie down slowly", "slow_lying"), ("standing", "standing"), ("random", None)])
def test_scenario_from_recording_name(name, key):
    assert scenario_for(name) == key


def test_report_lists_values_summary_and_problems():
    obs = [run("standing"), run("bending", seed=2), run("fall_still", fall_s=0.6)]
    md = markdown_report(obs, CFG, title="T", note="simulated")
    assert "`fall_velocity_threshold` | 2" in md and "| Bending to pick something up |" in md
    assert "## Not passed (1)" in md and "possible-fall check" in md


# ---------------------------------------------------------------- the script on recordings
def record(path, frames, label):
    with PoseRecorder(path, {"label": label, "frame_width": 640, "frame_height": 480}) as rec:
        for f in frames:
            rec.write(f)


def test_calibrate_script_on_recordings(tmp_path, capsys):
    fall, _, _ = ws.render_scenario("fall_still", GOOD, 1, fall_s=0.9)
    sit, _, _ = ws.render_scenario("sitting", GOOD, 1)
    record(tmp_path / "a.jsonl", fall, "fall_still")
    record(tmp_path / "b.jsonl", sit, "sitting on a chair")
    out = tmp_path / "r.md"
    assert calibrate.main([str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl"),
                           "--out", str(out)]) == 0
    text = out.read_text()
    assert "Real recordings" in text and "| Fall + remain still |" in text
    assert "fall_still" in capsys.readouterr().out


def test_calibrate_script_set_and_errors(tmp_path):
    fall, _, _ = ws.render_scenario("fall_still", GOOD, 1, fall_s=0.9)
    record(tmp_path / "f.jsonl", fall, "fall_still")
    # a value that makes the fall undetectable -> FAIL -> exit 1, and it is named in the report
    out = tmp_path / "r.md"
    assert calibrate.main([str(tmp_path / "f.jsonl"), "--set", "fall_velocity_threshold=9",
                           "--out", str(out)]) == 1
    assert "`fall_velocity_threshold=9`" in out.read_text()
    assert calibrate.main([str(tmp_path / "f.jsonl"), "--set", "speed=1"]) == 4
    assert calibrate.main([str(tmp_path / "f.jsonl"), "--set", "fall_velocity_threshold=x"]) == 4


# ---------------------------------------------------------------- debug overlay
def outputs_for(key, **kw):
    frames, land, _ = ws.render_scenario(key, GOOD, 1, **kw)
    ex = FeatureExtractor(CFG.features)
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    return [(f, det.update(f)) for f in (ex.update(p) for p in frames)], land


def test_debug_rows_flip_as_the_evidence_appears():
    seq, land = outputs_for("fall_still", fall_s=0.6)
    standing = evidence_rows(seq[30][1], seq[30][0], CFG)
    assert [r.met for r in standing][:3] == [False, False, False]   # stillness may be met: standing still
    i_fall = next(i for i, (_, o) in enumerate(seq) if o.state.value == "POSSIBLE_FALL")
    during = {r.label: r.met for r in evidence_rows(seq[i_fall][1], seq[i_fall][0], CFG)}
    assert during["fall speed"] and during["torso turn"]
    f, o = seq[-1]                                            # lying still, alert
    last = {r.label: r for r in evidence_rows(o, f, CFG)}
    assert o.state.value == "ALERT"
    assert last["posture"].met and last["stillness"].met and last["score"].met
    assert "HORIZONTAL" in last["posture"].text and "/ 2.00 tl/s" in last["fall speed"].text


def test_debug_panel_is_small():
    seq, _ = outputs_for("fall_still", fall_s=0.6)
    lines = debug_lines(evidence_rows(seq[-1][1], seq[-1][0], CFG))
    assert lines[0] == HEADER and len(lines) == 6
    assert max(len(s) for s in lines) <= 62                    # fits a 640 px frame
    img = np.zeros((480, 640, 3), np.uint8)
    draw_debug_panel(img, lines, origin=(10, 80))
    rows = np.where(img.any(axis=(1, 2)))[0]
    assert rows.min() >= 80 and rows.max() - rows.min() < 150   # under the status box, compact
    assert not img[300:].any()                                  # floor area left clear


def test_render_frame_debug_mode_replaces_feature_lines():
    import moeen.app as app
    seq, _ = outputs_for("fall_still", fall_s=0.6)
    f, o = seq[-1]
    frames, _, _ = ws.render_scenario("fall_still", GOOD, 1, fall_s=0.6)
    pose = frames[-1]
    img = np.full((480, 640, 3), 60, np.uint8)
    normal = app.render_frame(img, pose, CFG.display, 30.0, "info", f, o)
    debug = app.render_frame(img, pose, CFG.display, 30.0, "info", f, o, None,
                             debug_lines(evidence_rows(o, f, CFG)))
    assert (normal != debug).any()
    assert not (debug[330:470, 0:120] != normal[330:470, 0:120]).any()   # bottom-left untouched
