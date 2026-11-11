"""EventRecorder: detector incidents -> stored events (detector itself never touches the DB)."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

import moeen.app as app
import moeen.pose.pose_estimator as pe
import synthetic as syn
from fakes import FakeCapture, SequenceEstimator, factory_for
from feature_builders import FPS, HORIZONTAL, LOW, UPRIGHT, Timeline
from moeen.alerts import EventRecorder
from moeen.camera.webcam import Webcam
from moeen.config import load_config
from moeen.database import Database, EventRepository, EventStatus, EventType, Severity
from moeen.detection import AssistanceDetector

CFG = load_config()
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path):
    return EventRepository(Database(tmp_path / "events.db"))


def drive(repo, frames, ack_at_end=False, session="test"):
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    rec = EventRecorder(repo, session_id=session)
    for f in frames:
        rec.handle(det.update(f))
    if ack_at_end:
        out = det.acknowledge()
        if out is not None:
            rec.handle(out)
    return det, rec


def statuses(repo, event_id):
    return [h.to_status.value for h in repo.status_history(event_id)]


def test_fall_then_lying_still_creates_one_alert_event(repo):
    _, rec = drive(repo, Timeline().hold(2.0).fall().hold(15.0, HORIZONTAL, motion=0.02))
    (e,) = repo.list_events()
    assert e.event_type is EventType.FALL and e.severity is Severity.HIGH and e.status is EventStatus.NEW
    assert statuses(repo, e.id) == ["MONITORING", "NEW"]
    assert e.session_id == "test" and e.incident_id == 1
    assert e.duration_seconds == pytest.approx(CFG.fall_detection.recovery_window_seconds + 0.3, abs=0.2)
    assert e.score >= CFG.fall_detection.alert_score_threshold
    assert [t["to"] for t in e.details["transitions"]] == ["RECOVERY_WINDOW", "ALERT"]
    assert "evidence_at_alert" in e.details and rec.errors == 0


def test_fall_then_recovery_is_stored_as_resolved(repo):
    drive(repo, Timeline().hold(2.0).fall().hold(4.0, HORIZONTAL).hold(4.0, UPRIGHT))
    (e,) = repo.list_events()
    assert e.status is EventStatus.RESOLVED and e.resolution == "RECOVERED"
    assert e.severity is Severity.MEDIUM and statuses(repo, e.id) == ["MONITORING", "RESOLVED"]


def test_unconfirmed_candidate_stores_nothing(repo):
    drive(repo, Timeline().hold(2.0).hold(0.3, LOW, v=3.5).hold(1.0, LOW).hold(4.0, UPRIGHT))
    assert repo.count_events() == 0


def test_lying_still_becomes_immobility_and_assistance_is_recorded(repo):
    drive(repo, Timeline().hold(2.0).hold(70.0, HORIZONTAL, motion=0.02), ack_at_end=True)
    (e,) = repo.list_events()
    assert e.event_type is EventType.IMMOBILITY and e.severity is Severity.MEDIUM
    assert e.status is EventStatus.ASSISTANCE_RECORDED and e.resolution == "ASSISTANCE_RECORDED"
    assert statuses(repo, e.id) == ["MONITORING", "NEW", "ASSISTANCE_RECORDED"]


def test_alert_then_recovery_resolves_after_alert(repo):
    drive(repo, Timeline().hold(2.0).hold(70.0, HORIZONTAL, motion=0.02).hold(8.0, UPRIGHT, motion=0.2))
    (e,) = repo.list_events()
    assert e.status is EventStatus.RESOLVED and e.resolution == "RECOVERED_AFTER_ALERT"


def test_monitoring_superseded_by_fall_gives_two_events(repo):
    drive(repo, Timeline().hold(310.0, UPRIGHT, motion=0.02).fall().hold(15.0, HORIZONTAL, motion=0.02))
    newer, older = repo.list_events()
    assert older.event_type is EventType.IMMOBILITY and older.resolution == "SUPERSEDED"
    assert newer.event_type is EventType.FALL and newer.status is EventStatus.NEW


def test_shutdown_closes_monitoring_but_keeps_unanswered_alerts_open(repo):
    _, rec1 = drive(repo, Timeline().hold(2.0).hold(20.0, HORIZONTAL, motion=0.2), session="run1")
    _, rec2 = drive(repo, Timeline().hold(2.0).fall().hold(15.0, HORIZONTAL, motion=0.02), session="run2")
    assert rec1.errors == rec2.errors == 0
    closed = rec1.shutdown() + rec2.shutdown()
    assert len(closed) == 1 and closed[0].resolution == "MONITORING_STOPPED"
    assert [e.status for e in repo.list_events(open_only=True)] == [EventStatus.NEW]


def test_database_failure_never_breaks_detection(repo, monkeypatch, caplog):
    def broken(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(repo, "create_event", broken)
    det, rec = drive(repo, Timeline().hold(2.0).fall().hold(15.0, HORIZONTAL, motion=0.02))
    assert det.state.value == "ALERT"            # detection carried on
    assert rec.errors >= 1 and "Could not store event change" in caplog.text


def test_app_stores_events_from_the_live_loop(tmp_path, monkeypatch):
    poses = syn.render(syn.fall(16), 16, 30.0, noise=0.003)
    est = SequenceEstimator(poses)
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam", lambda cfg: Webcam(cfg, factory_for(FakeCapture(delay=0.0005))))
    db = tmp_path / "live.db"
    assert app.main(["--no-window", "--max-frames", str(len(poses)), "--db-path", str(db), "--port", "0"]) == app.EXIT_OK
    (e,) = EventRepository(Database(db)).list_events()
    assert e.event_type is EventType.FALL and e.status is EventStatus.NEW   # unanswered alert kept


def test_app_no_db_flag_stores_nothing(tmp_path, monkeypatch):
    est = SequenceEstimator(syn.render(syn.fall(16), 16, 30.0))
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam", lambda cfg: Webcam(cfg, factory_for(FakeCapture(delay=0.0005))))
    db = tmp_path / "unused.db"
    assert app.main(["--no-window", "--max-frames", "50", "--no-db", "--db-path", str(db), "--port", "0"]) == app.EXIT_OK
    assert not db.exists()


def test_app_reports_unusable_database(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not sqlite" * 200)
    assert app.main(["--no-window", "--db-path", str(bad)]) == app.EXIT_DATABASE_ERROR


def test_events_cli_lists_and_changes_status(tmp_path, monkeypatch, capsys):
    db = tmp_path / "cli.db"
    repo = EventRepository(Database(db))
    e = repo.create_event("FALL", "HIGH", 0.9)
    spec = importlib.util.spec_from_file_location("events_cli", ROOT / "scripts" / "events.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    for argv, expect in ([["list"], "FALL"], [["show", str(e.id)], "status history"],
                         [["assist", str(e.id), "--note", "ok"], "ASSISTANCE_RECORDED"],
                         [["resolve", str(e.id)], "RESOLVED"]):
        monkeypatch.setattr("sys.argv", ["events.py", *argv, "--db", str(db)])
        assert cli.main() == 0
        assert expect in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["events.py", "resolve", str(e.id), "--db", str(db)])
    assert cli.main() == 2                      # already resolved
