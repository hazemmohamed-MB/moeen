"""Unified detection state machine: falls, sustained lying/low posture and immobility.

    fall path:        NORMAL -> POSSIBLE_FALL -> RECOVERY_WINDOW -> ALERT -> RESOLVED -> NORMAL
                                   |                |
                                   +-> NORMAL       +-> NORMAL (recovered: incident cancelled)
    lying/immobility: NORMAL -> MONITORING -> ALERT -> RESOLVED -> NORMAL
                                    |
                                    +-> NORMAL (recovered)   +-> POSSIBLE_FALL (a fall starts)

Fall rules (``FallDetectionConfig``, times in seconds):

* NORMAL/MONITORING -> POSSIBLE_FALL: downward body-center velocity >= ``fall_velocity_threshold``
  for at least ``velocity_min_seconds`` within ``candidate_window_seconds``, AND torso-angle
  rise >= ``torso_angle_change_deg`` OR low_posture_score >= ``candidate_low_posture_score``.
* POSSIBLE_FALL -> RECOVERY_WINDOW within ``confirm_window_seconds``: velocity evidence +
  torso-angle rise + low/horizontal posture held for ``confirm_posture_seconds``.
  Otherwise -> NORMAL (not confirmed).
* RECOVERY_WINDOW -> NORMAL on UPRIGHT held ``recovery_hold_seconds``; -> ALERT after
  ``recovery_window_seconds`` if low/horizontal >= ``abnormal_posture_fraction`` of the last
  ``escalation_lookback_seconds`` with mean motion <= ``low_motion_threshold``, or after
  ``max_extension_seconds`` more without recovery.

Lying / immobility rules (``ImmobilityConfig``; see ``immobility_detector``):

* NORMAL -> MONITORING when low/horizontal posture is sustained ``lying_monitor_seconds``
  (condition LYING), or upright stillness is sustained ``upright_still_monitor_seconds``
  (condition IMMOBILITY - never escalates on its own).
* MONITORING -> ALERT when lying + not moving, low + not moving, or lying alone is sustained
  for its configured duration; a fall candidate in the last ``recent_candidate_seconds``
  multiplies the durations by ``recent_candidate_factor`` and makes the alert HIGH
  (otherwise MEDIUM).
* MONITORING -> NORMAL on UPRIGHT held ``recovery_hold_seconds`` or non-low posture held
  ``monitor_clear_seconds`` (LYING), or when movement resumes (IMMOBILITY).

Common: ALERT -> RESOLVED on UPRIGHT held ``alert_clear_hold_seconds`` or on
:meth:`AssistanceDetector.acknowledge`; RESOLVED -> NORMAL after ``resolved_hold_seconds``.
After a resolved alert, lying/immobility checks re-arm only once the person has been seen
upright (``rearm_requires_upright``).

No decision uses a single frame. The detector is pure: its only clock is
``FeatureFrame.timestamp_ms``.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import deque

from moeen.config import FallDetectionConfig, ImmobilityConfig
from moeen.detection import evidence as ev
from moeen.detection import immobility_detector as im
from moeen.detection.models import DetectorOutput, Evidence, Incident, Timers, Transition
from moeen.detection.scoring import components, weighted_score
from moeen.detection.states import (ALLOWED_TRANSITIONS, STATE_RISK, Condition, DetectionState,
                                    Resolution, RiskLevel)
from moeen.features.models import FeatureFrame

log = logging.getLogger(__name__)

S = DetectionState
_NEG_INF_MS = -(10 ** 15)


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


class AssistanceDetector:
    """Stateful, deterministic detector. Feed it FeatureFrames in time order."""

    def __init__(self, fall: FallDetectionConfig, immobility: ImmobilityConfig | None = None,
                 max_frame_gap_seconds: float = 0.5) -> None:
        self.cfg = fall
        self.icfg = immobility or ImmobilityConfig()
        self.max_gap_s = max_frame_gap_seconds
        c = fall
        self._keep_ms = _ms(max(c.baseline_window_seconds + c.candidate_window_seconds
                                + c.confirm_window_seconds,
                                c.escalation_lookback_seconds, c.alert_clear_hold_seconds,
                                c.recovery_hold_seconds, self.icfg.lying_monitor_seconds) + 1.0)
        self.reset()

    # ------------------------------------------------------------------ public API
    def reset(self) -> None:
        """Return to NORMAL and forget all history and incidents."""
        self._frames: deque[FeatureFrame] = deque()
        self._last_ms: int | None = None
        self._state = S.NORMAL
        self._state_entered_ms = 0
        self._incident: Incident | None = None
        self._incident_counter = 0
        self._evidence_floor_ms = _NEG_INF_MS   # ignore velocity evidence before this time
        self._max_abnormal_hold_s = 0.0         # longest low/horizontal hold during POSSIBLE_FALL
        self._monitor = im.PostureMonitor(self.icfg)
        self._m = im.MonitorEvidence(0.0, 0.0, 0.0, 0.0)
        self._monitors_armed = True
        self._last_fall_candidate: Incident | None = None
        self._transitions: list[Transition] = []
        self._last_output: DetectorOutput | None = None
        self._last_evidence: Evidence | None = None

    @property
    def state(self) -> DetectionState:
        return self._state

    @property
    def incident(self) -> Incident | None:
        return self._incident

    @property
    def last_output(self) -> DetectorOutput | None:
        return self._last_output

    @property
    def monitors_armed(self) -> bool:
        return self._monitors_armed

    def update(self, frame: FeatureFrame) -> DetectorOutput:
        """Process one feature observation. ``frame.timestamp_ms`` must not decrease.

        Raises:
            ValueError: if the timestamp goes backwards.
        """
        t = frame.timestamp_ms
        if self._last_ms is not None and t < self._last_ms:
            raise ValueError(f"timestamps must not decrease ({t} ms after {self._last_ms} ms)")
        if self._last_ms is None:
            self._state_entered_ms = t
        self._last_ms = t
        self._frames.append(frame)
        while self._frames and self._frames[0].timestamp_ms < t - self._keep_ms:
            self._frames.popleft()
        self._m = self._monitor.update(frame)
        self._transitions = []

        handler = {S.NORMAL: self._on_normal, S.POSSIBLE_FALL: self._on_possible_fall,
                   S.RECOVERY_WINDOW: self._on_recovery_window, S.MONITORING: self._on_monitoring,
                   S.ALERT: self._on_alert, S.RESOLVED: self._on_resolved}[self._state]
        evidence, comps, status = handler(frame)
        return self._finish(t, evidence, comps, status)

    def acknowledge(self, timestamp_ms: int | None = None) -> DetectorOutput | None:
        """Record that assistance was given (dashboard button).

        Moves RECOVERY_WINDOW, MONITORING or ALERT to RESOLVED with resolution
        ASSISTANCE_RECORDED and returns the new output; returns None otherwise.
        """
        if self._state not in (S.RECOVERY_WINDOW, S.MONITORING, S.ALERT) or self._last_evidence is None:
            return None
        t = max(timestamp_ms if timestamp_ms is not None else self._last_ms or 0, self._last_ms or 0)
        self._transitions = []
        self._close_incident(t, Resolution.ASSISTANCE_RECORDED)
        self._go(t, S.RESOLVED, "assistance recorded by a person")
        zero = {k: 0.0 for k in self.cfg.weights()}
        return self._finish(t, self._last_evidence, zero, "Resolved - assistance recorded")

    # ------------------------------------------------------------------ evidence
    def _window(self, seconds: float) -> list[FeatureFrame]:
        cutoff = self._last_ms - _ms(seconds)
        return [f for f in self._frames if f.timestamp_ms >= cutoff]

    def _recent_candidate(self, t: int) -> bool:
        cand = self._last_fall_candidate
        return cand is not None and (t - cand.started_ms) / 1000 <= self.icfg.recent_candidate_seconds

    def _gather(self, frame: FeatureFrame, rise_after_ms: int | None = None) -> Evidence:
        c = self.cfg
        t = frame.timestamp_ms
        frames = list(self._frames)
        cand_since = max(t - _ms(c.candidate_window_seconds), self._evidence_floor_ms)
        peak, above_s, _ = ev.velocity_evidence(frames, cand_since, c.fall_velocity_threshold)
        angle_frames = self._window(c.baseline_window_seconds + c.candidate_window_seconds) \
            if rise_after_ms is None else [f for f in frames
                                           if f.timestamp_ms >= rise_after_ms - _ms(c.baseline_window_seconds)]
        rise = ev.torso_angle_rise(angle_frames, rise_after_ms if rise_after_ms is not None
                                   else t - _ms(c.candidate_window_seconds))
        lookback = self._window(c.escalation_lookback_seconds)
        pose_loss = c.pose_loss_counts_as_abnormal
        m = self._m
        return Evidence(
            pose_present=frame.pose_present,
            posture=frame.posture.value,
            peak_down_velocity=peak,
            velocity_above_s=above_s,
            torso_angle_rise_deg=rise,
            low_posture_score=frame.low_posture_score,
            abnormal_posture_fraction=ev.fraction(lookback, lambda f: ev.is_abnormal(f, pose_loss)),
            mean_motion=ev.mean_motion(lookback),
            upright_hold_s=ev.hold_seconds(frames, ev.is_upright, self.max_gap_s),
            abnormal_hold_s=ev.hold_seconds(frames, lambda f: ev.is_abnormal(f, pose_loss),
                                            self.max_gap_s),
            low_sustained_s=m.low_s,
            horizontal_sustained_s=m.horizontal_s,
            still_sustained_s=m.still_s,
            recent_fall_candidate=self._recent_candidate(t),
        )

    def _incident_components(self, e: Evidence, persistence: float) -> dict[str, float]:
        inc = self._incident
        assert inc is not None
        return components(self.cfg, peak_velocity=inc.peak_down_velocity,
                          angle_rise_deg=inc.torso_angle_rise_deg,
                          posture=e.abnormal_posture_fraction, motion=self._motion_for_score(e),
                          motion_assessed=True, persistence=persistence)

    def _linked(self) -> bool:
        """Does the open lying/immobility incident follow a fall candidate?"""
        return self._incident is not None and self._incident.follows_fall_candidate

    def _monitor_components(self, e: Evidence) -> dict[str, float]:
        """Score parts for lying/immobility: posture, stillness and progress toward an alert;
        velocity/angle come from the linked fall candidate, if any (stronger evidence)."""
        recent = self._linked()
        cand = self._last_fall_candidate if recent else None
        lying = self._window(self.icfg.lying_monitor_seconds)
        f = self.icfg.recent_candidate_factor if recent else 1.0
        comps = components(self.cfg,
                           peak_velocity=cand.peak_down_velocity if cand else None,
                           angle_rise_deg=cand.torso_angle_rise_deg if cand else None,
                           posture=ev.fraction(lying, lambda fr: ev.is_abnormal(fr, False)),
                           motion=None, motion_assessed=False,
                           persistence=im.escalation_progress(self._m, self.icfg, recent))
        comps["stillness"] = min(1.0, self._m.still_s / (self.icfg.horizontal_still_alert_seconds * f))
        return comps

    def _motion_for_score(self, e: Evidence) -> float | None:
        # No motion data in the lookback (person not visible): treated as "not moving"
        # only if pose loss is configured to count as abnormal.
        if e.mean_motion is None and not self.cfg.pose_loss_counts_as_abnormal:
            return float("inf")
        return e.mean_motion

    # ------------------------------------------------------------------ shared entry checks
    def _try_fall_candidate(self, frame: FeatureFrame, e: Evidence):
        """Start a POSSIBLE_FALL if the candidate evidence is present; else return None."""
        c = self.cfg
        velocity_ok = e.velocity_above_s >= c.velocity_min_seconds
        angle_ok = (e.torso_angle_rise_deg or 0.0) >= c.torso_angle_change_deg
        low_ok = (e.low_posture_score or 0.0) >= c.candidate_low_posture_score
        if not (velocity_ok and (angle_ok or low_ok)):
            return None
        t = frame.timestamp_ms
        if self._state is S.MONITORING:
            self._close_incident(t, Resolution.SUPERSEDED)
        since = max(t - _ms(c.candidate_window_seconds), self._evidence_floor_ms)
        _, _, first_ms = ev.velocity_evidence(list(self._frames), since, c.fall_velocity_threshold)
        self._incident_counter += 1
        self._max_abnormal_hold_s = 0.0
        self._incident = Incident(incident_id=self._incident_counter,
                                  started_ms=first_ms if first_ms is not None else t,
                                  condition=Condition.FALL,
                                  peak_down_velocity=e.peak_down_velocity,
                                  torso_angle_rise_deg=e.torso_angle_rise_deg)
        why = []
        if angle_ok:
            why.append(f"torso angle +{e.torso_angle_rise_deg:.0f} deg")
        if low_ok:
            why.append(f"low posture score {e.low_posture_score:.2f}")
        self._go(t, S.POSSIBLE_FALL,
                 f"fast downward motion (peak {e.peak_down_velocity:.2f} torso lengths/s for "
                 f"{e.velocity_above_s:.2f} s) + " + ", ".join(why))
        return self._on_possible_fall(frame)

    def _try_monitoring(self, frame: FeatureFrame, e: Evidence):
        """Start a MONITORING incident if lying/immobility is sustained; else return None."""
        if not self._monitors_armed:
            return None
        entry = im.monitor_entry(self._m, self.icfg)
        if entry is None:
            return None
        condition, reason = entry
        t = frame.timestamp_ms
        self._incident_counter += 1
        # Linking is decided once, at the start: the whole episode then counts as "after a
        # fall candidate" even if it lasts longer than recent_candidate_seconds.
        self._incident = Incident(incident_id=self._incident_counter, started_ms=t, condition=condition,
                                  follows_fall_candidate=e.recent_fall_candidate)
        suffix = " (follows a fall candidate)" if e.recent_fall_candidate else ""
        self._go(t, S.MONITORING, reason + suffix)
        return self._on_monitoring(frame, evidence=e)

    # ------------------------------------------------------------------ state handlers
    def _on_normal(self, frame: FeatureFrame):
        c = self.cfg
        e = self._gather(frame)
        result = self._try_fall_candidate(frame, e) or self._try_monitoring(frame, e)
        if result is not None:
            return result
        comps = components(c, peak_velocity=e.peak_down_velocity, angle_rise_deg=e.torso_angle_rise_deg,
                           posture=e.low_posture_score, motion=None, motion_assessed=False,
                           persistence=0.0)
        if not frame.pose_present:
            status = "Normal - no person visible"
        elif not self._monitors_armed:
            status = "Normal (lying/immobility checks resume once the person is upright)"
        else:
            status = "Normal"
        return e, comps, status

    def _on_possible_fall(self, frame: FeatureFrame):
        c = self.cfg
        inc = self._incident
        assert inc is not None
        t = frame.timestamp_ms
        e = self._gather(frame, rise_after_ms=inc.started_ms)
        peak = max(x for x in (inc.peak_down_velocity, e.peak_down_velocity) if x is not None) \
            if (inc.peak_down_velocity is not None or e.peak_down_velocity is not None) else None
        rise = max((x for x in (inc.torso_angle_rise_deg, e.torso_angle_rise_deg) if x is not None),
                   default=None)
        self._incident = inc = dataclasses.replace(inc, peak_down_velocity=peak, torso_angle_rise_deg=rise)

        posture_now = 1.0 if (not frame.pose_present and c.pose_loss_counts_as_abnormal) \
            else e.low_posture_score
        comps = components(c, peak_velocity=peak, angle_rise_deg=rise, posture=posture_now,
                           motion=None, motion_assessed=False, persistence=0.0)
        angle_ok = (rise or 0.0) >= c.torso_angle_change_deg
        posture_ok = e.abnormal_hold_s >= c.confirm_posture_seconds
        self._max_abnormal_hold_s = max(self._max_abnormal_hold_s, e.abnormal_hold_s)
        elapsed_s = (t - inc.started_ms) / 1000

        if angle_ok and posture_ok:
            self._incident = dataclasses.replace(inc, confirmed_ms=t)
            self._go(t, S.RECOVERY_WINDOW,
                     f"fall confirmed: peak {peak:.2f} torso lengths/s, torso +{rise:.0f} deg, "
                     f"low/horizontal for {e.abnormal_hold_s:.2f} s")
            return self._on_recovery_window(frame, evidence=e)
        if elapsed_s >= c.confirm_window_seconds:
            missing = []
            if not angle_ok:
                missing.append(f"torso angle rise {rise or 0:.0f} < {c.torso_angle_change_deg:.0f} deg")
            if self._max_abnormal_hold_s < c.confirm_posture_seconds:
                missing.append(f"low/horizontal posture held at most {self._max_abnormal_hold_s:.2f} < "
                               f"{c.confirm_posture_seconds:.2f} s")
            elif not angle_ok:
                missing.append("posture was low, but without the torso rotation of a fall")
            self._close_incident(t, Resolution.NOT_CONFIRMED)
            self._evidence_floor_ms = t
            self._go(t, S.NORMAL, "not confirmed: " + "; ".join(missing))
            # Someone who stays down after an unconfirmed candidate goes straight to MONITORING.
            e = self._gather(frame)
            result = self._try_monitoring(frame, e)
            if result is not None:
                return result
            return e, comps, "Normal (possible fall not confirmed)"
        status = (f"Possible fall - checking: torso +{rise or 0:.0f}/{c.torso_angle_change_deg:.0f} deg, "
                  f"low posture {e.abnormal_hold_s:.1f}/{c.confirm_posture_seconds:.1f} s")
        return e, comps, status

    def _on_recovery_window(self, frame: FeatureFrame, evidence: Evidence | None = None):
        c = self.cfg
        inc = self._incident
        assert inc is not None and inc.confirmed_ms is not None
        t = frame.timestamp_ms
        e = evidence or self._gather(frame)
        elapsed_s = (t - inc.confirmed_ms) / 1000
        comps = self._incident_components(e, persistence=elapsed_s / c.recovery_window_seconds)
        score = weighted_score(c, comps)

        if e.upright_hold_s >= c.recovery_hold_seconds:
            self._close_incident(t, Resolution.RECOVERED)
            self._evidence_floor_ms = t
            self._go(t, S.NORMAL, f"recovered: upright for {e.upright_hold_s:.1f} s "
                                  f"after {elapsed_s:.1f} s")
            return e, comps, "Normal (recovered from possible fall)"

        if elapsed_s >= c.recovery_window_seconds:
            frac = e.abnormal_posture_fraction or 0.0
            motion = self._motion_for_score(e)
            motion_low = motion is None or motion <= c.low_motion_threshold
            if frac >= c.abnormal_posture_fraction and motion_low and score >= c.alert_score_threshold:
                motion_txt = "not visible" if motion is None else f"{motion:.3f}"
                return self._raise_alert(frame, e, Condition.FALL, RiskLevel.HIGH,
                                         f"no recovery after {elapsed_s:.1f} s: low/horizontal "
                                         f"{100 * frac:.0f}% of last {c.escalation_lookback_seconds:.0f} s, "
                                         f"motion {motion_txt}")
            if elapsed_s >= c.recovery_window_seconds + c.max_extension_seconds:
                return self._raise_alert(frame, e, Condition.FALL, RiskLevel.HIGH,
                                         f"no recovery after {elapsed_s:.1f} s (still down, "
                                         f"moving or mixed posture)")
            left = c.recovery_window_seconds + c.max_extension_seconds - elapsed_s
            return e, comps, f"Fall detected - still down but moving; escalation in {left:.0f} s"

        left = c.recovery_window_seconds - elapsed_s
        return e, comps, (f"Fall detected - waiting for recovery: {left:.1f} s left "
                          f"(upright {e.upright_hold_s:.1f}/{c.recovery_hold_seconds:.1f} s)")

    def _on_monitoring(self, frame: FeatureFrame, evidence: Evidence | None = None):
        ic = self.icfg
        inc = self._incident
        assert inc is not None
        t = frame.timestamp_ms
        e = evidence or self._gather(frame)
        m = self._m

        # A fall that starts while monitoring takes over (e.g. someone sitting still falls).
        if evidence is None:
            result = self._try_fall_candidate(frame, e)
            if result is not None:
                return result

        # An upright-stillness incident becomes a lying incident if the person goes down.
        if inc.condition is Condition.IMMOBILITY and m.low_s >= ic.lying_monitor_seconds:
            self._incident = inc = dataclasses.replace(inc, condition=Condition.LYING)
            log.info("MONITORING condition IMMOBILITY -> LYING at %.2f s", t / 1000)

        comps = self._monitor_components(e)

        # recovery
        if inc.condition is Condition.LYING:
            if e.upright_hold_s >= self.cfg.recovery_hold_seconds:
                return self._end_monitoring(frame, e, comps,
                                            f"recovered: upright for {e.upright_hold_s:.1f} s")
            if m.normal_posture_s >= ic.monitor_clear_seconds:
                return self._end_monitoring(frame, e, comps,
                                            f"no longer low/horizontal for {m.normal_posture_s:.1f} s")
        elif m.still_s == 0.0 and frame.motion_magnitude is not None:
            return self._end_monitoring(frame, e, comps, "movement resumed")

        # escalation
        esc = im.check_escalation(m, ic, inc.follows_fall_candidate)
        if esc is not None:
            return self._raise_alert(frame, e, esc.condition, esc.severity, esc.reason)

        if inc.condition is Condition.IMMOBILITY:
            return e, comps, f"Monitoring - no movement for {m.still_s:.0f} s (upright; no alert)"
        due = im.time_to_escalation(m, ic, inc.follows_fall_candidate)
        visible = " - person not visible" if not frame.pose_present else ""
        due_txt = f"; alert in {due[0]:.0f} s ({due[1]})" if due else ""
        return e, comps, (f"Monitoring - down {m.low_s:.0f} s, still {m.still_s:.0f} s"
                          f"{due_txt}{visible}")

    def _end_monitoring(self, frame: FeatureFrame, e: Evidence, comps, reason: str):
        t = frame.timestamp_ms
        self._close_incident(t, Resolution.RECOVERED)
        self._go(t, S.NORMAL, reason)
        return e, comps, "Normal"

    def _raise_alert(self, frame: FeatureFrame, e: Evidence, condition: Condition,
                     severity: RiskLevel, reason: str):
        t = frame.timestamp_ms
        self._incident = dataclasses.replace(self._incident, alert_ms=t, condition=condition,
                                             severity=severity)
        self._go(t, S.ALERT, reason)
        comps = self._alert_components(e)
        return e, comps, f"ALERT ({condition.value}, {severity.value}) - {reason}"

    def _alert_components(self, e: Evidence) -> dict[str, float]:
        if self._incident is not None and self._incident.confirmed_ms is not None:
            return self._incident_components(e, persistence=1.0)      # fall path
        comps = self._monitor_components(e)
        comps["persistence"] = 1.0
        return comps

    def _on_alert(self, frame: FeatureFrame):
        c = self.cfg
        inc = self._incident
        assert inc is not None and inc.alert_ms is not None
        t = frame.timestamp_ms
        e = self._gather(frame)
        comps = self._alert_components(e)
        if e.upright_hold_s >= c.alert_clear_hold_seconds:
            self._close_incident(t, Resolution.RECOVERED_AFTER_ALERT)
            self._go(t, S.RESOLVED, f"recovered after alert: upright for {e.upright_hold_s:.1f} s")
            return e, {k: 0.0 for k in comps}, "Resolved - person recovered"
        if inc.condition is Condition.FALL:
            detail = f"no recovery for {(t - inc.confirmed_ms) / 1000:.0f} s"
        else:
            detail = f"down for {self._m.low_s:.0f} s, still for {self._m.still_s:.0f} s"
        return e, comps, f"ALERT ({inc.condition.value}, {inc.severity.value}) - {detail}"

    def _on_resolved(self, frame: FeatureFrame):
        c = self.cfg
        t = frame.timestamp_ms
        e = self._gather(frame)
        zero = {k: 0.0 for k in c.weights()}
        if (t - self._state_entered_ms) / 1000 >= c.resolved_hold_seconds:
            self._evidence_floor_ms = t
            self._go(t, S.NORMAL, "incident closed")
            return e, zero, "Normal"
        res = self._incident.resolution.value if self._incident and self._incident.resolution else ""
        return e, zero, f"Resolved ({res.lower().replace('_', ' ')})"

    # ------------------------------------------------------------------ bookkeeping
    def _go(self, t: int, new_state: DetectionState, reason: str) -> None:
        if new_state not in ALLOWED_TRANSITIONS[self._state]:
            raise AssertionError(f"illegal transition {self._state.value} -> {new_state.value}")
        self._transitions.append(Transition(t, self._state, new_state, reason))
        log.info("%s -> %s at %.2f s: %s", self._state.value, new_state.value, t / 1000, reason)
        self._state = new_state
        self._state_entered_ms = t

    def _close_incident(self, t: int, resolution: Resolution) -> None:
        inc = self._incident
        if inc is None or inc.resolution is not None:
            return
        self._incident = inc = dataclasses.replace(inc, resolved_ms=t, resolution=resolution)
        if inc.condition is Condition.FALL:
            self._last_fall_candidate = inc
        if resolution in (Resolution.ASSISTANCE_RECORDED, Resolution.RECOVERED_AFTER_ALERT) \
                and self.icfg.rearm_requires_upright:
            self._monitors_armed = False

    def _timers(self, t: int) -> Timers:
        c = self.cfg
        inc = self._incident
        in_state = (t - self._state_entered_ms) / 1000
        confirm_rem = rec_el = rec_rem = ext_rem = hold_req = alert_el = res_rem = None
        mon_el = esc_in = None
        if self._state is S.POSSIBLE_FALL and inc is not None:
            confirm_rem = max(0.0, c.confirm_window_seconds - (t - inc.started_ms) / 1000)
        if self._state in (S.RECOVERY_WINDOW, S.ALERT) and inc is not None and inc.confirmed_ms is not None:
            rec_el = (t - inc.confirmed_ms) / 1000
        if self._state is S.RECOVERY_WINDOW and rec_el is not None:
            rec_rem = max(0.0, c.recovery_window_seconds - rec_el)
            if rec_el >= c.recovery_window_seconds:
                ext_rem = max(0.0, c.recovery_window_seconds + c.max_extension_seconds - rec_el)
            hold_req = c.recovery_hold_seconds
        if self._state is S.MONITORING:
            mon_el = in_state
            hold_req = c.recovery_hold_seconds
            if inc is not None and inc.condition is Condition.LYING:
                due = im.time_to_escalation(self._m, self.icfg, inc.follows_fall_candidate)
                esc_in = due[0] if due else None
        if self._state is S.ALERT and inc is not None and inc.alert_ms is not None:
            alert_el = (t - inc.alert_ms) / 1000
            hold_req = c.alert_clear_hold_seconds
        if self._state is S.RESOLVED:
            res_rem = max(0.0, c.resolved_hold_seconds - in_state)
        return Timers(time_in_state_s=in_state, confirm_remaining_s=confirm_rem,
                      recovery_elapsed_s=rec_el, recovery_remaining_s=rec_rem,
                      extension_remaining_s=ext_rem, recovery_hold_required_s=hold_req,
                      alert_elapsed_s=alert_el, resolved_remaining_s=res_rem,
                      monitor_elapsed_s=mon_el, escalation_in_s=esc_in)

    def _risk(self) -> RiskLevel:
        inc = self._incident
        if self._state is S.ALERT and inc is not None and inc.severity is not None:
            return inc.severity
        return STATE_RISK[self._state]

    def _finish(self, t: int, e: Evidence, comps: dict[str, float], status: str) -> DetectorOutput:
        if not self._monitors_armed and e.upright_hold_s >= self.cfg.recovery_hold_seconds:
            self._monitors_armed = True
        score = weighted_score(self.cfg, comps)
        inc = self._incident
        if inc is not None and inc.resolution is None:
            self._incident = inc = dataclasses.replace(inc, max_score=max(inc.max_score, score))
        self._last_evidence = e
        out = DetectorOutput(
            timestamp_ms=t, state=self._state, risk_level=self._risk(), score=score,
            score_components=dict(comps),
            condition=inc.condition if inc is not None and inc.resolution is None else None,
            evidence=e, timers=self._timers(t), incident=inc,
            transitions=tuple(self._transitions), status=status)
        self._last_output = out
        return out
