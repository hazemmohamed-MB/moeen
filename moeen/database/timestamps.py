"""One timestamp format for the whole event history.

Stored format: UTC ISO-8601 with milliseconds and a ``Z`` suffix, always the same width:

    2026-10-04T06:58:12.345Z

* consistent - every row uses UTC, so daylight-saving changes cannot reorder events;
* sortable   - fixed width, so text order == time order (``ORDER BY created_at`` works);
* readable   - plain ISO-8601; :func:`to_local_display` renders it in local time for people.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_ts(dt: datetime) -> str:
    """Aware datetime -> stored string. Naive datetimes are rejected (ambiguous)."""
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(text: str) -> datetime:
    """Stored string -> aware UTC datetime."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def to_local_display(text: str | None) -> str:
    """Stored string -> 'YYYY-MM-DD HH:MM:SS' in this computer's local time zone."""
    if not text:
        return ""
    return parse_ts(text).astimezone().strftime("%Y-%m-%d %H:%M:%S")
