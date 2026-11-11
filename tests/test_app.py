"""Smoke tests for the preview loop, exit handling and CLI exit codes - no camera, no window."""

import cv2
import numpy as np
import pytest

import moeen.app as app
import moeen.pose.pose_estimator as pe
import synthetic
from fakes import FakeCapture, FakeEstimator, factory_for, upright_landmarks
from moeen.camera.webcam import Webcam
from moeen.config import CameraConfig, load_config
from moeen.detection import DetectionState, AssistanceDetector
from moeen.features import FeatureExtractor
from moeen.pose.overlay import detection_status_lines, feature_status_lines
from moeen.pose.recording import load_recording
from moeen.types import PoseFrame


def test_run_preview_processes_frames_without_window():
    cfg = load_config()
    est = FakeEstimator()
    with Webcam(CameraConfig(open_timeout_seconds=0.5), factory_for(FakeCapture())) as cam:
        stats = app.run_preview(cfg, cam, est, max_frames=6, window=None)
    assert stats.frames == 6
    assert stats.frames_with_pose == 3
    assert stats.stop_reason == "max frames reached"
    assert est.calls == sorted(est.calls)


def test_render_frame_mirrors_and_keeps_size():
    cfg = load_config()
    img = np.zeros((120, 160, 3), np.uint8)
    out = app.render_frame(img, PoseFrame(0, 160, 120, upright_landmarks()), cfg.display, 25.0, "info")
    assert out.shape == img.shape and out.any()
    assert not img.any()  # input not modified


def test_run_preview_computes_features_every_frame():
    cfg = load_config()
    extractor = FeatureExtractor(cfg.features)
    with Webcam(CameraConfig(open_timeout_seconds=0.5), factory_for(FakeCapture())) as cam:
        app.run_preview(cfg, cam, FakeEstimator(), max_frames=8, extractor=extractor)
    frames = list(extractor.history)
    assert len(frames) == 8
    assert [f.pose_present for f in frames] == [True, False] * 4   # FakeEstimator alternates


def test_render_frame_with_features_shows_feature_text():
    cfg = load_config()
    pose = synthetic.render(synthetic.standing(), 0.0)[0]
    feats = FeatureExtractor(cfg.features).update(pose)
    img = np.zeros((480, 640, 3), np.uint8)
    plain = app.render_frame(img, pose, cfg.display, 30.0, "info")
    with_feats = app.render_frame(img, pose, cfg.display, 30.0, "info", feats)
    assert (with_feats != plain).any()
    assert feature_status_lines(feats)[0].startswith("Posture UPRIGHT")


def test_main_record_flag_writes_loadable_recording(monkeypatch, tmp_path, run_main):
    est = FakeEstimator()
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam", lambda cfg: Webcam(cfg, factory_for(FakeCapture())))
    path = tmp_path / "rec.jsonl"
    assert run_main(["--no-window", "--max-frames", "5", "--record", str(path),
                     "--label", "smoke"]) == app.EXIT_OK
    header, frames = load_recording(path)
    assert header["label"] == "smoke" and header["frame_width"] == 64
    assert len(frames) == 5 and frames[0].has_pose and not frames[1].has_pose


@pytest.fixture
def run_main(tmp_path):
    """Call app.main with the event database redirected to a temporary file, so tests never
    touch the project's data/moeen.db, and the dashboard on any free port."""
    db = tmp_path / "events.db"

    def _run(argv):
        return app.main([*argv, "--db-path", str(db), "--port", "0"])
    _run.db_path = db
    return _run


class FakeGui:
    """Replaces the cv2 window functions used by PreviewWindow."""

    def __init__(self, keys=(), visibility=()):
        self.keys, self.visibility = list(keys), list(visibility)

    def install(self, monkeypatch):
        monkeypatch.setattr(cv2, "namedWindow", lambda *a: None)
        monkeypatch.setattr(cv2, "imshow", lambda *a: None)
        monkeypatch.setattr(cv2, "waitKey", lambda *a: self.keys.pop(0) if self.keys else -1)
        monkeypatch.setattr(cv2, "getWindowProperty", self._prop)
        monkeypatch.setattr(cv2, "destroyWindow", lambda *a: None)

    def _prop(self, *a):
        v = self.visibility.pop(0) if self.visibility else 1.0
        if v == "error":
            raise cv2.error("NULL window")
        return v


IMG = np.zeros((10, 10, 3), np.uint8)


@pytest.mark.parametrize("key", [ord("q"), ord("Q"), 27])
def test_quit_keys(monkeypatch, key):
    FakeGui(keys=[-1, key]).install(monkeypatch)
    w = app.PreviewWindow("t")
    assert w.show(IMG) is None
    assert w.show(IMG) == "key pressed"


def test_window_close_button_detected(monkeypatch):
    FakeGui(visibility=[1.0, 1.0, 0.0]).install(monkeypatch)
    w = app.PreviewWindow("t")
    assert w.show(IMG) is None and w.show(IMG) is None
    assert w.show(IMG) == "window closed"


def test_window_destroyed_error_detected(monkeypatch):
    FakeGui(visibility=[1.0, "error"]).install(monkeypatch)
    w = app.PreviewWindow("t")
    w.show(IMG)
    assert w.show(IMG) == "window closed"


def test_backend_without_visibility_support_does_not_quit(monkeypatch):
    FakeGui(visibility=[-1.0] * 5).install(monkeypatch)
    w = app.PreviewWindow("t")
    assert all(w.show(IMG) is None for _ in range(5))


def test_headless_opencv_reported(monkeypatch):
    def no_gui(*a):
        raise cv2.error("The function is not implemented")
    monkeypatch.setattr(cv2, "namedWindow", no_gui)
    with pytest.raises(app.DisplayError, match="headless"):
        app.PreviewWindow("t")


# ---------------------------------------------------------------- CLI exit codes
def test_main_config_error_exit_code(tmp_path, run_main):
    bad = tmp_path / "bad.yaml"
    bad.write_text("camera:\n  width: 0\n")
    assert run_main(["--config", str(bad), "--no-window"]) == app.EXIT_CONFIG_ERROR


def test_main_missing_model_exit_code(tmp_path, run_main):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"pose:\n  model_dir: '{tmp_path.as_posix()}'\n")
    assert run_main(["--config", str(cfg), "--no-window"]) == app.EXIT_POSE_ERROR


def test_main_camera_open_failure_exit_code(monkeypatch, run_main):
    est = FakeEstimator()
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam",
                        lambda cfg: Webcam(cfg, factory_for(FakeCapture(opened=False))))
    assert run_main(["--no-window", "--camera-index", "7"]) == app.EXIT_CAMERA_ERROR
    assert est.closed  # model released even though the camera failed


def test_main_runs_headless_to_completion(monkeypatch, run_main):
    est = FakeEstimator()
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam", lambda cfg: Webcam(cfg, factory_for(FakeCapture())))
    assert run_main(["--no-window", "--max-frames", "4"]) == app.EXIT_OK
    assert len(est.calls) == 4 and est.closed


def test_main_ctrl_c_exits_cleanly(monkeypatch, run_main):
    class InterruptingEstimator(FakeEstimator):
        def detect(self, frame, ts):
            raise KeyboardInterrupt
    est = InterruptingEstimator()
    cap = FakeCapture()
    monkeypatch.setattr(pe, "MediaPipePoseEstimator", lambda cfg: est)
    monkeypatch.setattr(app, "Webcam", lambda cfg: Webcam(cfg, factory_for(cap)))
    assert run_main(["--no-window"]) == app.EXIT_OK
    assert est.closed and cap.released == 1


# ---------------------------------------------------------------- detector integration
def test_run_preview_runs_detector_and_needs_extractor():
    cfg = load_config()
    det = AssistanceDetector(cfg.fall_detection, cfg.immobility)
    with Webcam(CameraConfig(open_timeout_seconds=0.5), factory_for(FakeCapture())) as cam:
        with pytest.raises(ValueError, match="needs a feature extractor"):
            app.run_preview(cfg, cam, FakeEstimator(), max_frames=2, detector=det)
        stats = app.run_preview(cfg, cam, FakeEstimator(), max_frames=6,
                                extractor=FeatureExtractor(cfg.features), detector=det)
    assert det.last_output is not None and det.state is DetectionState.NORMAL
    assert stats.transitions == []


def test_ack_key_calls_detector_acknowledge(monkeypatch):
    cfg = load_config()
    det = AssistanceDetector(cfg.fall_detection, cfg.immobility)
    calls = []
    monkeypatch.setattr(det, "acknowledge", lambda t=None: calls.append(t))
    FakeGui(keys=[-1, ord("a"), -1, ord("q")]).install(monkeypatch)
    window = app.PreviewWindow("t")
    with Webcam(CameraConfig(open_timeout_seconds=0.5), factory_for(FakeCapture())) as cam:
        stats = app.run_preview(cfg, cam, FakeEstimator(), window=window,
                                extractor=FeatureExtractor(cfg.features), detector=det)
    assert stats.stop_reason == "key pressed" and len(calls) == 1


def test_render_frame_shows_alert_banner():
    cfg = load_config()
    det = AssistanceDetector(cfg.fall_detection, cfg.immobility)
    ex = FeatureExtractor(cfg.features)
    out = None
    for p in synthetic.render(synthetic.fall(16), 16):
        feats = ex.update(p)
        out = det.update(feats)
    assert out.state is DetectionState.ALERT
    img = np.zeros((480, 640, 3), np.uint8)
    framed = app.render_frame(img, p, cfg.display, 30.0, "info", feats, out)
    assert tuple(framed[2, 320]) == (0, 0, 255)            # red border at the top edge
    assert detection_status_lines(out)[0].startswith("STATE ALERT")


def test_mute_key_toggles_the_alert_sound(monkeypatch):
    from moeen.alerts import AlertManager, SoundPlayer
    cfg = load_config()
    player = SoundPlayer(cfg.sound, backends=[])
    FakeGui(keys=[-1, ord("m"), -1, ord("M"), ord("m"), ord("q")]).install(monkeypatch)
    window = app.PreviewWindow("t")
    with Webcam(CameraConfig(open_timeout_seconds=0.5), factory_for(FakeCapture())) as cam:
        app.run_preview(cfg, cam, FakeEstimator(), window=window,
                        extractor=FeatureExtractor(cfg.features),
                        detector=AssistanceDetector(cfg.fall_detection, cfg.immobility),
                        alerts=AlertManager(cfg.sound, player))
    assert player.muted is True                      # pressed three times


def test_alert_status_line_wording():
    from moeen.pose.overlay import alert_status_line
    on = {"enabled": True, "available": True, "muted": False, "backend": "afplay", "plays": 2}
    assert alert_status_line({"id": 4, "status": "NEW"}, on) == \
        "Event #4 NEW (unanswered) | sound: on (afplay), played 2x | a = assistance, m = mute"
    assert alert_status_line({"id": 4, "status": "MONITORING"}, {**on, "muted": True}) == \
        "Event #4 MONITORING | sound: MUTED | m = mute"
    assert alert_status_line(None, {**on, "available": False}) == "sound: no audio output | m = mute"
    assert alert_status_line(None, {**on, "enabled": False}) == "sound: off | m = mute"
    assert alert_status_line(None, None) is None


def test_debug_key_toggles_the_evidence_overlay(monkeypatch):
    cfg = load_config()
    seen = []
    real = app.render_frame

    def spy(*a, **k):
        seen.append(bool(a[8]) if len(a) > 8 else False)
        return real(*a, **k)
    monkeypatch.setattr(app, "render_frame", spy)
    FakeGui(keys=[-1, ord("d"), -1, ord("d"), -1, ord("q")]).install(monkeypatch)
    window = app.PreviewWindow("t")
    with Webcam(CameraConfig(open_timeout_seconds=0.5), factory_for(FakeCapture())) as cam:
        app.run_preview(cfg, cam, FakeEstimator(), window=window,
                        extractor=FeatureExtractor(cfg.features),
                        detector=AssistanceDetector(cfg.fall_detection, cfg.immobility))
    assert seen == [False, False, True, True, False, False]


def test_calibration_flags(tmp_path):
    args = app.build_arg_parser().parse_args(["--no-calibration"])
    assert app.config_from_args(args).source_files[-1].endswith("default.yaml")
    cal = tmp_path / "c.yaml"
    cal.write_text("values:\n  recovery_window_seconds: 7\n")
    args = app.build_arg_parser().parse_args(["--calibration", str(cal)])
    assert app.config_from_args(args).fall_detection.recovery_window_seconds == 7.0
