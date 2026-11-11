"""Everything that happens to one frame *after* pose estimation - no camera, no model.

    FeatureFrame -> detector -> stored events -> dashboard actions -> alert sound -> status

The live app (``moeen.app``) feeds it features from the webcam; tests feed it synthetic
feature sequences, so the integration of these components is tested exactly as it runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from moeen.alerts import AlertManager, EventRecorder
from moeen.detection import AssistanceDetector, DetectorOutput, Transition
from moeen.features import FeatureFrame
from moeen.runtime.bridge import DashboardBridge

log = logging.getLogger(__name__)


@dataclass
class FrameResult:
    output: DetectorOutput                 # what to display (after any acknowledgement)
    transitions: list[Transition] = field(default_factory=list)   # all of this frame
    event: dict | None = None              # {"id", "status"} of the live stored event


class ProcessingPipeline:
    def __init__(self, detector: AssistanceDetector, *, events: EventRecorder | None = None,
                 alerts: AlertManager | None = None,
                 bridge: DashboardBridge | None = None) -> None:
        self.detector = detector
        self.events = events
        self.alerts = alerts
        self.bridge = bridge
        self.last: FrameResult | None = None

    def process(self, features: FeatureFrame, *, fps: float = 0.0,
                frame_size: tuple[int, int] | None = None) -> FrameResult:
        out = self.detector.update(features)
        transitions = list(out.transitions)
        if self.events is not None:
            self.events.handle(out)
        if self.bridge is not None:
            # dashboard buttons are applied here, on the loop thread (single writer)
            acked = self.bridge.apply_commands(self.detector, features.timestamp_ms)
            if acked is not None:
                out = acked
                transitions += acked.transitions
        return self._finish(out, transitions, features, fps, frame_size)

    def acknowledge(self, features: FeatureFrame | None, *, fps: float = 0.0,
                    frame_size: tuple[int, int] | None = None) -> FrameResult | None:
        """'Assistance recorded' from the keyboard (``a`` in the preview window)."""
        ts = features.timestamp_ms if features is not None else None
        acked = self.detector.acknowledge(ts)
        if acked is None:
            return None
        if self.events is not None:
            self.events.handle(acked, user_action="assistance", user_note="recorded with the 'a' key")
        return self._finish(acked, list(acked.transitions), features, fps, frame_size)

    def toggle_mute(self) -> bool | None:
        return self.alerts.toggle_mute() if self.alerts is not None else None

    def sound_status(self) -> dict | None:
        return self.alerts.status() if self.alerts is not None else None

    def _finish(self, out: DetectorOutput, transitions: list[Transition],
                features: FeatureFrame | None, fps: float,
                frame_size: tuple[int, int] | None) -> FrameResult:
        # The sound decision comes after dashboard actions, so an alert answered in this
        # frame never beeps.
        if self.alerts is not None:
            self.alerts.update(out)
        if self.bridge is not None:
            self.bridge.publish(out, features, fps=fps, frame_size=frame_size,
                                sound=self.sound_status())
        event = self.events.live_event(out) if self.events is not None else None
        self.last = FrameResult(out, transitions, event)
        return self.last
