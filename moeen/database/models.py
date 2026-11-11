"""Event records as stored in SQLite (PRD section 9 data model)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from moeen.database.timestamps import to_local_display


class EventType(str, Enum):
    FALL = "FALL"
    LYING = "LYING"
    IMMOBILITY = "IMMOBILITY"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EventStatus(str, Enum):
    MONITORING = "MONITORING"                    # being watched; not (yet) an alert
    NEW = "NEW"                                  # alert raised, nobody has responded yet
    ASSISTANCE_RECORDED = "ASSISTANCE_RECORDED"  # a person recorded that help was given
    RESOLVED = "RESOLVED"                        # closed


OPEN_STATUSES: frozenset[EventStatus] = frozenset({EventStatus.MONITORING, EventStatus.NEW})

# Status lifecycle enforced by the repository (RESOLVED is final).
ALLOWED_STATUS_TRANSITIONS: dict[EventStatus, frozenset[EventStatus]] = {
    EventStatus.MONITORING: frozenset({EventStatus.NEW, EventStatus.ASSISTANCE_RECORDED,
                                       EventStatus.RESOLVED}),
    EventStatus.NEW: frozenset({EventStatus.ASSISTANCE_RECORDED, EventStatus.RESOLVED}),
    EventStatus.ASSISTANCE_RECORDED: frozenset({EventStatus.RESOLVED}),
    EventStatus.RESOLVED: frozenset(),
}


@dataclass(frozen=True)
class Event:
    id: int
    event_type: EventType
    created_at: str                 # UTC ISO-8601, see moeen.database.timestamps
    updated_at: str
    resolved_at: str | None
    severity: Severity
    score: float                    # system score 0..1, not a medical probability
    duration_seconds: float | None
    status: EventStatus
    resolution: str | None
    session_id: str | None
    incident_id: int | None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready representation (for the API), including local-time display strings."""
        return {
            "id": self.id, "event_type": self.event_type.value,
            "created_at": self.created_at, "created_at_local": to_local_display(self.created_at),
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at, "resolved_at_local": to_local_display(self.resolved_at),
            "severity": self.severity.value, "score": self.score,
            "duration_seconds": self.duration_seconds, "status": self.status.value,
            "resolution": self.resolution, "session_id": self.session_id,
            "incident_id": self.incident_id, "details": self.details,
        }


@dataclass(frozen=True)
class StatusChange:
    id: int
    event_id: int
    changed_at: str
    from_status: EventStatus | None
    to_status: EventStatus
    note: str | None
