"""Flask API tested on its own: no camera, no processing loop (except a stand-in thread
that drains commands like the real loop does)."""

import json
import re
import threading
import time
import urllib.request

import pytest

from feature_builders import HORIZONTAL, Timeline
from moeen.alerts import EventRecorder
from moeen.api import DashboardError, DashboardServer, create_app
from moeen.config import load_config
from moeen.database import Database, EventRepository
from moeen.detection import AssistanceDetector, DetectionState
from moeen.runtime import Command, StatusStore
from moeen.runtime.commands import apply_command
from moeen.runtime.snapshot import build_snapshot

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
CFG = load_config().with_overrides({"dashboard": {"command_timeout_seconds": 0.5,
                                                  "stale_after_seconds": 3.0}})
JSON = {"Content-Type": "application/json"}


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def repo(tmp_path):
    return EventRepository(Database(tmp_path / "api.db"))


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    return StatusStore(clock=clock)


@pytest.fixture
def client(repo, store):
    return create_app(CFG, store, repo).test_client()


def fallen_detector(repo, seconds=15.0):
    """A real detector + recorder that has just raised a FALL alert (synthetic frames)."""
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    rec = EventRecorder(repo, session_id="api-test")
    out = None
    for f in Timeline().hold(2.0).fall().hold(seconds, HORIZONTAL, motion=0.02):
        out = det.update(f)
        rec.handle(out)
    return det, rec, out


def post(client, url, body=None, headers=JSON):
    return client.post(url, data=json.dumps(body if body is not None else {}), headers=headers)


# ---------------------------------------------------------------- health / status
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["pipeline_running"] is False and d["database"] is True
    assert TS_RE.match(d["server_time"])


def test_status_before_the_camera_loop_publishes(client):
    d = client.get("/api/status").get_json()
    assert d["snapshot"] is None and d["stale"] is True and d["last_event"] is None


def test_status_shows_state_condition_severity_score_duration(client, store, repo):
    det, rec, out = fallen_detector(repo)
    event_id = rec.event_id_for_incident(out.incident.incident_id)
    store.publish(build_snapshot(out, None, fps=29.5, frame_size=(640, 480),
                                 event={"id": event_id, "status": "NEW"}))
    d = client.get("/api/status").get_json()
    s = d["snapshot"]
    assert d["stale"] is False and d["age_s"] == 0
    assert (s["state"], s["condition"], s["risk_level"]) == ("ALERT", "FALL", "HIGH")
    assert CFG.fall_detection.alert_score_threshold <= s["score"] <= 1
    assert set(s["score_components"]) == {"velocity", "angle", "posture", "stillness", "persistence"}
    assert s["incident"]["open"] is True and s["incident"]["duration_s"] > 10
    assert TS_RE.match(s["incident"]["started_at"]) and TS_RE.match(s["updated_at"])
    assert s["timers"]["alert_elapsed_s"] is not None and s["event"]["id"] == event_id
    assert d["last_event"]["id"] == event_id and d["last_event"]["status"] == "NEW"


def test_status_becomes_stale_when_the_loop_stops_publishing(client, store, repo, clock):
    _, _, out = fallen_detector(repo, seconds=1.0)
    store.publish(build_snapshot(out, None, fps=30, frame_size=None, event=None))
    clock.t += 2.0
    assert client.get("/api/status").get_json()["stale"] is False
    clock.t += 2.0
    d = client.get("/api/status").get_json()
    assert d["stale"] is True and d["age_s"] == pytest.approx(4.0)


# ---------------------------------------------------------------- events
def test_event_list_newest_first_with_filters(client, repo):
    assert client.get("/api/events").get_json() == {"events": [], "total": 0, "open": 0}
    a = repo.create_event("FALL", "HIGH", 0.9)
    b = repo.create_event("LYING", "LOW", 0.3, status="MONITORING")
    c = repo.create_event("IMMOBILITY", "MEDIUM", 0.6)
    repo.resolve_event(c.id, resolution="RECOVERED")
    d = client.get("/api/events").get_json()
    assert [e["id"] for e in d["events"]] == [c.id, b.id, a.id]
    assert d["total"] == 3 and d["open"] == 2
    assert [e["id"] for e in client.get("/api/events?open=1").get_json()["events"]] == [b.id, a.id]
    assert [e["id"] for e in client.get("/api/events?status=NEW").get_json()["events"]] == [a.id]
    assert [e["id"] for e in client.get("/api/events?type=LYING").get_json()["events"]] == [b.id]
    assert [e["id"] for e in client.get("/api/events?limit=1&offset=1").get_json()["events"]] == [b.id]
    e = d["events"][0]
    assert {"created_at_local", "severity", "score", "duration_seconds", "status"} <= set(e)


@pytest.mark.parametrize("query", ["limit=0", "limit=abc", "limit=500", "status=BOGUS", "type=X",
                                   "offset=-1"])
def test_event_list_rejects_bad_parameters(client, query):
    r = client.get(f"/api/events?{query}")
    assert r.status_code == 400 and "error" in r.get_json()


def test_event_detail_with_history_and_not_found(client, repo):
    e = repo.create_event("FALL", "HIGH", 0.9, status="MONITORING", note="fall confirmed")
    repo.update_status(e.id, "NEW", note="alert")
    d = client.get(f"/api/events/{e.id}").get_json()
    assert d["event"]["id"] == e.id
    assert [h["to_status"] for h in d["history"]] == ["MONITORING", "NEW"]
    r = client.get("/api/events/999")
    assert r.status_code == 404 and "999" in r.get_json()["error"]
    assert client.get("/api/nope").status_code == 404 and client.get("/api/nope").is_json
    assert client.get(f"/api/events/{e.id}/assistance").status_code == 405


# ---------------------------------------------------------------- actions without the camera loop
def test_assistance_and_resolve_directly_on_the_database(client, repo):
    e = repo.create_event("FALL", "HIGH", 0.9)
    r = post(client, f"/api/events/{e.id}/assistance", {"note": "  helped up  "})
    d = r.get_json()
    assert r.status_code == 200 and d["applied_to_live_incident"] is False
    assert d["event"]["status"] == "ASSISTANCE_RECORDED"
    assert repo.status_history(e.id)[-1].note == "helped up"
    r = post(client, f"/api/events/{e.id}/resolve")
    assert r.status_code == 200 and r.get_json()["event"]["status"] == "RESOLVED"
    assert r.get_json()["event"]["resolution"] == "RESOLVED_BY_USER"
    r = post(client, f"/api/events/{e.id}/resolve")
    assert r.status_code == 409 and "not allowed" in r.get_json()["error"]
    assert post(client, "/api/events/999/assistance").status_code == 404


def test_actions_require_json_and_validate_the_body(client, repo):
    e = repo.create_event("FALL", "HIGH", 0.9)
    assert client.post(f"/api/events/{e.id}/assistance").status_code == 415     # no JSON
    assert client.post(f"/api/events/{e.id}/assistance", data="note=x",
                       headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 415
    assert post(client, f"/api/events/{e.id}/assistance", [1, 2]).status_code == 400
    assert post(client, f"/api/events/{e.id}/assistance", {"note": 5}).status_code == 400
    assert repo.get_event(e.id).status.value == "NEW"                             # unchanged
    r = post(client, f"/api/events/{e.id}/assistance", {"note": "x" * 2000})
    assert r.status_code == 200 and len(repo.status_history(e.id)[-1].note) == 500


def test_without_database_events_are_unavailable_but_status_works(store):
    c = create_app(CFG, store, None).test_client()
    assert c.get("/api/events").status_code == 503
    assert post(c, "/api/events/1/assistance").status_code == 503
    d = c.get("/api/status").get_json()
    assert d["last_event"] is None and c.get("/api/health").get_json()["database"] is False


# ---------------------------------------------------------------- actions through the camera loop
class StandInLoop:
    """Drains commands on its own thread and applies them, exactly like the real loop."""

    def __init__(self, store, repo, detector, recorder, process=True):
        self.store, self.repo, self.det, self.rec = store, repo, detector, recorder
        self.process = process
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            if self.process:
                for cmd in self.store.drain():
                    try:
                        cmd.finish(result=apply_command(cmd.kind, cmd.event_id, cmd.note,
                                                        repo=self.repo, detector=self.det,
                                                        events=self.rec))
                    except Exception as exc:  # noqa: BLE001
                        cmd.finish(error=exc)
            time.sleep(0.01)

    def __enter__(self):
        self.store.set_pipeline_running(True)
        self.thread.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self.thread.join(1)
        self.store.set_pipeline_running(False)


def test_assistance_on_the_live_incident_goes_through_the_loop(client, store, repo):
    det, rec, out = fallen_detector(repo)
    event_id = rec.event_id_for_incident(out.incident.incident_id)
    with StandInLoop(store, repo, det, rec):
        r = post(client, f"/api/events/{event_id}/assistance", {"note": "nurse arrived"})
    d = r.get_json()
    assert r.status_code == 200 and d["applied_to_live_incident"] is True
    assert d["event"]["status"] == "ASSISTANCE_RECORDED"
    assert det.state is DetectionState.RESOLVED            # the detector itself was acknowledged
    assert repo.status_history(event_id)[-1].note == "nurse arrived"


def test_resolve_on_the_live_incident(client, store, repo):
    det, rec, out = fallen_detector(repo)
    event_id = rec.event_id_for_incident(out.incident.incident_id)
    with StandInLoop(store, repo, det, rec):
        d = post(client, f"/api/events/{event_id}/resolve", {"note": "demo"}).get_json()
    assert d["applied_to_live_incident"] is True and d["event"]["status"] == "RESOLVED"
    assert d["event"]["resolution"] == "RESOLVED_BY_USER" and det.state is DetectionState.RESOLVED


def test_older_event_while_loop_runs_is_updated_directly(client, store, repo):
    old = repo.create_event("LYING", "MEDIUM", 0.5)
    det, rec, _ = fallen_detector(repo)
    with StandInLoop(store, repo, det, rec):
        d = post(client, f"/api/events/{old.id}/assistance").get_json()
    assert d["applied_to_live_incident"] is False and d["event"]["status"] == "ASSISTANCE_RECORDED"
    assert det.state is DetectionState.ALERT                 # live incident untouched


def test_busy_loop_times_out_with_a_clear_message(client, store, repo):
    e = repo.create_event("FALL", "HIGH", 0.9)
    with StandInLoop(store, repo, None, None, process=False):
        r = post(client, f"/api/events/{e.id}/assistance")
    assert r.status_code == 503 and "did not respond" in r.get_json()["error"]


def test_stopping_the_store_fails_pending_commands():
    store = StatusStore()
    cmd = store.submit(Command("assistance", 1))
    store.stop()
    assert cmd.done.is_set() and isinstance(cmd.error, RuntimeError)


# ---------------------------------------------------------------- preview
def test_preview_frame_and_stream(client, store):
    assert client.get("/api/preview.jpg").status_code == 503
    store.set_frame(b"\xff\xd8jpegbytes\xff\xd9")
    r = client.get("/api/preview.jpg")
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data.startswith(b"\xff\xd8")
    r = client.get("/video_feed", buffered=False)
    assert r.mimetype == "multipart/x-mixed-replace"
    chunks = iter(r.response)
    first = next(chunks)
    assert b"Content-Type: image/jpeg" in first and b"jpegbytes" in first
    store.stop()                                              # stream must end on shutdown
    assert list(chunks) == []


def test_preview_can_be_disabled(repo, store):
    cfg = CFG.with_overrides({"dashboard": {"preview_enabled": False}})
    c = create_app(cfg, store, repo).test_client()
    assert c.get("/video_feed").status_code == 404 and c.get("/api/preview.jpg").status_code == 404


def test_config_endpoint_is_read_only_summary(client):
    d = client.get("/api/config").get_json()
    assert d["fall_detection"]["recovery_window_seconds"] == CFG.fall_detection.recovery_window_seconds
    assert "host" not in d["dashboard"] and "lying_monitor_seconds" in d["immobility"]
    assert client.post("/api/config").status_code == 405


# ---------------------------------------------------------------- real HTTP server
def test_server_starts_serves_and_stops_cleanly(repo):
    server = DashboardServer(create_app(CFG, StatusStore(), repo), "127.0.0.1", 0).start()
    try:
        with urllib.request.urlopen(f"{server.url}/api/health", timeout=3) as resp:
            assert resp.status == 200 and json.load(resp)["ok"] is True
        with pytest.raises(DashboardError, match="in use|cannot start"):
            DashboardServer(create_app(CFG, StatusStore(), repo), "127.0.0.1", server.port)
    finally:
        server.stop()
    assert not server.running


# ---------------------------------------------------------------- dashboard page
def test_dashboard_page_and_static_files(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and r.mimetype == "text/html"
    for element_id in ("band-title", "act-assist", "act-resolve", "meter", "f-condition",
                       "f-severity", "f-duration", "f-event-time", "events", "preview"):
        assert f'id="{element_id}"' in html
    assert 'data-status-poll-ms="1000"' in html and 'data-preview-enabled="true"' in html
    assert "getUserMedia" not in client.get("/static/app.js").get_data(as_text=True)
    assert client.get("/static/style.css").status_code == 200
    font = client.get("/static/fonts/AtkinsonHyperlegible-Regular.ttf")
    assert font.status_code == 200 and len(font.data) > 10_000
