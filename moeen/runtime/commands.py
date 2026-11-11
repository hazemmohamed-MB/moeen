"""Apply dashboard commands on the processing-loop thread.

If the command targets the event of the incident the detector is handling right now, the
detector itself is acknowledged (so it leaves MONITORING/RECOVERY_WINDOW/ALERT) and the
EventRecorder stores the result. Otherwise (an older event, e.g. from a previous run) the
repository is updated directly.
"""

from __future__ import annotations

from moeen.alerts import EventRecorder
from moeen.database import Event, EventRepository
from moeen.detection import AssistanceDetector, DetectionState, DetectorOutput

ACTIONS = ("assistance", "resolve")
_LIVE_STATES = (DetectionState.RECOVERY_WINDOW, DetectionState.MONITORING, DetectionState.ALERT)


def apply_command(kind: str, event_id: int, note: str | None, *, repo: EventRepository,
                  detector: AssistanceDetector | None, events: EventRecorder | None,
                  timestamp_ms: int | None = None) -> tuple[Event, DetectorOutput | None]:
    """Returns (updated event, detector output if the live incident was acknowledged)."""
    if kind not in ACTIONS:
        raise ValueError(f"unknown action {kind!r}")
    inc = detector.incident if detector is not None else None
    live_event = (events.event_id_for_incident(inc.incident_id)
                  if events is not None and inc is not None and inc.resolution is None else None)
    if live_event == event_id and detector.state in _LIVE_STATES:
        out = detector.acknowledge(timestamp_ms)
        if out is not None:
            events.handle(out, user_action=kind, user_note=note)
            return repo.get_event(event_id), out
    if kind == "assistance":
        return repo.record_assistance(event_id, note=note), None
    return repo.resolve_event(event_id, resolution="RESOLVED_BY_USER", note=note), None
