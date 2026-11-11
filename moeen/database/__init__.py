"""Local SQLite event history (PRD section 9).

The detector never imports this package; ``moeen.alerts.event_recorder`` translates detector
output into repository calls, so detection stays testable without a database.
"""

from moeen.database.db import SCHEMA_VERSION, Database, DatabaseError
from moeen.database.models import Event, EventStatus, EventType, Severity, StatusChange
from moeen.database.repository import EventNotFound, EventRepository, InvalidStatusTransition

__all__ = ["SCHEMA_VERSION", "Database", "DatabaseError", "Event", "EventNotFound",
           "EventRepository", "EventStatus", "EventType", "InvalidStatusTransition",
           "Severity", "StatusChange"]
