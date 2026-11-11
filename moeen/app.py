"""Moeen entry point - live webcam + MediaPipe pose preview with feature read-out.

Run from the project root:

    python -m moeen.app                      # defaults from config/default.yaml
    python -m moeen.app --camera-index 1 --width 1280 --height 720
    python -m moeen.app --record data/recordings/sit_01.jsonl --label "sit on chair"

Quit with ``q`` or ``Esc`` in the window, by closing the window, or with Ctrl+C in the terminal.
Press ``a`` in the window to acknowledge an incident ("assistance recorded"), ``m`` to mute or
unmute the alert sound, ``d`` to show the calibration evidence overlay.

Features are measured, the detection state machine (falls, sustained lying / low posture,
immobility) runs on every frame, its state is shown in the window, incidents are stored as
events in the local SQLite database (config: database.path; --no-db to skip), and a local
web dashboard shows the live state and event history (http://127.0.0.1:5000 by default;
--no-dashboard to skip). This process owns the webcam; the browser only shows frames that
Python has already processed. A confirmed high-severity alert plays a local chime, with a
cooldown so it never repeats every frame (sound section of the config; --no-sound to skip).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from moeen import __version__
from moeen.alerts import AlertManager, EventRecorder, SoundPlayer
from moeen.camera.webcam import CameraError, Webcam
from moeen.config import AppConfig, ConfigError, DisplayConfig, calibration_values, load_config
from moeen.database import EventRepository
from moeen.detection import AssistanceDetector, DetectionState, DetectorOutput, Transition
from moeen.features import FeatureExtractor, FeatureFrame
from moeen.pose.base import PoseEstimator
from moeen.pose.overlay import (alert_status_line, detection_status_lines, draw_features,
                                draw_pose, draw_state_banner, draw_status,
                                feature_status_lines)
from moeen.pose.debug_overlay import debug_lines, draw_debug_panel, evidence_rows
from moeen.pose.recording import PoseRecorder
from moeen.runtime import DashboardBridge, ProcessingPipeline, StatusStore
from moeen.runtime.shutdown import sigterm_as_keyboard_interrupt
from moeen.timing import FpsMeter

log = logging.getLogger("moeen")

EXIT_OK = 0
EXIT_CONFIG_ERROR = 4
EXIT_CAMERA_ERROR = 2
EXIT_POSE_ERROR = 3
EXIT_DISPLAY_ERROR = 5
EXIT_DATABASE_ERROR = 6
EXIT_DASHBOARD_ERROR = 7

_QUIT_KEYS = {ord("q"), ord("Q"), 27}  # 27 = Esc
_ACK_KEYS = {ord("a"), ord("A")}
_MUTE_KEYS = {ord("m"), ord("M")}
_DEBUG_KEYS = {ord("d"), ord("D")}


class DisplayError(RuntimeError):
    """The OpenCV build cannot open a window (e.g. a headless OpenCV is installed)."""


@dataclass
class PreviewStats:
    frames: int = 0
    frames_with_pose: int = 0
    elapsed_seconds: float = 0.0
    stop_reason: str = ""
    transitions: list[Transition] = field(default_factory=list)

    @property
    def average_fps(self) -> float:
        return self.frames / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0

    @property
    def pose_rate(self) -> float:
        return self.frames_with_pose / self.frames if self.frames else 0.0


class PreviewWindow:
    """OpenCV window that reports when the user wants to quit."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._seen_visible = False
        self.last_key = -1          # last key pressed (0-255), -1 if none
        try:
            cv2.namedWindow(name, cv2.WINDOW_NORMAL)
        except cv2.error as exc:
            raise DisplayError(
                "OpenCV cannot open a window. This usually means a headless OpenCV build is "
                "installed. Fix: pip uninstall -y opencv-python opencv-python-headless "
                "opencv-contrib-python && pip install -r requirements.txt\n"
                f"(OpenCV said: {exc})") from exc

    def show(self, image: np.ndarray) -> str | None:
        """Display ``image``. Returns a stop reason if the user quit, else None."""
        cv2.imshow(self.name, image)
        key = cv2.waitKey(1) & 0xFF
        self.last_key = key if key != 0xFF else -1
        if key in _QUIT_KEYS:
            return "key pressed"
        try:
            visible = cv2.getWindowProperty(self.name, cv2.WND_PROP_VISIBLE)
        except cv2.error:
            return "window closed"
        if visible >= 1:
            self._seen_visible = True
        elif self._seen_visible:  # was visible, now gone -> user clicked the close button
            return "window closed"
        return None

    def close(self) -> None:
        try:
            cv2.destroyWindow(self.name)
            cv2.waitKey(1)  # let the GUI event loop actually process the destroy
        except cv2.error:
            pass


def render_frame(image: np.ndarray, pose, display: DisplayConfig, fps: float,
                 extra: str, features: FeatureFrame | None = None,
                 detection: DetectorOutput | None = None,
                 alert_line: str | None = None,
                 debug: Sequence[str] | None = None) -> np.ndarray:
    """Return an annotated copy of ``image``: skeleton, torso axis, mirror, state border and
    ALERT strip, feature/state text, and (optionally) the event + sound status line.

    With ``debug`` lines (the evidence panel), the panel is drawn bottom-left and the raw
    feature lines are left out of the top box, so the screen does not fill up."""
    out = image.copy()
    drawn = draw_pose(out, pose, display.landmark_visibility_threshold)
    draw_features(out, features)
    if display.mirror:
        out = cv2.flip(out, 1)  # flip after drawing so the skeleton stays aligned
    strip = draw_state_banner(out, detection)
    total = len(pose.landmarks) if pose.has_pose else 0
    pose_text = f"Pose: detected ({drawn}/{total} visible)" if pose.has_pose else "Pose: no person"
    if debug:
        # calibration mode: a short status box, then the evidence panel right below it
        state = detection_status_lines(detection)[:1]
        bottom = draw_status(out, [f"FPS {fps:5.1f}  {pose_text}", *state,
                                   *([alert_line] if alert_line else [])],
                             origin=(10, 10 + strip))
        draw_debug_panel(out, debug, origin=(10, bottom + 4))
    else:
        draw_status(out, [f"FPS {fps:5.1f}", pose_text, *feature_status_lines(features),
                          *detection_status_lines(detection),
                          *([alert_line] if alert_line else []), extra], origin=(10, 10 + strip))
    return out


def run_preview(config: AppConfig, camera: Webcam, estimator: PoseEstimator, *,
                max_frames: int | None = None, max_seconds: float | None = None,
                window: PreviewWindow | None = None,
                extractor: FeatureExtractor | None = None,
                recorder: PoseRecorder | None = None,
                detector: AssistanceDetector | None = None,
                events: EventRecorder | None = None,
                bridge: DashboardBridge | None = None,
                alerts: AlertManager | None = None,
                debug_overlay: bool = False) -> PreviewStats:
    """Main loop: frame -> pose -> features -> pipeline -> draw -> show. Returns statistics.

    ``camera`` must already be open. Stops on quit key, window close, ``max_frames`` or
    ``max_seconds``. Camera failures propagate as :class:`CameraError`. If ``recorder`` is
    given, every PoseFrame is written to it. ``detector`` requires ``extractor``. The optional
    ``events`` (database), ``bridge`` (dashboard) and ``alerts`` (sound) are wired into a
    :class:`ProcessingPipeline` together with the detector. ``debug_overlay`` starts with the
    evidence panel shown (``d`` toggles it).
    """
    if detector is not None and extractor is None:
        raise ValueError("a detector needs a feature extractor")
    pipeline = (ProcessingPipeline(detector, events=events, alerts=alerts, bridge=bridge)
                if detector is not None else None)
    display = config.display
    fps_meter = FpsMeter(display.fps_window_seconds)
    stats = PreviewStats()
    t0 = time.monotonic()
    last_log = t0
    last_frame_id = 0
    frame_size = (camera.actual_width, camera.actual_height)
    info = (f"{camera.actual_width}x{camera.actual_height} | model {config.pose.model_variant}"
            f" | q/Esc to quit")

    while True:
        frame = camera.read_latest(after_id=last_frame_id, timeout=2.0)
        last_frame_id = frame.frame_id
        timestamp_ms = int((frame.timestamp - t0) * 1000)
        pose = estimator.detect(frame.image, timestamp_ms)
        features = extractor.update(pose) if extractor is not None else None
        if recorder is not None:
            recorder.write(pose)
        stats.frames += 1
        stats.frames_with_pose += int(pose.has_pose)
        fps = fps_meter.tick()

        result = (pipeline.process(features, fps=fps, frame_size=frame_size)
                  if pipeline is not None else None)
        if result is not None:
            stats.transitions.extend(result.transitions)
        detection = result.output if result is not None else None

        send_preview = bridge is not None and bridge.preview_due()
        if window is not None or send_preview:
            alert_line = (alert_status_line(result.event, pipeline.sound_status())
                          if result is not None else None)
            debug = (debug_lines(evidence_rows(detection, features, config))
                     if debug_overlay else None)
            image = render_frame(frame.image, pose, display, fps, info, features, detection,
                                 alert_line, debug)
            if send_preview:
                bridge.send_preview(image)
            if window is not None:
                reason = window.show(image)
                if reason:
                    stats.stop_reason = reason
                    break
                if pipeline is not None and window.last_key in _ACK_KEYS:
                    acked = pipeline.acknowledge(features, fps=fps, frame_size=frame_size)
                    if acked is not None:
                        stats.transitions.extend(acked.transitions)
                        detection = acked.output
                elif pipeline is not None and window.last_key in _MUTE_KEYS:
                    pipeline.toggle_mute()
                elif window.last_key in _DEBUG_KEYS:
                    debug_overlay = not debug_overlay

        now = time.monotonic()
        if now - last_log >= display.console_log_interval_seconds:
            feat = ""
            if features is not None and features.pose_present:
                feat = "  posture=%s torso=%s hip_v=%s motion=%s" % (
                    features.posture.value,
                    "-" if features.torso_angle_deg is None else f"{features.torso_angle_deg:.0f}",
                    "-" if features.hip_velocity is None else f"{features.hip_velocity:+.2f}",
                    "-" if features.motion_magnitude is None else f"{features.motion_magnitude:.3f}")
            if detection is not None:
                feat += f"  state={detection.state.value} score={detection.score:.2f}"
            log.info("fps=%.1f  pose=%s  frames=%d  pose_rate=%.0f%%%s", fps,
                     "yes" if pose.has_pose else "no", stats.frames, 100 * stats.pose_rate, feat)
            last_log = now
        if max_frames is not None and stats.frames >= max_frames:
            stats.stop_reason = "max frames reached"
            break
        if max_seconds is not None and now - t0 >= max_seconds:
            stats.stop_reason = "max seconds reached"
            break

    stats.elapsed_seconds = time.monotonic() - t0
    return stats


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m moeen.app",
                                description="Moeen - live webcam pose preview with features and detection state machine")
    p.add_argument("--config", help="config file (default: config/default.yaml)")
    p.add_argument("--override-config", help="optional YAML merged over --config")
    p.add_argument("--calibration", metavar="PATH",
                   help="calibration file (default: config/calibration.yaml)")
    p.add_argument("--no-calibration", action="store_true",
                   help="ignore config/calibration.yaml (use the code defaults)")
    p.add_argument("--debug-overlay", action="store_true",
                   help="start with the evidence overlay shown (toggle with d)")
    p.add_argument("--camera-index", type=int, help="override camera.index")
    p.add_argument("--width", type=int, help="override camera.width")
    p.add_argument("--height", type=int, help="override camera.height")
    p.add_argument("--camera-backend", help="override camera.backend (auto/any/dshow/msmf/avfoundation/v4l2)")
    p.add_argument("--model-variant", help="override pose.model_variant (lite/full/heavy)")
    p.add_argument("--no-window", action="store_true", help="run without a preview window")
    p.add_argument("--no-mirror", action="store_true", help="do not mirror the preview")
    p.add_argument("--max-frames", type=int, help="stop after N frames")
    p.add_argument("--max-seconds", type=float, help="stop after N seconds")
    p.add_argument("--record", metavar="PATH",
                   help="save the pose landmarks of this session to a .jsonl file (no video)")
    p.add_argument("--label", default="", help="free-text label stored in the recording header")
    p.add_argument("--no-db", action="store_true", help="do not store events in the database")
    p.add_argument("--db-path", help="override database.path")
    p.add_argument("--no-dashboard", action="store_true", help="do not start the web dashboard")
    p.add_argument("--no-sound", action="store_true", help="never play the alert sound")
    p.add_argument("--host", help="override dashboard.host (default 127.0.0.1 = this computer only)")
    p.add_argument("--port", type=int, help="override dashboard.port")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def config_from_args(args: argparse.Namespace) -> AppConfig:
    calibration = False if args.no_calibration else (args.calibration or True)
    cfg = load_config(args.config, args.override_config, calibration)
    return cfg.with_overrides({
        "camera": {"index": args.camera_index, "width": args.width, "height": args.height,
                   "backend": args.camera_backend},
        "pose": {"model_variant": args.model_variant},
        "display": {"show_window": False if args.no_window else None,
                    "mirror": False if args.no_mirror else None},
        "database": {"enabled": False if args.no_db else None, "path": args.db_path},
        "dashboard": {"enabled": False if args.no_dashboard else None, "host": args.host,
                      "port": args.port},
        "sound": {"enabled": False if args.no_sound else None},
    })


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    try:
        config = config_from_args(args)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return EXIT_CONFIG_ERROR

    log.info("Config: %s", " + ".join(Path(f).name for f in config.source_files))
    log.info("Calibration: %s", ", ".join(f"{k}={v:g}" for k, v in calibration_values(config).items()))

    if not config.display.show_window and args.max_frames is None and args.max_seconds is None:
        log.info("Running without a window; press Ctrl+C to stop.")

    # Import here so a config error is reported even if MediaPipe is broken.
    from moeen.pose.pose_estimator import MediaPipePoseEstimator, PoseEstimatorError

    from moeen.database import Database, DatabaseError

    events: EventRecorder | None = None
    repo: EventRepository | None = None
    if config.database.enabled:
        try:
            db = Database(config.database.path_resolved())
        except DatabaseError as exc:
            log.error("Database error: %s", exc)
            return EXIT_DATABASE_ERROR
        repo = EventRepository(db)
        events = EventRecorder(repo)
        log.info("Event database: %s (%d events stored, %d open)", db.path,
                 repo.count_events(), repo.count_events(open_only=True))
    else:
        log.info("Event database disabled - incidents will not be stored.")

    store: StatusStore | None = None
    server = None
    bridge: DashboardBridge | None = None
    if config.dashboard.enabled:
        from moeen.api import DashboardError, DashboardServer, create_app
        store = StatusStore()
        try:
            server = DashboardServer(create_app(config, store, repo), config.dashboard.host,
                                     config.dashboard.port).start()
        except DashboardError as exc:
            log.error("Dashboard error: %s (or run with --no-dashboard)", exc)
            if events is not None:
                events.shutdown()
            return EXIT_DASHBOARD_ERROR
        bridge = DashboardBridge(store, config.dashboard, repo=repo, events=events)
        log.info("Dashboard: open %s in a browser on this computer", server.url)
    else:
        log.info("Dashboard disabled.")

    # The sound player is optional in every way: if this computer has no audio output it
    # logs why, and alerts stay visual (window + dashboard).
    player = SoundPlayer(config.sound).start()
    alerts = AlertManager(config.sound, player)

    estimator = None
    window = None
    recorder = None
    try:
        with sigterm_as_keyboard_interrupt():   # kill <pid> behaves like Ctrl+C
            estimator = MediaPipePoseEstimator(config.pose)  # fail fast before touching the camera
            with Webcam(config.camera) as camera:
                if config.display.show_window:
                    window = PreviewWindow(config.display.window_name)
                if args.record:
                    recorder = PoseRecorder(args.record, recording_metadata(config, camera, args.label))
                    log.info("Recording pose landmarks to %s", args.record)
                log.info("Preview running. Quit with q / Esc, by closing the window, or Ctrl+C. "
                         "Keys: a = assistance recorded, m = mute sound, d = evidence overlay.")
                if store is not None:
                    store.set_pipeline_running(True)
                stats = run_preview(config, camera, estimator, max_frames=args.max_frames,
                                    max_seconds=args.max_seconds, window=window,
                                    extractor=FeatureExtractor(config.features), recorder=recorder,
                                    detector=AssistanceDetector(config.fall_detection, config.immobility),
                                    events=events, bridge=bridge, alerts=alerts,
                                    debug_overlay=args.debug_overlay)
    except PoseEstimatorError as exc:
        log.error("Pose estimator error: %s", exc)
        return EXIT_POSE_ERROR
    except CameraError as exc:
        log.error("Camera error: %s", exc)
        return EXIT_CAMERA_ERROR
    except DisplayError as exc:
        log.error("Display error: %s", exc)
        return EXIT_DISPLAY_ERROR
    except KeyboardInterrupt:
        log.info("Interrupted (Ctrl+C or stop signal) - shut down cleanly.")
        return EXIT_OK
    finally:
        # Order matters: stop accepting dashboard actions first (pending ones get a clear
        # error), then the web server, then close monitoring-only events and release devices.
        if store is not None:
            store.set_pipeline_running(False)
            store.stop()
        if server is not None:
            server.stop()
            log.info("Dashboard stopped.")
        player.close()
        if events is not None:
            events.shutdown()
            if events.errors:
                log.warning("%d event change(s) could not be stored (see errors above)", events.errors)
        if recorder is not None:
            recorder.close()
            log.info("Saved %d frames to %s", recorder.frames_written, recorder.path)
        if window is not None:
            window.close()
        if estimator is not None:
            estimator.close()

    log.info("Stopped (%s). frames=%d  avg_fps=%.1f  pose_detected_in=%.0f%% of frames",
             stats.stop_reason, stats.frames, stats.average_fps, 100 * stats.pose_rate)
    n_alerts = sum(1 for t in stats.transitions if t.to_state is DetectionState.ALERT)
    log.info("Detector: %d state transitions, %d alert(s), alert sound played %d time(s)",
             len(stats.transitions), n_alerts, player.plays)
    return EXIT_OK


def recording_metadata(config: AppConfig, camera: Webcam, label: str) -> dict:
    """Header stored at the top of a pose recording."""
    try:
        from moeen.pose.pose_estimator import mediapipe_version
        mp_version = mediapipe_version()
    except Exception:  # noqa: BLE001 - metadata only
        mp_version = "unknown"
    return {
        "label": label,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "moeen_version": __version__,
        "mediapipe_version": mp_version,
        "model_variant": config.pose.model_variant,
        "camera_index": config.camera.index,
        "frame_width": camera.actual_width,
        "frame_height": camera.actual_height,
    }


if __name__ == "__main__":
    sys.exit(main())
