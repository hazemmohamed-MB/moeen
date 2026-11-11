"""Structured detector output, designed to be shown on the dashboard and stored as events.

Time units: every absolute time is ``*_ms`` (the frame timestamp, integer milliseconds);
every duration is ``*_s`` (seconds, float).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Any

from moeen.detection.states import Condition, DetectionState, Resolution, RiskLevel


@dataclass(frozen=True)
class Evidence:
    """Measurements the decision is based on (current frame / current windows)."""

    pose_present: bool
    posture: str                          # PostureLabel value of the current frame
    peak_down_velocity: float | None      # torso lengths / s, max in the candidate window
    velocity_above_s: float               # time the velocity exceeded the threshold in the window
    torso_angle_rise_deg: float | None    # torso-angle rise within baseline + candidate window
    low_posture_score: float | None       # current frame, 0..1
    abnormal_posture_fraction: float | None  # share of low/horizontal frames in the lookback
    mean_motion: float | None             # torso lengths, mean motion magnitude in the lookback
    upright_hold_s: float                 # how long the posture has been UPRIGHT continuously
    abnormal_hold_s: float                # how long the posture has been low/horizontal continuously
    # sustained timers (tolerate brief blips; see moeen.detection.immobility_detector)
    low_sustained_s: float = 0.0          # low OR horizontal posture
    horizontal_sustained_s: float = 0.0   # horizontal posture only
    still_sustained_s: float = 0.0        # motion at or below the stillness threshold
    recent_fall_candidate: bool = False   # a fall candidate happened within the configured window


@dataclass(frozen=True)
class Timers:
    """Countdowns/elapsed times for the current state (None when not applicable)."""

    time_in_state_s: float
    confirm_remaining_s: float | None     # POSSIBLE_FALL: time left to confirm
    recovery_elapsed_s: float | None      # RECOVERY_WINDOW/ALERT: time since confirmation
    recovery_remaining_s: float | None    # RECOVERY_WINDOW: time left before escalation check
    extension_remaining_s: float | None   # RECOVERY_WINDOW past its window: time left before forced escalation
    recovery_hold_required_s: float | None  # UPRIGHT hold needed to cancel/resolve in this state
    alert_elapsed_s: float | None         # ALERT: time since the alert was raised
    resolved_remaining_s: float | None    # RESOLVED: time until back to NORMAL
    monitor_elapsed_s: float | None = None    # MONITORING: time since monitoring started
    escalation_in_s: float | None = None      # MONITORING: time until the nearest alert rule fires


@dataclass(frozen=True)
class Incident:
    """One incident (fall, lying or immobility), from its first evidence to its resolution."""

    incident_id: int
    started_ms: int                       # first candidate evidence / start of monitoring
    condition: Condition = Condition.FALL
    severity: RiskLevel | None = None     # set when the alert is raised
    follows_fall_candidate: bool = False  # lying/immobility incident that started soon after a fall candidate
    confirmed_ms: int | None = None       # fall path: entered RECOVERY_WINDOW
    alert_ms: int | None = None
    resolved_ms: int | None = None
    resolution: Resolution | None = None
    peak_down_velocity: float | None = None   # torso lengths / s
    torso_angle_rise_deg: float | None = None
    max_score: float = 0.0


@dataclass(frozen=True)
class Transition:
    timestamp_ms: int
    from_state: DetectionState
    to_state: DetectionState
    reason: str


@dataclass(frozen=True)
class DetectorOutput:
    """Everything the dashboard / alert layer needs about the current frame."""

    timestamp_ms: int
    state: DetectionState
    risk_level: RiskLevel
    score: float                          # rule-based system score 0..1 (not a medical probability)
    score_components: dict[str, float]    # each 0..1, before weighting
    condition: Condition | None           # condition of the active incident (None when none is open)
    evidence: Evidence
    timers: Timers
    incident: Incident | None             # current or most recent incident (None before the first)
    transitions: tuple[Transition, ...]   # transitions that happened on this frame (usually empty)
    status: str                           # one-line human-readable explanation

    @property
    def state_changed(self) -> bool:
        return bool(self.transitions)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation (enums as strings)."""
        def conv(v: Any) -> Any:
            if isinstance(v, Enum):
                return v.value
            if dataclasses.is_dataclass(v):
                return {f.name: conv(getattr(v, f.name)) for f in dataclasses.fields(v)}
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [conv(x) for x in v]
            return v
        out = conv(self)
        out["state_changed"] = self.state_changed
        return out
