"""Turns detector output into stored events (the event lifecycle, PRD section 6 + 9).

The detector knows nothing about the database; this class watches the transitions it
reports and calls the repository:

    detector transition                       event row
    ----------------------------------------  ------------------------------------------
    -> RECOVERY_WINDOW / MONITORING           create, status MONITORING
    -> ALERT                                  status NEW, type/severity/score updated
    RECOVERY_WINDOW/MONITORING -> NORMAL      RESOLVED (resolution RECOVERED)
    MONITORING -> POSSIBLE_FALL               RESOLVED (resolution SUPERSEDED)
    -> RESOLVED (assistance recorded)         ASSISTANCE_RECORDED
    -> RESOLVED (recovered after alert)       RESOLVED (resolution RECOVERED_AFTER_ALERT)
    POSSIBLE_FALL -> NORMAL (not confirmed)   nothing stored (too brief to be an event)

Durations come from detector timestamps (seconds since the incident's first evidence).
Database failures are logged and counted but never stop the detection loop.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from moeen.database import (DatabaseError, Event, EventNotFound, EventRepository, EventStatus,
                            InvalidStatusTransition)
from moeen.detection import DetectionState, DetectorOutput, Incident, Resolution, Transition
from moeen.detection.states import STATE_RISK

log = logging.getLogger(__name__)
S = DetectionState

_DB_ERRORS = (sqlite3.Error, DatabaseError, EventNotFound, InvalidStatusTransition, ValueError)


def new_session_id() -> str:
    """Identifies one application run; incident numbers restart at 1 each run."""
    return datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]


class EventRecorder:
    def __init__(self, repo: EventRepository, session_id: str | None = None) -> None:
        self.repo = repo
        self.session_id = session_id or new_session_id()
        self._open: dict[int, int] = {}                     # incident_id -> event_id
        self._history: dict[int, list[dict[str, Any]]] = {}  # incident_id -> transitions
        self.errors = 0

    @property
    def open_event_ids(self) -> list[int]:
        return list(self._open.values())

    def event_id_for_incident(self, incident_id: int) -> int | None:
        """Database id of the open event for a detector incident (None if not stored)."""
        return self._open.get(incident_id)

    def live_event(self, out: DetectorOutput) -> dict[str, Any] | None:
        """``{"id", "status"}`` of the stored event for the incident in progress, else None.

        The row is kept in step with the detector (NEW while alerting, MONITORING before
        that), so this needs no database read on every frame.
        """
        inc = out.incident
        if inc is None or inc.resolution is not None:
            return None
        event_id = self._open.get(inc.incident_id)
        if event_id is None:
            return None
        status = EventStatus.NEW if out.state is S.ALERT else EventStatus.MONITORING
        return {"id": event_id, "status": status.value}

    # ------------------------------------------------------------------ main entry
    def handle(self, out: DetectorOutput, user_action: str | None = None,
               user_note: str | None = None) -> list[Event]:
        """Store the effects of this frame's transitions. Returns events created/changed.

        ``user_action`` ("assistance" or "resolve") and ``user_note`` describe a dashboard
        action that caused this output (an acknowledgement of the live incident).
        """
        changed: list[Event] = []
        for tr in out.transitions:
            try:
                events = self._apply(tr, out, user_action, user_note)
            except _DB_ERRORS as exc:
                self.errors += 1
                log.error("Could not store event change (%s -> %s): %s",
                          tr.from_state.value, tr.to_state.value, exc)
                continue
            for ev in events:
                log.info("Event #%d %s: status %s%s", ev.id, ev.event_type.value, ev.status.value,
                         f" ({ev.resolution})" if ev.resolution and ev.resolution != ev.status.value else "")
            changed.extend(events)
        return changed

    def shutdown(self) -> list[Event]:
        """Close events that were only being *monitored* when the app stops.

        Alerts that nobody has responded to (status NEW) are left open on purpose: an
        unanswered alert must stay visible on the dashboard after a restart.
        """
        closed: list[Event] = []
        for incident_id, event_id in list(self._open.items()):
            try:
                ev = self.repo.get_event(event_id)
                if ev.status is EventStatus.MONITORING:
                    closed.append(self.repo.resolve_event(event_id, resolution="MONITORING_STOPPED",
                                                          note="application stopped"))
                    self._open.pop(incident_id, None)
            except _DB_ERRORS as exc:
                self.errors += 1
                log.error("Could not close event %s on shutdown: %s", event_id, exc)
        return closed

    # ------------------------------------------------------------------ helpers
    def _remember(self, inc: Incident, tr: Transition) -> list[dict[str, Any]]:
        hist = self._history.setdefault(inc.incident_id, [])
        hist.append({"t_ms": tr.timestamp_ms, "from": tr.from_state.value, "to": tr.to_state.value,
                     "reason": tr.reason})
        return hist

    @staticmethod
    def _duration(inc: Incident, t_ms: int) -> float:
        return max(0.0, (t_ms - inc.started_ms) / 1000)

    @staticmethod
    def _incident_details(inc: Incident) -> dict[str, Any]:
        return {"condition": inc.condition.value, "incident_id": inc.incident_id,
                "follows_fall_candidate": inc.follows_fall_candidate,
                "peak_down_velocity": inc.peak_down_velocity,
                "torso_angle_rise_deg": inc.torso_angle_rise_deg}

    def _create(self, inc: Incident, tr: Transition, out: DetectorOutput, status: EventStatus) -> Event:
        severity = STATE_RISK[tr.to_state] if tr.to_state is not S.ALERT else (inc.severity or STATE_RISK[S.ALERT])
        ev = self.repo.create_event(
            inc.condition.value, severity.value, min(1.0, max(0.0, inc.max_score)),
            status=status, duration_seconds=self._duration(inc, tr.timestamp_ms),
            details={**self._incident_details(inc), "transitions": self._remember(inc, tr)},
            session_id=self.session_id, incident_id=inc.incident_id, note=tr.reason)
        self._open[inc.incident_id] = ev.id
        return ev

    def _close_superseded(self, keep_incident: int | None, tr: Transition) -> list[Event]:
        out: list[Event] = []
        for incident_id, event_id in list(self._open.items()):
            if incident_id != keep_incident:
                out.append(self.repo.resolve_event(event_id, resolution=Resolution.SUPERSEDED.value,
                                                   note=tr.reason))
                self._open.pop(incident_id)
        return out

    def _apply(self, tr: Transition, out: DetectorOutput, user_action: str | None = None,
               user_note: str | None = None) -> list[Event]:
        inc = out.incident
        if inc is None:
            return []
        t = tr.timestamp_ms
        event_id = self._open.get(inc.incident_id)

        if tr.to_state in (S.RECOVERY_WINDOW, S.MONITORING):
            if event_id is None:
                return [self._create(inc, tr, out, EventStatus.MONITORING)]
            return []

        if tr.to_state is S.POSSIBLE_FALL:
            # a fall starting during monitoring replaces the monitoring incident
            return self._close_superseded(inc.incident_id, tr)

        if tr.to_state is S.ALERT:
            if event_id is None:
                return [self._create(inc, tr, out, EventStatus.NEW)]
            hist = self._remember(inc, tr)
            evidence = out.evidence
            self.repo.update_event(
                event_id, event_type=inc.condition.value,
                severity=(inc.severity or STATE_RISK[S.ALERT]).value,
                score=min(1.0, max(0.0, inc.max_score)),
                details_update={**self._incident_details(inc), "transitions": hist,
                                "evidence_at_alert": {
                                    "posture": evidence.posture,
                                    "abnormal_posture_fraction": evidence.abnormal_posture_fraction,
                                    "mean_motion": evidence.mean_motion,
                                    "low_sustained_s": evidence.low_sustained_s,
                                    "still_sustained_s": evidence.still_sustained_s}})
            return [self.repo.update_status(event_id, EventStatus.NEW, note=tr.reason,
                                            duration_seconds=self._duration(inc, t))]

        if event_id is None:
            return []                       # e.g. a candidate that was never confirmed

        if tr.to_state in (S.NORMAL, S.RESOLVED):
            hist = self._remember(inc, tr)
            self.repo.update_event(event_id, score=min(1.0, max(0.0, inc.max_score)),
                                   details_update={"transitions": hist})
            self._open.pop(inc.incident_id, None)
            if inc.resolution is Resolution.ASSISTANCE_RECORDED:
                note = user_note or tr.reason
                if user_action == "resolve":
                    return [self.repo.resolve_event(event_id, resolution="RESOLVED_BY_USER", note=note,
                                                    duration_seconds=self._duration(inc, t))]
                return [self.repo.record_assistance(event_id, note=note,
                                                    duration_seconds=self._duration(inc, t))]
            resolution = inc.resolution.value if inc.resolution else "RESOLVED"
            return [self.repo.resolve_event(event_id, resolution=resolution, note=tr.reason,
                                            duration_seconds=self._duration(inc, t))]
        return []
