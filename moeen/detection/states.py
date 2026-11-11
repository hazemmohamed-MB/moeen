"""States, conditions, risk levels and incident resolutions of the detection state machine.

One state machine handles every supported case (PRD sections 4 and 6):

    fall path:        NORMAL -> POSSIBLE_FALL -> RECOVERY_WINDOW -> ALERT -> RESOLVED -> NORMAL
    lying/immobility: NORMAL -> MONITORING -> ALERT -> RESOLVED -> NORMAL

The *condition* of an incident says which case it is (PRD data model ``event_type``).
"""

from __future__ import annotations

from enum import Enum


class DetectionState(str, Enum):
    NORMAL = "NORMAL"                    # no sustained abnormal evidence
    POSSIBLE_FALL = "POSSIBLE_FALL"      # fast downward motion + posture change; collecting evidence
    RECOVERY_WINDOW = "RECOVERY_WINDOW"  # fall confirmed enough to watch; waiting for recovery
    MONITORING = "MONITORING"            # sustained lying/low posture or immobility; watching
    ALERT = "ALERT"                      # confirmed abnormal condition (no recovery)
    RESOLVED = "RESOLVED"                # incident closed (recovered or assistance recorded)


class Condition(str, Enum):
    """What kind of incident this is (stored as the event type)."""

    FALL = "FALL"                # fall followed by failure to recover
    LYING = "LYING"              # sustained abnormal lying / low posture
    IMMOBILITY = "IMMOBILITY"    # sustained lack of movement (with posture/candidate context)


class RiskLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Resolution(str, Enum):
    """How an incident ended."""

    NOT_CONFIRMED = "NOT_CONFIRMED"              # POSSIBLE_FALL expired without full evidence
    RECOVERED = "RECOVERED"                      # recovered before any alert (incident cancelled)
    RECOVERED_AFTER_ALERT = "RECOVERED_AFTER_ALERT"
    ASSISTANCE_RECORDED = "ASSISTANCE_RECORDED"  # acknowledged by a person (dashboard button)
    SUPERSEDED = "SUPERSEDED"                    # a monitoring incident replaced by a fall candidate


# Risk per state; ALERT uses the severity stored on the incident (depends on the condition).
STATE_RISK: dict[DetectionState, RiskLevel] = {
    DetectionState.NORMAL: RiskLevel.NONE,
    DetectionState.POSSIBLE_FALL: RiskLevel.LOW,
    DetectionState.RECOVERY_WINDOW: RiskLevel.MEDIUM,
    DetectionState.MONITORING: RiskLevel.LOW,
    DetectionState.ALERT: RiskLevel.HIGH,
    DetectionState.RESOLVED: RiskLevel.NONE,
}

# Allowed transitions; the state machine asserts every transition against this table.
ALLOWED_TRANSITIONS: dict[DetectionState, frozenset[DetectionState]] = {
    DetectionState.NORMAL: frozenset({DetectionState.POSSIBLE_FALL, DetectionState.MONITORING}),
    DetectionState.POSSIBLE_FALL: frozenset({DetectionState.RECOVERY_WINDOW, DetectionState.NORMAL}),
    DetectionState.RECOVERY_WINDOW: frozenset({DetectionState.NORMAL, DetectionState.ALERT,
                                               DetectionState.RESOLVED}),
    DetectionState.MONITORING: frozenset({DetectionState.NORMAL, DetectionState.ALERT,
                                          DetectionState.RESOLVED, DetectionState.POSSIBLE_FALL}),
    DetectionState.ALERT: frozenset({DetectionState.RESOLVED}),
    DetectionState.RESOLVED: frozenset({DetectionState.NORMAL}),
}
