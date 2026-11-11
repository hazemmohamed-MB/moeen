"""Connects the processing loop to the dashboard (runs on the processing-loop thread).

Each frame the loop calls :meth:`DashboardBridge.step`, which

1. applies dashboard actions queued by the web server (the loop is the only writer of the
   detector and of live events, so there are no races),
2. publishes the status snapshot for ``/api/status``, and
3. every ``1 / preview_fps`` seconds, JPEG-encodes the annotated frame for ``/video_feed``.

The web server never touches the camera, the pose model or the detector.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import cv2
import numpy as np

from moeen.alerts import EventRecorder
from moeen.config import DashboardConfig
from moeen.database import EventRepository
from moeen.detection import AssistanceDetector, DetectorOutput
from moeen.features import FeatureFrame
from moeen.runtime.commands import apply_command
from moeen.runtime.snapshot import build_snapshot
from moeen.runtime.status_store import StatusStore

log = logging.getLogger(__name__)


class DashboardBridge:
    def __init__(self, store: StatusStore, config: DashboardConfig, *,
                 repo: EventRepository | None, events: EventRecorder | None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.store = store
        self.config = config
        self.repo = repo
        self.events = events
        self._clock = clock
        self._next_preview = 0.0
        self.previews_sent = 0
        self.commands_applied = 0

    # ------------------------------------------------------------------ commands
    def apply_commands(self, detector: AssistanceDetector | None,
                       timestamp_ms: int | None) -> DetectorOutput | None:
        """Apply queued dashboard actions. Returns the detector output of the last action that
        acknowledged the live incident (so the loop can show it this frame), else None."""
        acked: DetectorOutput | None = None
        for cmd in self.store.drain():
            if self.repo is None:
                cmd.finish(error=RuntimeError("the event database is disabled"))
                continue
            try:
                event, out = apply_command(cmd.kind, cmd.event_id, cmd.note, repo=self.repo,
                                           detector=detector, events=self.events,
                                           timestamp_ms=timestamp_ms)
            except Exception as exc:  # noqa: BLE001 - reported to the HTTP caller, loop goes on
                cmd.finish(error=exc)
                continue
            self.commands_applied += 1
            if out is not None:
                acked = out
            log.info("Dashboard: %s recorded for event %d%s", cmd.kind, event.id,
                     " (live incident)" if out is not None else "")
            cmd.finish(result=(event, out))
        return acked

    # ------------------------------------------------------------------ status + preview
    def live_event(self, detection: DetectorOutput) -> dict | None:
        """The stored event of the incident in progress, as shown on the dashboard."""
        return self.events.live_event(detection) if self.events is not None else None

    def publish(self, detection: DetectorOutput | None, features: FeatureFrame | None, *,
                fps: float, frame_size: tuple[int, int] | None,
                sound: dict | None = None) -> None:
        if detection is None:
            return
        self.store.publish(build_snapshot(detection, features, fps=fps, frame_size=frame_size,
                                          event=self.live_event(detection), sound=sound))

    def preview_due(self) -> bool:
        return self.config.preview_enabled and self._clock() >= self._next_preview

    def send_preview(self, image: np.ndarray) -> bool:
        """JPEG-encode ``image`` for the dashboard. Returns True if a frame was published."""
        self._next_preview = self._clock() + 1.0 / self.config.preview_fps
        ok, jpg = cv2.imencode(".jpg", image,
                               [cv2.IMWRITE_JPEG_QUALITY, self.config.preview_jpeg_quality])
        if not ok:
            return False
        self.store.set_frame(jpg.tobytes())
        self.previews_sent += 1
        return True

    def step(self, detector: AssistanceDetector | None, detection: DetectorOutput | None,
             features: FeatureFrame | None, *, fps: float,
             frame_size: tuple[int, int] | None) -> DetectorOutput | None:
        """Apply dashboard actions and publish the status. Returns the detector output to
        display (the acknowledged output if a dashboard action closed the live incident).

        Preview frames are sent separately (:meth:`preview_due` / :meth:`send_preview`) so the
        loop draws the annotated frame at most once, and only when someone needs it.
        """
        timestamp_ms = features.timestamp_ms if features is not None else None
        acked = self.apply_commands(detector, timestamp_ms)
        if acked is not None:
            detection = acked
        self.publish(detection, features, fps=fps, frame_size=frame_size)
        return detection
