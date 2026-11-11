"""Phase 6 integration: the processing loop drives the dashboard.

1. DashboardBridge on its own (real detector + recorder on hand-built feature frames).
2. The whole app (``moeen.app.main``) with a fake camera and a synthetic fall replayed as
   poses, the dashboard on a free port, and real HTTP requests made while the loop runs.
No webcam, no MediaPipe model, no browser.
"""

import dataclasses
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pytest

import moeen.app as app
import moeen.pose.pose_estimator as pe
import synthetic as syn
from fakes import FakeCapture, SequenceEstimator, factory_for
from feature_builders import HORIZONTAL, Timeline
from moeen.alerts import EventRecorder
from moeen.api import server as api_server
from moeen.camera.webcam import Webcam
from moeen.config import load_config
from moeen.database import Database, EventRepository, EventStatus
from moeen.detection import AssistanceDetector, DetectionState
from moeen.runtime import Command, DashboardBridge, StatusStore
from moeen.runtime.shutdown import sigterm_as_keyboard_interrupt

CFG = load_config()
ROOT = Path(__file__).resolve().parent.parent


class FakeClock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


@pytest.fixture
def repo(tmp_path):
    return EventRepository(Database(tmp_path / "bridge.db"))


def run_frames(det, rec, bridge, frames):
    out = None
    for f in frames:
        out = det.update(f)
        rec.handle(out)
        out = bridge.step(det, out, f, fps=30.0, frame_size=(640, 480))
    return out


# ---------------------------------------------------------------- bridge
def test_bridge_publishes_state_and_live_event(repo):
    store = StatusStore()
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    rec = EventRecorder(repo, session_id="bridge")
    bridge = DashboardBridge(store, CFG.dashboard, repo=repo, events=rec)

    run_frames(det, rec, bridge, Timeline().hold(2.0))
    snap, _ = store.snapshot()
    assert snap["state"] == "NORMAL" and snap["event"] is None

    run_frames(det, rec, bridge, Timeline(2000 + 1000 / 30).fall().hold(1.0, HORIZONTAL, motion=0.01))
    snap, _ = store.snapshot()
    assert snap["state"] in ("RECOVERY_WINDOW", "MONITORING")
    (ev,) = repo.list_events()
    assert snap["event"] == {"id": ev.id, "status": "MONITORING"}      # matches the stored row

    tl = Timeline(det.last_output.timestamp_ms + 1000 / 30).hold(40.0, HORIZONTAL, motion=0.01)
    run_frames(det, rec, bridge, tl)
    snap, _ = store.snapshot()
    assert snap["state"] == "ALERT"
    assert snap["event"] == {"id": ev.id, "status": repo.get_event(ev.id).status.value} \
        == {"id": ev.id, "status": "NEW"}


def test_bridge_applies_a_queued_action_to_the_live_incident(repo):
    store = StatusStore()
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    rec = EventRecorder(repo, session_id="bridge")
    bridge = DashboardBridge(store, CFG.dashboard, repo=repo, events=rec)
    tl = Timeline().hold(2.0).fall().hold(40.0, HORIZONTAL, motion=0.01)
    run_frames(det, rec, bridge, tl)
    assert det.state is DetectionState.ALERT
    (ev,) = repo.list_events()

    cmd = store.submit(Command("assistance", ev.id, "helped up"))
    shown = run_frames(det, rec, bridge, Timeline(tl.t).hold(0.04, HORIZONTAL, motion=0.01))
    assert cmd.wait(0.1) and cmd.error is None
    event, out = cmd.result
    assert out is not None and det.state is DetectionState.RESOLVED
    assert shown.state is DetectionState.RESOLVED
    assert event.status is EventStatus.ASSISTANCE_RECORDED
    snap, _ = store.snapshot()
    assert snap["state"] == "RESOLVED" and snap["event"] is None
    assert snap["incident"]["resolution"] == "ASSISTANCE_RECORDED"
    assert bridge.commands_applied == 1


def test_bridge_reports_command_errors_and_keeps_going(repo):
    store = StatusStore()
    bridge = DashboardBridge(store, CFG.dashboard, repo=repo, events=None)
    bad = store.submit(Command("assistance", 999, None))
    assert bridge.apply_commands(None, None) is None
    assert bad.wait(0.1) and bad.error is not None

    no_db = DashboardBridge(store, CFG.dashboard, repo=None, events=None)
    cmd = store.submit(Command("resolve", 1, None))
    no_db.apply_commands(None, None)
    assert "disabled" in str(cmd.error)


def test_bridge_throttles_preview_frames():
    clock = FakeClock()
    store = StatusStore()
    cfg = CFG.dashboard  # preview_fps from config
    bridge = DashboardBridge(store, cfg, repo=None, events=None, clock=clock)
    img = np.zeros((48, 64, 3), np.uint8)
    assert bridge.preview_due() and bridge.send_preview(img)
    jpg, _ = store.latest_frame()
    assert jpg[:2] == b"\xff\xd8"                                   # a JPEG
    assert cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR).shape == (48, 64, 3)
    clock.t += 0.5 / cfg.preview_fps
    assert not bridge.preview_due()
    clock.t += 0.6 / cfg.preview_fps
    assert bridge.preview_due()

    off = DashboardBridge(store, dataclasses.replace(cfg, preview_enabled=False),
                          repo=None, events=None, clock=clock)
    assert not off.preview_due()


# ---------------------------------------------------------------- whole app
class StoppableEstimator(SequenceEstimator):
    """Replays poses; raises KeyboardInterrupt (like Ctrl+C) once ``stop`` is set."""

    def __init__(self, frames, stop):
        super().__init__(frames)
        self.stop = stop

    def detect(self, frame_bgr, timestamp_ms):
        if self.stop.is_set():
            raise KeyboardInterrupt
        return super().detect(frame_bgr, timestamp_ms)


def http(url, data=None):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"} if data is not None else {},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as r:
        body = r.read()
        return r.status, r.headers.get("Content-Type", ""), body


def wait_for(fn, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached in time")


@pytest.fixture
def started_servers(monkeypatch):
    servers = []
    real_start = api_server.DashboardServer.start

    def start(self):
        servers.append(self)
        return real_start(self)
    monkeypatch.setattr(api_server.DashboardServer, "start", start)
    return servers


def test_app_serves_live_state_and_takes_actions_while_running(tmp_path, monkeypatch,
                                                                started_servers):
    stop = threading.Event()
    est = StoppableEstimator(syn.render(syn.fall(16), 16, 30.0, noise=0.003), stop)
    cap = FakeCapture(delay=0.001)
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam", lambda cfg: Webcam(cfg, factory_for(cap)))

    class Speaker:                      # Phase 7: the alert sound, without making noise
        name = "test-speaker"
        played = 0

        def play(self, wav_path, timeout):
            Speaker.played += 1
    import moeen.alerts.sound_alert as sound_alert
    monkeypatch.setattr(sound_alert, "choose_backends", lambda *a, **k: [Speaker()])
    db = tmp_path / "live.db"
    result = {}
    t = threading.Thread(target=lambda: result.setdefault(
        "code", app.main(["--no-window", "--db-path", str(db), "--port", "0"])))
    t.start()
    try:
        (server,) = wait_for(lambda: started_servers, 10)
        base = server.url

        def status():
            return json.loads(http(base + "/api/status")[2])
        first = wait_for(lambda: (s := status())["snapshot"] and s)
        assert first["pipeline_running"] is True and first["stale"] is False

        alert = wait_for(lambda: (s := status())["snapshot"]["state"] == "ALERT" and s)
        snap = alert["snapshot"]
        assert snap["condition"] == "FALL" and snap["incident"]["open"] is True
        event_id = snap["event"]["id"]
        assert snap["event"]["status"] == "NEW" and alert["last_event"]["id"] == event_id
        sound = wait_for(lambda: (x := status()["snapshot"]["sound"])["plays"] >= 1 and x)
        assert sound["backend"] == "test-speaker" and sound["available"] is True

        code, ctype, jpg = http(base + "/api/preview.jpg")          # Python-rendered frame
        assert code == 200 and ctype == "image/jpeg" and jpg[:2] == b"\xff\xd8"

        code, _, body = http(f"{base}/api/events/{event_id}/assistance", {"note": "helped up"})
        reply = json.loads(body)
        assert code == 200 and reply["applied_to_live_incident"] is True
        assert reply["event"]["status"] == "ASSISTANCE_RECORDED"
        wait_for(lambda: status()["snapshot"]["state"] in ("RESOLVED", "NORMAL"))

        # a browser watching the live picture must not keep the app from shutting down
        stream = urllib.request.urlopen(base + "/video_feed", timeout=10)
        assert stream.headers["Content-Type"].startswith("multipart/x-mixed-replace")
        assert b"image/jpeg" in stream.read(200)
        stream_done = threading.Event()
        threading.Thread(target=lambda: (stream.read(), stream_done.set()), daemon=True).start()
    finally:
        stop.set()
        t.join(15)
    assert stream_done.wait(5), "the video stream did not end when the app stopped"
    assert not t.is_alive() and result["code"] == app.EXIT_OK
    assert not server.running                                       # web thread joined
    with pytest.raises(urllib.error.URLError):
        http(base + "/api/health")
    assert est.closed and cap.released == 1
    assert Speaker.played == 1                  # one alert, one chime (not one per frame)
    (ev,) = EventRepository(Database(db)).list_events()
    assert ev.status is EventStatus.ASSISTANCE_RECORDED and ev.id == event_id


def test_app_reports_a_busy_dashboard_port_before_opening_the_camera(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: opened.append("model"))
    monkeypatch.setattr(app, "Webcam", lambda cfg: opened.append("camera"))
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        code = app.main(["--no-window", "--db-path", str(tmp_path / "x.db"), "--port", str(port)])
    assert code == app.EXIT_DASHBOARD_ERROR and opened == []


def test_app_no_dashboard_flag_starts_no_server(tmp_path, monkeypatch, started_servers):
    est = SequenceEstimator(syn.render(syn.standing(1.0), 1.0, 30.0))
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam", lambda cfg: Webcam(cfg, factory_for(FakeCapture(delay=0.0005))))
    assert app.main(["--no-window", "--max-frames", "10", "--no-dashboard",
                     "--db-path", str(tmp_path / "y.db")]) == app.EXIT_OK
    assert started_servers == []


# ---------------------------------------------------------------- shutdown signals
@pytest.mark.skipif(not hasattr(signal, "SIGTERM") or sys.platform == "win32",
                    reason="POSIX signals")
def test_sigterm_becomes_keyboard_interrupt_inside_the_block():
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(KeyboardInterrupt):
        with sigterm_as_keyboard_interrupt():
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)                       # the handler runs before this finishes
    assert signal.getsignal(signal.SIGTERM) == before


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_standalone_dashboard_process_starts_and_stops_on_sigterm(tmp_path):
    with socket.socket() as s:                  # pick a free port for the child process
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "moeen.api", "--db", str(tmp_path / "s.db"),
                             "--port", str(port)], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        health = wait_for(lambda: _try_health(port), 15)
        assert health["ok"] is True and health["pipeline_running"] is False
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0 and "Dashboard stopped." in out


def _try_health(port):
    try:
        return json.loads(http(f"http://127.0.0.1:{port}/api/health")[2])
    except (urllib.error.URLError, ConnectionError):
        return None
