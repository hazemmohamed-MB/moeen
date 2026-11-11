"""Decides when the alert sound plays, and logs what the alert layer does.

The rule (``sound`` section of the config):

* only a confirmed alert (detector state ALERT) whose severity is at least
  ``sound.min_severity`` (HIGH by default: a fall without recovery, or lying/stillness
  right after a fall candidate) makes a sound;
* the first play happens on the first frame of the alert, then - while the same alert stays
  unanswered - again every ``repeat_seconds``, at most ``max_plays_per_alert`` times;
* no two sounds are ever closer than ``cooldown_seconds`` (also across incidents), so a
  flickering condition cannot make the laptop beep every frame;
* as soon as the alert is answered ("Assistance recorded") or the person recovers, the
  incident is no longer in ALERT and the sound stops.

:class:`AlertSoundPolicy` is pure: its only clock is the detector timestamp, so it is tested
with synthetic frames. :class:`AlertManager` connects it to a :class:`SoundPlayer`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from moeen.config import SoundConfig
from moeen.detection import DetectionState, DetectorOutput
from moeen.detection.states import RiskLevel

log = logging.getLogger(__name__)

_RANK = {RiskLevel.NONE: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}


@dataclass(frozen=True)
class SoundRequest:
    incident_id: int
    play_number: int          # 1 = first play for this alert
    reason: str


class AlertSoundPolicy:
    def __init__(self, config: SoundConfig) -> None:
        self.cfg = config
        self._min_rank = _RANK[RiskLevel(config.min_severity)]
        self._incident: int | None = None     # incident the counters below belong to
        self._plays = 0
        self._last_play_ms: int | None = None  # for this incident
        self._last_any_ms: int | None = None   # any incident (cooldown)
        self.suppressed = 0                    # frames where a due sound waited for the cooldown

    def qualifies(self, out: DetectorOutput) -> bool:
        inc = out.incident
        return (out.state is DetectionState.ALERT and inc is not None and inc.resolution is None
                and inc.severity is not None and _RANK[inc.severity] >= self._min_rank)

    def update(self, out: DetectorOutput) -> SoundRequest | None:
        """Call once per frame. Returns a request when the sound should play now."""
        if not self.qualifies(out):
            return None
        inc = out.incident
        t = out.timestamp_ms
        if inc.incident_id != self._incident:
            self._incident, self._plays, self._last_play_ms = inc.incident_id, 0, None

        if self._plays == 0:
            reason = f"{inc.condition.value} alert ({inc.severity.value})"
        elif (self.cfg.repeat_seconds > 0 and self._plays < self.cfg.max_plays_per_alert
              and t - self._last_play_ms >= self.cfg.repeat_seconds * 1000):
            unanswered = (t - (inc.alert_ms or t)) / 1000
            reason = (f"{inc.condition.value} alert still unanswered after {unanswered:.0f} s "
                      f"(play {self._plays + 1}/{self.cfg.max_plays_per_alert})")
        else:
            return None

        if self._last_any_ms is not None and t - self._last_any_ms < self.cfg.cooldown_seconds * 1000:
            self.suppressed += 1        # due, but too soon after the last sound: wait
            return None
        self._plays += 1
        self._last_play_ms = self._last_any_ms = t
        return SoundRequest(inc.incident_id, self._plays, reason)


class AlertManager:
    """Per-frame alert layer: sound decisions + log lines. Never raises."""

    def __init__(self, config: SoundConfig, player=None) -> None:
        self.cfg = config
        self.policy = AlertSoundPolicy(config)
        self.player = player
        self.requests: list[SoundRequest] = []
        self._broken = False

    def update(self, out: DetectorOutput | None) -> SoundRequest | None:
        if out is None or self._broken:
            return None
        try:
            return self._update(out)
        except Exception:  # noqa: BLE001 - an alert-layer bug must not stop detection
            self._broken = True
            log.exception("Alert layer failed; continuing without sound")
            return None

    def _update(self, out: DetectorOutput) -> SoundRequest | None:
        for tr in out.transitions:
            if tr.to_state is DetectionState.ALERT and out.incident is not None:
                sev = out.incident.severity.value if out.incident.severity else "?"
                sound = "sound on" if self.policy.qualifies(out) and self.cfg.enabled else (
                    "no sound: below sound.min_severity" if self.cfg.enabled else "sound disabled")
                log.warning("ALERT raised: %s, severity %s (%s)", out.incident.condition.value,
                            sev, sound)
            elif tr.from_state is DetectionState.ALERT:
                log.info("Alert ended: %s", tr.reason)
        if not self.cfg.enabled:
            return None
        req = self.policy.update(out)
        if req is None:
            return None
        self.requests.append(req)
        if self.player is None:
            return req
        if self.player.muted:
            log.info("Alert sound muted (press m to unmute): %s", req.reason)
        elif self.player.play(req.reason):
            log.warning("Alert sound: %s", req.reason)
        else:
            log.info("Alert sound not played (%s): %s",
                     "no audio output" if not self.player.available else "already playing",
                     req.reason)
        return req

    def toggle_mute(self) -> bool | None:
        return self.player.toggle_mute() if self.player is not None else None

    def status(self) -> dict:
        """For the dashboard and the preview overlay."""
        if self.player is None:
            return {"enabled": False, "available": False, "muted": False, "backend": None,
                    "plays": 0, "last_error": None, "min_severity": self.cfg.min_severity}
        st = self.player.status().to_dict()
        st["min_severity"] = self.cfg.min_severity
        return st
