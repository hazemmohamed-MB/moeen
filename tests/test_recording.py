"""Pose recording round-trip and the replay_features script (no camera needed)."""

import importlib.util
import json
from pathlib import Path

import pytest

import synthetic as syn
from moeen.pose.recording import PoseRecorder, RecordingError, load_recording
from moeen.types import PoseFrame

ROOT = Path(__file__).resolve().parent.parent


def test_round_trip_preserves_frames(tmp_path):
    frames = syn.render(syn.fall(), 1.0, noise=0.003, drop_frames=lambda t: 0.4 < t < 0.5)
    path = tmp_path / "rec.jsonl"
    with PoseRecorder(path, {"label": "unit test"}) as rec:
        for f in frames:
            rec.write(f)
    header, loaded = load_recording(path)
    assert header["label"] == "unit test" and header["format"] == 1
    assert len(loaded) == len(frames) == rec.frames_written
    for a, b in zip(frames, loaded):
        assert (a.timestamp_ms, a.image_width, a.has_pose) == (b.timestamp_ms, b.image_width, b.has_pose)
        if a.has_pose:
            assert b.landmarks[11].x == pytest.approx(a.landmarks[11].x, abs=1e-5)
            assert b.landmarks[11].visibility == pytest.approx(a.landmarks[11].visibility, abs=1e-5)


@pytest.mark.parametrize("content, msg", [
    ("", "empty"),
    ('{"t": 0, "w": 1, "h": 1, "lm": null}\n', "first line must be a header"),
    ('{"type": "header", "format": 99}\n', "unsupported format"),
    ('{"type": "header", "format": 1}\nnot json\n', "invalid JSON"),
    ('{"type": "header", "format": 1}\n{"w": 1}\n', "bad frame record"),
])
def test_malformed_recordings_rejected(tmp_path, content, msg):
    p = tmp_path / "bad.jsonl"
    p.write_text(content)
    with pytest.raises(RecordingError, match=msg):
        load_recording(p)


def test_missing_recording(tmp_path):
    with pytest.raises(RecordingError, match="not found"):
        load_recording(tmp_path / "nope.jsonl")


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_replay_features_script_summarizes_and_writes_csv(tmp_path, monkeypatch, capsys):
    path = tmp_path / "fall.jsonl"
    with PoseRecorder(path, {"label": "synthetic fall"}) as rec:
        for f in syn.render(syn.fall(), 5, noise=0.003):
            rec.write(f)
    out_csv = tmp_path / "fall.csv"
    replay = _load_script("replay_features")
    monkeypatch.setattr("sys.argv", ["replay_features.py", str(path), "--csv", str(out_csv)])
    assert replay.main() == 0
    text = capsys.readouterr().out
    assert "synthetic fall" in text and "HORIZONTAL" in text and "max down" in text
    lines = out_csv.read_text().splitlines()
    assert len(lines) == 1 + 151
    assert "hip_velocity" in lines[0] and "posture" in lines[0]


def test_recording_module_is_pure():
    src = (ROOT / "moeen/pose/recording.py").read_text()
    assert "import cv2" not in src and "mediapipe" not in src.split('"""', 2)[2]


def test_replay_detection_script_reports_transitions(tmp_path, monkeypatch, capsys):
    path = tmp_path / "fall.jsonl"
    with PoseRecorder(path, {"label": "synthetic fall, stays down"}) as rec:
        for f in syn.render(syn.fall(16), 16, noise=0.003):
            rec.write(f)
    out_csv = tmp_path / "states.csv"
    replay = _load_script("replay_detection")
    monkeypatch.setattr("sys.argv", ["replay_detection.py", str(path), "--csv", str(out_csv)])
    assert replay.main() == 0
    text = capsys.readouterr().out
    for s in ("POSSIBLE_FALL", "RECOVERY_WINDOW", "ALERT", "alerts: 1 (FALL/HIGH)"):
        assert s in text
    rows = out_csv.read_text().splitlines()
    assert rows[0].startswith("t_s,state,condition,risk,score") and len(rows) == 1 + 481
