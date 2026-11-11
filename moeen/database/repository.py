"""Event repository: the only module that writes SQL for events.

Safety rules:
* Every value goes through a ``?`` placeholder - SQL text is never built from input.
  (The only formatted pieces are fixed column names chosen in this file.)
* Every value is validated before it reaches SQLite (enums, score range, JSON details),
  and the schema repeats the key checks as CHECK constraints.
* Status changes follow ``ALLOWED_STATUS_TRANSITIONS`` and are checked and applied inside
  one IMMEDIATE transaction, so two writers cannot both "resolve" the same event.
* Every status change is appended to ``event_status_log``.
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Iterable, Mapping

from moeen.database.db import Database
from moeen.database.models import (ALLOWED_STATUS_TRANSITIONS, OPEN_STATUSES, Event, EventStatus,
                                   EventType, Severity, StatusChange)
from moeen.database.timestamps import Clock, format_ts, utc_now

MAX_NOTE_LENGTH = 500
MAX_LIST_LIMIT = 1000


class EventNotFound(LookupError):
    """No event with the given id."""


class InvalidStatusTransition(ValueError):
    """The requested status change is not allowed from the event's current status."""


# ---------------------------------------------------------------- validation helpers
def _enum(cls, value, name: str):
    try:
        return value if isinstance(value, cls) else cls(value)
    except ValueError:
        allowed = ", ".join(m.value for m in cls)
        raise ValueError(f"invalid {name} {value!r}; allowed: {allowed}") from None


def _score(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not 0.0 <= value <= 1.0:
        raise ValueError(f"score must be a number between 0 and 1 (got {value!r})")
    return float(value)


def _duration(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or value < 0:
        raise ValueError(f"duration_seconds must be a non-negative number (got {value!r})")
    return float(value)


def _details_json(details: Mapping[str, Any] | None) -> str:
    if details is None:
        return "{}"
    if not isinstance(details, Mapping):
        raise ValueError("details must be a mapping (dict)")
    try:
        return json.dumps(dict(details), allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"details must be JSON-serializable: {exc}") from exc


def _note(note: str | None) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    return note[:MAX_NOTE_LENGTH]


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"], event_type=EventType(row["event_type"]), created_at=row["created_at"],
        updated_at=row["updated_at"], resolved_at=row["resolved_at"],
        severity=Severity(row["severity"]), score=row["score"],
        duration_seconds=row["duration_seconds"], status=EventStatus(row["status"]),
        resolution=row["resolution"], session_id=row["session_id"],
        incident_id=row["incident_id"], details=json.loads(row["details_json"] or "{}"))


class EventRepository:
    """Create, read, update and resolve alert events."""

    def __init__(self, db: Database, clock: Clock = utc_now) -> None:
        self.db = db
        self._clock = clock

    def _now(self) -> str:
        return format_ts(self._clock())

    # ------------------------------------------------------------------ create
    def create_event(self, event_type: EventType | str, severity: Severity | str, score: float, *,
                     status: EventStatus | str = EventStatus.NEW,
                     duration_seconds: float | None = None,
                     details: Mapping[str, Any] | None = None,
                     session_id: str | None = None, incident_id: int | None = None,
                     note: str | None = None) -> Event:
        """Insert a new event (and its first status-log entry). Returns the stored event."""
        etype = _enum(EventType, event_type, "event_type")
        sev = _enum(Severity, severity, "severity")
        st = _enum(EventStatus, status, "status")
        if st not in OPEN_STATUSES:
            raise ValueError("new events must start as MONITORING or NEW")
        values = (etype.value, sev.value, _score(score), _duration(duration_seconds), st.value,
                  session_id, incident_id, _details_json(details))
        now = self._now()
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO events (event_type, severity, score, duration_seconds, status, "
                "session_id, incident_id, details_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (*values, now, now))
            event_id = cur.lastrowid
            conn.execute("INSERT INTO event_status_log (event_id, changed_at, from_status, to_status, note) "
                         "VALUES (?, ?, NULL, ?, ?)", (event_id, now, st.value, _note(note)))
            return self._get(conn, event_id)

    # ------------------------------------------------------------------ read
    @staticmethod
    def _get(conn: sqlite3.Connection, event_id: int) -> Event:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise EventNotFound(f"no event with id {event_id}")
        return _row_to_event(row)

    def get_event(self, event_id: int) -> Event:
        with self.db.read() as conn:
            return self._get(conn, int(event_id))

    def find_by_incident(self, session_id: str, incident_id: int) -> Event | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM events WHERE session_id = ? AND incident_id = ?",
                               (session_id, incident_id)).fetchone()
        return None if row is None else _row_to_event(row)

    @staticmethod
    def _filters(status, event_type, open_only) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        statuses: list[EventStatus] = []
        if status is not None:
            items = [status] if isinstance(status, (str, EventStatus)) else list(status)
            statuses = [_enum(EventStatus, s, "status") for s in items]
        if open_only:
            statuses = [s for s in (statuses or OPEN_STATUSES) if s in OPEN_STATUSES]
            if not statuses:
                return "WHERE 0", []
        if statuses:
            clauses.append(f"status IN ({', '.join('?' for _ in statuses)})")
            params += [s.value for s in statuses]
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(_enum(EventType, event_type, "event_type").value)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def list_events(self, *, limit: int = 50, offset: int = 0,
                    status: EventStatus | str | Iterable[EventStatus | str] | None = None,
                    event_type: EventType | str | None = None,
                    open_only: bool = False) -> list[Event]:
        """Events, newest first, optionally filtered by status / type / open-only."""
        if not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_LIST_LIMIT}")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        where, params = self._filters(status, event_type, open_only)
        with self.db.read() as conn:
            rows = conn.execute(f"SELECT * FROM events {where} ORDER BY created_at DESC, id DESC "
                                "LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return [_row_to_event(r) for r in rows]

    def count_events(self, *, status=None, event_type=None, open_only: bool = False) -> int:
        where, params = self._filters(status, event_type, open_only)
        with self.db.read() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM events {where}", params).fetchone()[0]

    def status_history(self, event_id: int) -> list[StatusChange]:
        """All status changes of an event, oldest first."""
        with self.db.read() as conn:
            self._get(conn, int(event_id))
            rows = conn.execute("SELECT * FROM event_status_log WHERE event_id = ? ORDER BY id",
                                (int(event_id),)).fetchall()
        return [StatusChange(id=r["id"], event_id=r["event_id"], changed_at=r["changed_at"],
                             from_status=EventStatus(r["from_status"]) if r["from_status"] else None,
                             to_status=EventStatus(r["to_status"]), note=r["note"]) for r in rows]

    # ------------------------------------------------------------------ update
    def update_event(self, event_id: int, *, event_type: EventType | str | None = None,
                     severity: Severity | str | None = None, score: float | None = None,
                     duration_seconds: float | None = None,
                     details_update: Mapping[str, Any] | None = None) -> Event:
        """Update descriptive fields (not the status). ``details_update`` is merged into
        the existing details (top-level keys replaced)."""
        sets: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            sets.append("event_type = ?")
            params.append(_enum(EventType, event_type, "event_type").value)
        if severity is not None:
            sets.append("severity = ?")
            params.append(_enum(Severity, severity, "severity").value)
        if score is not None:
            sets.append("score = ?")
            params.append(_score(score))
        if duration_seconds is not None:
            sets.append("duration_seconds = ?")
            params.append(_duration(duration_seconds))
        if details_update is not None:
            _details_json(details_update)   # validate before opening the transaction
        with self.db.transaction() as conn:
            current = self._get(conn, int(event_id))
            if details_update is not None:
                sets.append("details_json = ?")
                params.append(_details_json({**current.details, **details_update}))
            if sets:
                sets.append("updated_at = ?")
                params.append(self._now())
                conn.execute(f"UPDATE events SET {', '.join(sets)} WHERE id = ?",
                             (*params, int(event_id)))
            return self._get(conn, int(event_id))

    def update_status(self, event_id: int, new_status: EventStatus | str, *,
                      note: str | None = None, resolution: str | None = None,
                      duration_seconds: float | None = None) -> Event:
        """Change the status if the lifecycle allows it; logs the change.

        Leaving the open statuses (MONITORING/NEW) sets ``resolved_at`` the first time.

        Raises:
            EventNotFound, InvalidStatusTransition, ValueError.
        """
        target = _enum(EventStatus, new_status, "status")
        dur = _duration(duration_seconds)
        note = _note(note)
        with self.db.transaction() as conn:
            current = self._get(conn, int(event_id))
            if target not in ALLOWED_STATUS_TRANSITIONS[current.status]:
                raise InvalidStatusTransition(
                    f"event {event_id}: {current.status.value} -> {target.value} is not allowed")
            now = self._now()
            closing = target not in OPEN_STATUSES and current.resolved_at is None
            conn.execute(
                "UPDATE events SET status = ?, updated_at = ?, "
                "resolved_at = COALESCE(resolved_at, ?), "
                "resolution = COALESCE(?, resolution), "
                "duration_seconds = COALESCE(?, duration_seconds) "
                "WHERE id = ? AND status = ?",
                (target.value, now, now if closing else None, resolution, dur,
                 int(event_id), current.status.value))
            conn.execute("INSERT INTO event_status_log (event_id, changed_at, from_status, to_status, note) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (int(event_id), now, current.status.value, target.value, note))
            return self._get(conn, int(event_id))

    def resolve_event(self, event_id: int, *, resolution: str = "RESOLVED", note: str | None = None,
                      duration_seconds: float | None = None) -> Event:
        """Close an event (status RESOLVED) with a resolution reason."""
        if not isinstance(resolution, str) or not resolution.strip():
            raise ValueError("resolution must be a non-empty string")
        return self.update_status(event_id, EventStatus.RESOLVED, note=note,
                                  resolution=resolution.strip()[:64],
                                  duration_seconds=duration_seconds)

    def record_assistance(self, event_id: int, *, note: str | None = None,
                          duration_seconds: float | None = None) -> Event:
        """Mark that a person gave assistance (the dashboard's "Assistance recorded")."""
        return self.update_status(event_id, EventStatus.ASSISTANCE_RECORDED, note=note,
                                  resolution="ASSISTANCE_RECORDED", duration_seconds=duration_seconds)
