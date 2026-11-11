"""Build the JSON status snapshot the dashboard shows, from one frame's detector output."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from moeen.database.timestamps import format_ts
from moeen.detection import DetectorOutput
from moeen.features import FeatureFrame


def _round(v: float | None, nd: int = 3) -> float | None:
    return None if v is None else round(float(v), nd)


def build_snapshot(detection: DetectorOutput, features: FeatureFrame | None, *, fps: float,
                   frame_size: tuple[int, int] | None, event: dict[str, Any] | None,
                   sound: dict[str, Any] | None = None,
                   wall_now: datetime | None = None) -> dict[str, Any]:
    """Plain-dict status for /api/status.

    Durations come from detector timestamps; wall-clock times are derived from ``wall_now``
    so the dashboard can show "since 10:42:07".
    """
    wall_now = wall_now or datetime.now(timezone.utc)
    inc = detection.incident
    incident = None
    if inc is not None:
        open_ = inc.resolution is None
        end_ms = detection.timestamp_ms if open_ else (inc.resolved_ms or detection.timestamp_ms)
        duration = max(0.0, (end_ms - inc.started_ms) / 1000)
        started_wall = wall_now - timedelta(seconds=(detection.timestamp_ms - inc.started_ms) / 1000)
        incident = {
            "id": inc.incident_id, "open": open_, "condition": inc.condition.value,
            "severity": inc.severity.value if inc.severity else None,
            "started_at": format_ts(started_wall), "duration_s": round(duration, 1),
            "resolution": inc.resolution.value if inc.resolution else None,
            "follows_fall_candidate": inc.follows_fall_candidate,
        }
    t = detection.timers
    return {
        "state": detection.state.value,
        "condition": detection.condition.value if detection.condition else None,
        "risk_level": detection.risk_level.value,
        "score": round(detection.score, 3),
        "score_components": {k: round(v, 3) for k, v in detection.score_components.items()},
        "status": detection.status,
        "timers": {
            "time_in_state_s": _round(t.time_in_state_s, 1),
            "confirm_remaining_s": _round(t.confirm_remaining_s, 1),
            "recovery_remaining_s": _round(t.recovery_remaining_s, 1),
            "extension_remaining_s": _round(t.extension_remaining_s, 1),
            "escalation_in_s": _round(t.escalation_in_s, 1),
            "alert_elapsed_s": _round(t.alert_elapsed_s, 1),
            "resolved_remaining_s": _round(t.resolved_remaining_s, 1),
        },
        "incident": incident,
        "event": event,
        "sound": sound,
        "person_visible": bool(features.pose_present) if features is not None else False,
        "posture": features.posture.value if features is not None else None,
        "torso_angle_deg": _round(features.torso_angle_deg, 0) if features is not None else None,
        "motion": _round(features.motion_magnitude) if features is not None else None,
        "fps": round(fps, 1),
        "frame": {"width": frame_size[0], "height": frame_size[1]} if frame_size else None,
        "updated_at": format_ts(wall_now),
    }
