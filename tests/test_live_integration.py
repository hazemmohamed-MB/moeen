"""Phase 7 integration test: every non-camera component wired together, as in the live app.

    synthetic FeatureFrames -> ProcessingPipeline
        -> AssistanceDetector -> EventRecorder -> SQLite
        -> DashboardBridge -> StatusStore -> Flask API (+ the "Assistance recorded" button)
        -> AlertManager -> SoundPlayer (fake audio output that records each play)
        -> preview overlay (state banner + event/sound line)

The feature sequence is deterministic (hand-built frames at 30 fps, no randomness), so the
expected states, stored events, sounds and API answers are exact. Only the webcam and the
MediaPipe model are left out; their own tests cover them.
"""

import threading

import numpy as np

from feature_builders import HORIZONTAL, Timeline
from moeen.alerts import AlertManager, EventRecorder, SoundPlayer
from moeen.api import create_app
from moeen.config import load_config
from moeen.database import Database, EventRepository
from moeen.detection import AssistanceDetector, DetectionState as S
from moeen.pose.overlay import STATE_COLORS, alert_status_line, draw_state_banner
from moeen.runtime import DashboardBridge, ProcessingPipeline, StatusStore

CFG = load_config()            # the shipped thresholds and sound rules, unchanged


class RecordingAudio:
    """Stands in for the speaker: counts plays, makes no noise."""

    name = "test-speaker"

    def __init__(self):
        self.played = 0

    def play(self, wav_path, timeout):
        assert wav_path.exists()
        self.played += 1


class Run:
    """Feeds a growing Timeline through the pipeline frame by frame."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.tl = Timeline()
        self.done = 0
        self.seen: list[S] = []

    def feed(self, until=None):
        """Process the frames added since the last call (or until ``until(result)`` is true)."""
        result = None
        while self.done < len(self.tl.frames):
            result = self.pipeline.process(self.tl.frames[self.done], fps=30.0,
                                           frame_size=(640, 480))
            self.done += 1
            if not self.seen or self.seen[-1] is not result.output.state:
                self.seen.append(result.output.state)
            if until is not None and until(result):
                break
        return result


def test_live_pipeline_end_to_end(tmp_path, caplog):
    caplog.set_level("INFO")
    repo = EventRepository(Database(tmp_path / "live.db"))
    store = StatusStore()
    events = EventRecorder(repo, session_id="phase7")
    speaker = RecordingAudio()
    player = SoundPlayer(CFG.sound, backends=[speaker]).start()
    pipeline = ProcessingPipeline(
        AssistanceDetector(CFG.fall_detection, CFG.immobility), events=events,
        alerts=AlertManager(CFG.sound, player),
        bridge=DashboardBridge(store, CFG.dashboard, repo=repo, events=events))
    api = create_app(CFG, store, repo).test_client()
    store.set_pipeline_running(True)
    run = Run(pipeline)

    def status():
        return api.get("/api/status").get_json()["snapshot"]

    try:
        # 1. normal standing: nothing stored, no sound -----------------------------------
        run.tl.hold(3.0)
        run.feed()
        assert status()["state"] == "NORMAL" and repo.count_events() == 0

        # 2. fall, then the person stays down ----------------------------------------------
        run.tl.fall().hold(30.0, HORIZONTAL, motion=0.01)
        r = run.feed(until=lambda r: r.output.state is S.RECOVERY_WINDOW)
        assert r.event["status"] == "MONITORING"                       # stored, watching
        assert status()["event"] == r.event and speaker.played == 0    # no sound yet

        r = run.feed(until=lambda r: r.output.state is S.ALERT)
        first_id = r.event["id"]
        assert r.event == {"id": first_id, "status": "NEW"}            # unanswered alert
        snap = status()
        assert snap["condition"] == "FALL" and snap["risk_level"] == "HIGH"

        # overlay on the camera preview for this frame
        img = np.zeros((480, 640, 3), np.uint8)
        strip = draw_state_banner(img, r.output)
        assert strip > 0 and tuple(img[2, 320]) == STATE_COLORS["ALERT"]
        run.feed()                                                     # rest of the 30 s down
        assert player.wait_idle(2)
        line = alert_status_line(pipeline.last.event, pipeline.sound_status())
        assert line.startswith(f"Event #{first_id} NEW (unanswered) | sound: on (test-speaker), played 1x")
        # ~17 s of ALERT frames (~500 frames), still exactly one sound (repeat is every 30 s)
        assert speaker.played == 1 and status()["sound"]["plays"] == 1

        # 3. "Assistance recorded" pressed on the dashboard while the loop runs ------------
        reply = {}
        click = threading.Thread(target=lambda: reply.update(
            api.post(f"/api/events/{first_id}/assistance", json={"note": "helped up"}).get_json()))
        click.start()
        run.tl.hold(3.0, HORIZONTAL, motion=0.01)
        run.feed(until=lambda r: not click.is_alive())                 # the loop applies it
        click.join(5)
        assert reply["applied_to_live_incident"] is True
        assert reply["event"]["status"] == "ASSISTANCE_RECORDED"
        assert pipeline.detector.state is S.RESOLVED and status()["event"] is None
        run.feed()                                                     # still lying, answered
        assert speaker.played == 1                                     # the sound stopped

        # person gets up; the system re-arms
        run.tl.hold(6.0)
        run.feed()
        assert pipeline.detector.state is S.NORMAL

        # 4. second fall, alert, then the person gets up alone -----------------------------
        run.tl.hold(2.0).fall().hold(20.0, HORIZONTAL, motion=0.01)
        r = run.feed(until=lambda r: r.output.state is S.ALERT)
        second_id = r.event["id"]
        run.feed()
        assert player.wait_idle(2) and speaker.played == 2              # new incident, new sound
        run.tl.hold(8.0)                                               # stands up
        run.feed()
        assert pipeline.detector.state is S.NORMAL

        # 5. third fall, but the person recovers inside the recovery window ----------------
        run.tl.hold(2.0).fall().hold(2.0, HORIZONTAL, motion=0.01).hold(6.0)
        run.feed()
        assert pipeline.detector.state is S.NORMAL and speaker.played == 2   # never alerted
    finally:
        store.stop()
        player.close()

    # ---- what is stored: the full lifecycle of each event ------------------------------
    listed = api.get("/api/events").get_json()
    assert listed["total"] == 3 and listed["open"] == 0
    first, second, third = sorted(listed["events"], key=lambda e: e["id"])
    assert (first["id"], second["id"]) == (first_id, second_id)

    def history(event_id):
        return [h.to_status.value for h in repo.status_history(event_id)]
    assert history(first_id) == ["MONITORING", "NEW", "ASSISTANCE_RECORDED"]
    assert history(second_id) == ["MONITORING", "NEW", "RESOLVED"]
    assert history(third["id"]) == ["MONITORING", "RESOLVED"]
    assert second["resolution"] == "RECOVERED_AFTER_ALERT" and third["resolution"] == "RECOVERED"
    assert all(e["event_type"] == "FALL" and e["severity"] for e in (first, second, third))
    assert first["duration_seconds"] > 10 and third["duration_seconds"] < 5

    # ---- the detector went through the PRD states, the log tells the story -------------
    assert run.seen[:5] == [S.NORMAL, S.POSSIBLE_FALL, S.RECOVERY_WINDOW, S.ALERT, S.RESOLVED]
    log = caplog.text
    assert log.count("ALERT raised: FALL, severity HIGH (sound on)") == 2
    assert log.count("Alert sound: FALL alert (HIGH)") == 2
    assert f"Event #{first_id} FALL: status NEW" in log
    assert f"Event #{first_id} FALL: status ASSISTANCE_RECORDED" in log
    assert f"Dashboard: assistance recorded for event {first_id} (live incident)" in log
    assert events.errors == 0
