"""Sustained lying/low-posture and immobility evidence (PRD sections 4.2 and 4.3).

This module measures *how long* a person has been low/horizontal and *how long* they have
not moved, using rolling, blip-tolerant timers, and turns those durations into
MONITORING-entry and ALERT-escalation decisions. The state machine in
``moeen.detection.detector`` owns the states; this module only provides evidence and rules.

False-positive rules built in:
* Sitting on a chair and bending are not low/horizontal postures (feature labels UPRIGHT /
  TILTED), so they never start a lying incident.
* Upright stillness (e.g. sitting quietly) can only produce MONITORING, never an ALERT.
* A lying incident needs the posture to be *sustained* (``lying_monitor_seconds``) before
  MONITORING, and much longer before any ALERT, so brief lying transitions never alert.
* Immobility is strong evidence only together with posture: lying + not moving escalates
  sooner than lying alone, a clearly horizontal body sooner than a low one, and a recent
  fall candidate shortens all durations and raises the alert to HIGH.
"""

from __future__ import annotations

from dataclasses import dataclass

from moeen.config import ImmobilityConfig
from moeen.detection.states import Condition, RiskLevel
from moeen.features.models import FeatureFrame, PostureLabel


class SustainTracker:
    """How long a condition has been true, ignoring interruptions up to ``tolerance_s``.

    ``update`` is O(1), so minute-long durations need no frame history. A ``None`` flag
    means "unknown" (e.g. no person visible) and is treated like an interruption: it never
    extends the sustained time and ends it once it lasts longer than the tolerance.
    """

    def __init__(self, tolerance_s: float) -> None:
        self.tolerance_ms = int(round(tolerance_s * 1000))
        self.start_ms: int | None = None
        self.last_true_ms: int | None = None

    def reset(self) -> None:
        self.start_ms = None
        self.last_true_ms = None

    def update(self, t_ms: int, flag: bool | None) -> float:
        if flag:
            if self.start_ms is None or t_ms - self.last_true_ms > self.tolerance_ms:
                self.start_ms = t_ms
            self.last_true_ms = t_ms
        elif self.last_true_ms is not None and t_ms - self.last_true_ms > self.tolerance_ms:
            self.reset()
        return self.sustained_s

    @property
    def sustained_s(self) -> float:
        if self.start_ms is None:
            return 0.0
        return (self.last_true_ms - self.start_ms) / 1000


@dataclass(frozen=True)
class MonitorEvidence:
    """Sustained durations in seconds, as of the latest frame."""

    low_s: float            # low OR horizontal posture
    horizontal_s: float     # horizontal posture
    still_s: float          # motion magnitude <= still_motion_threshold
    normal_posture_s: float  # visible and neither low nor horizontal (e.g. upright, tilted)


class PostureMonitor:
    """Updates the sustained timers from each FeatureFrame."""

    def __init__(self, cfg: ImmobilityConfig) -> None:
        self.cfg = cfg
        self.low = SustainTracker(cfg.posture_tolerance_seconds)
        self.horizontal = SustainTracker(cfg.posture_tolerance_seconds)
        self.still = SustainTracker(cfg.still_tolerance_seconds)
        self.normal = SustainTracker(cfg.posture_tolerance_seconds)

    def reset(self) -> None:
        for tr in (self.low, self.horizontal, self.still, self.normal):
            tr.reset()

    def update(self, f: FeatureFrame) -> MonitorEvidence:
        t = f.timestamp_ms
        known = f.pose_present and f.posture is not PostureLabel.UNKNOWN
        low = f.is_low_or_horizontal if known else None
        horizontal = (f.posture is PostureLabel.HORIZONTAL) if known else None
        still = None if f.motion_magnitude is None else f.motion_magnitude <= self.cfg.still_motion_threshold
        normal = (not f.is_low_or_horizontal) if known else None
        return MonitorEvidence(
            low_s=self.low.update(t, low),
            horizontal_s=self.horizontal.update(t, horizontal),
            still_s=self.still.update(t, still),
            normal_posture_s=self.normal.update(t, normal),
        )


@dataclass(frozen=True)
class Escalation:
    condition: Condition
    severity: RiskLevel
    reason: str


@dataclass(frozen=True)
class _Rule:
    name: str
    condition: Condition
    required_s: float       # after the recent-candidate factor
    current_s: float
    active: bool            # posture part of the rule currently holds


def _rules(m: MonitorEvidence, cfg: ImmobilityConfig, recent_candidate: bool) -> list[_Rule]:
    f = cfg.recent_candidate_factor if recent_candidate else 1.0
    rules = [
        _Rule("lying and not moving", Condition.IMMOBILITY, cfg.horizontal_still_alert_seconds * f,
              min(m.horizontal_s, m.still_s), m.horizontal_s > 0),
        _Rule("low posture and not moving", Condition.IMMOBILITY, cfg.low_still_alert_seconds * f,
              min(m.low_s, m.still_s), m.low_s > 0),
    ]
    if cfg.horizontal_alert_seconds > 0:
        rules.append(_Rule("lying", Condition.LYING, cfg.horizontal_alert_seconds * f,
                           m.horizontal_s, m.horizontal_s > 0))
    return rules


def monitor_entry(m: MonitorEvidence, cfg: ImmobilityConfig) -> tuple[Condition, str] | None:
    """Should a MONITORING incident start? Returns (condition, reason) or None."""
    if m.low_s >= cfg.lying_monitor_seconds:
        return Condition.LYING, f"low/horizontal posture sustained for {m.low_s:.1f} s"
    if cfg.upright_still_monitor_seconds > 0 and m.still_s >= cfg.upright_still_monitor_seconds:
        return Condition.IMMOBILITY, f"no movement for {m.still_s:.0f} s (upright)"
    return None


def check_escalation(m: MonitorEvidence, cfg: ImmobilityConfig,
                     recent_candidate: bool) -> Escalation | None:
    """First alert rule that is satisfied, or None. Rules are ordered strongest first."""
    severity = RiskLevel.HIGH if recent_candidate else RiskLevel.MEDIUM
    for r in _rules(m, cfg, recent_candidate):
        if r.active and r.current_s >= r.required_s:
            suffix = " after a fall candidate" if recent_candidate else ""
            return Escalation(r.condition, severity, f"{r.name} for {r.current_s:.0f} s{suffix}")
    return None


def time_to_escalation(m: MonitorEvidence, cfg: ImmobilityConfig,
                       recent_candidate: bool) -> tuple[float, str] | None:
    """Seconds until the nearest currently-applicable alert rule fires (if nothing changes)."""
    best: tuple[float, str] | None = None
    for r in _rules(m, cfg, recent_candidate):
        if not r.active:
            continue
        remaining = max(0.0, r.required_s - r.current_s)
        if best is None or remaining < best[0]:
            best = (remaining, r.name)
    return best


def escalation_progress(m: MonitorEvidence, cfg: ImmobilityConfig, recent_candidate: bool) -> float:
    """0..1 progress toward the nearest applicable alert rule (for the system score)."""
    vals = [min(1.0, r.current_s / r.required_s) for r in _rules(m, cfg, recent_candidate) if r.active]
    return max(vals, default=0.0)
