"""Scenario observations for calibration: run a pose sequence through the real feature
extractor, detector and sound policy, and judge the result against what the scenario should
produce.

Works the same on SIMULATED sequences (``python scripts/calibrate.py --synthetic``) and on
REAL recordings made with ``python -m moeen.app --record ...``. Only real recordings say
how the system behaves with a real person and camera; simulated runs check the logic and
the margins under controlled, idealized conditions.

No result here is a measure of medical accuracy or real-world safety.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from moeen.alerts.alert_manager import AlertSoundPolicy
from moeen.config import AppConfig
from moeen.detection import AssistanceDetector, DetectionState as S
from moeen.features import FeatureExtractor
from moeen.types import PoseFrame

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    expected: str           # plain-language expected outcome (the acceptance rule)


SCENARIOS: dict[str, Scenario] = {s.key: s for s in (
    Scenario("standing", "Standing", "no event, no alert"),
    Scenario("walking", "Walking", "no event, no alert"),
    Scenario("sitting", "Sitting down on a chair", "no event, no alert"),
    Scenario("bending", "Bending to pick something up", "no event, no alert"),
    Scenario("slow_lying", "Lying down slowly and staying",
             "no fall incident, no HIGH alert, no sound (watching / a MEDIUM alert after "
             "long stillness is allowed)"),
    Scenario("fall_recover", "Quick fall + immediate recovery",
             "no alert; a possible-fall state may appear but must be cancelled"),
    Scenario("fall_still", "Fall + remain still",
             "FALL alert, HIGH severity, sound, within recovery window + 5 s of landing"),
)}

# Words in a recording's label or file name -> scenario (most specific first).
_NAME_RULES = [
    (r"recover|get.?up|stand.?up.?after", "fall_recover"),
    (r"fall", "fall_still"),
    (r"lie|lying|lay", "slow_lying"),
    (r"bend|pick", "bending"),
    (r"sit|chair", "sitting"),
    (r"walk", "walking"),
    (r"stand", "standing"),
]


def scenario_for(name: str) -> str | None:
    """Guess the scenario from a recording label / file name (e.g. 'fall_still_02')."""
    low = name.lower()
    for key in SCENARIOS:
        if key in low:
            return key
    for pattern, key in _NAME_RULES:
        if re.search(pattern, low):
            return key
    return None


@dataclass
class Observation:
    scenario: str
    variant: str
    frames: int
    duration_s: float
    states: list[str] = field(default_factory=list)       # in order, consecutive duplicates removed
    alert: str = "-"                                        # e.g. "FALL/HIGH at 12.9 s"
    alert_after_landing_s: float | None = None
    sounds: int = 0
    events: int = 0                                         # incidents that would be stored
    peak_velocity: float = 0.0                              # torso lengths/s, max over the run
    peak_angle_rise: float = 0.0                            # deg
    max_hip_drop: float = 0.0                               # torso lengths
    max_score: float = 0.0
    possible_fall_s: float = 0.0                            # time shown as "checking a possible fall"
    final_state: str = "NORMAL"
    verdict: str = PASS
    reason: str = ""

    @property
    def state_path(self) -> str:
        return " > ".join(self.states)


def observe(poses: Sequence[PoseFrame], config: AppConfig, scenario: str, variant: str = "",
            landing_s: float | None = None) -> Observation:
    """Run one sequence and judge it. ``landing_s``: time the person reaches the floor in a
    fall scenario (for the alert-delay check); None if unknown (real recordings)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; known: {', '.join(SCENARIOS)}")
    extractor = FeatureExtractor(config.features)
    detector = AssistanceDetector(config.fall_detection, config.immobility)
    policy = AlertSoundPolicy(config.sound)
    t0 = poses[0].timestamp_ms if poses else 0
    prev_ms: int | None = None
    obs = Observation(scenario, variant, len(poses),
                      (poses[-1].timestamp_ms - t0) / 1000 if poses else 0.0)
    for pose in poses:
        feats = extractor.update(pose)
        out = detector.update(feats)
        if policy.update(out) is not None:
            obs.sounds += 1
        state = out.state.value
        if not obs.states or obs.states[-1] != state:
            obs.states.append(state)
        for tr in out.transitions:
            if tr.to_state in (S.RECOVERY_WINDOW, S.MONITORING) and tr.from_state in (S.NORMAL, S.POSSIBLE_FALL):
                obs.events += 1
            if tr.to_state is S.ALERT and obs.alert == "-":
                inc = out.incident
                t = (tr.timestamp_ms - t0) / 1000
                obs.alert = f"{inc.condition.value}/{inc.severity.value} at {t:.1f} s"
                if landing_s is not None:
                    obs.alert_after_landing_s = t - landing_s
        e = out.evidence
        if e.peak_down_velocity is not None:
            obs.peak_velocity = max(obs.peak_velocity, e.peak_down_velocity)
        if e.torso_angle_rise_deg is not None:
            obs.peak_angle_rise = max(obs.peak_angle_rise, e.torso_angle_rise_deg)
        if feats.hip_drop is not None and math.isfinite(feats.hip_drop):
            obs.max_hip_drop = max(obs.max_hip_drop, feats.hip_drop)
        obs.max_score = max(obs.max_score, out.score)
        if out.state is S.POSSIBLE_FALL and prev_ms is not None:
            obs.possible_fall_s += (pose.timestamp_ms - prev_ms) / 1000
        prev_ms = pose.timestamp_ms
        obs.final_state = state
    _judge(obs, config)
    return obs


def _judge(o: Observation, config: AppConfig) -> None:
    states = set(o.states)
    alert_high = "/HIGH" in o.alert
    if o.scenario in ("standing", "walking", "sitting", "bending"):
        if "ALERT" in states:
            o.verdict, o.reason = FAIL, f"false alert ({o.alert})"
        elif states & {"RECOVERY_WINDOW", "MONITORING"}:
            o.verdict, o.reason = FAIL, "an event would be stored (" + o.state_path + ")"
        elif "POSSIBLE_FALL" in states:
            o.verdict, o.reason = WARN, (f"possible-fall check shown for {o.possible_fall_s:.1f} s "
                                         "(not stored, no alert)")
    elif o.scenario == "slow_lying":
        if "RECOVERY_WINDOW" in states:
            o.verdict, o.reason = FAIL, "treated as a confirmed fall"
        elif alert_high or o.sounds:
            o.verdict, o.reason = FAIL, f"HIGH alert / sound ({o.alert})"
        elif "POSSIBLE_FALL" in states:
            o.verdict, o.reason = WARN, "brief possible-fall check"
        else:
            o.reason = "watching" + (f", {o.alert}" if o.alert != "-" else "") \
                if "MONITORING" in states else "no event"
    elif o.scenario == "fall_recover":
        if "ALERT" in states:
            o.verdict, o.reason = FAIL, f"alert despite recovery ({o.alert})"
        elif o.final_state not in ("NORMAL", "RESOLVED"):
            o.verdict, o.reason = FAIL, f"not back to normal (ends {o.final_state})"
        else:
            o.reason = "cancelled after " + o.state_path.split(" > ", 1)[-1] \
                if len(o.states) > 1 else "no possible-fall state"
    elif o.scenario == "fall_still":
        limit = config.fall_detection.recovery_window_seconds + 5.0
        if not o.alert.startswith("FALL/HIGH"):
            o.verdict = FAIL
            o.reason = "no fall alert" + (f" (got {o.alert})" if o.alert != "-" else "") \
                + f"; peak speed {o.peak_velocity:.2f} tl/s, torso turn {o.peak_angle_rise:.0f} deg"
        elif o.alert_after_landing_s is not None and o.alert_after_landing_s > limit:
            o.verdict, o.reason = FAIL, f"alert too late ({o.alert_after_landing_s:.1f} s after landing)"
        elif o.sounds == 0:
            o.verdict, o.reason = FAIL, "alert without sound"
        else:
            delay = (f" ({o.alert_after_landing_s:.1f} s after landing)"
                     if o.alert_after_landing_s is not None else "")
            o.reason = f"{o.alert}{delay}"


# ---------------------------------------------------------------------- reporting
@dataclass
class ScenarioSummary:
    scenario: str
    runs: int
    passed: int
    warned: int
    failed: int
    peak_velocity: tuple[float, float]
    peak_angle_rise: tuple[float, float]
    max_hip_drop: tuple[float, float]
    alert_delay: tuple[float, float] | None


def summarize(observations: Iterable[Observation]) -> list[ScenarioSummary]:
    by: dict[str, list[Observation]] = {}
    for o in observations:
        by.setdefault(o.scenario, []).append(o)
    out = []
    for key in SCENARIOS:
        obs = by.get(key)
        if not obs:
            continue

        def rng(vals):
            vals = list(vals)
            return (min(vals), max(vals))
        delays = [o.alert_after_landing_s for o in obs if o.alert_after_landing_s is not None]
        out.append(ScenarioSummary(
            key, len(obs), sum(o.verdict == PASS for o in obs), sum(o.verdict == WARN for o in obs),
            sum(o.verdict == FAIL for o in obs), rng(o.peak_velocity for o in obs),
            rng(o.peak_angle_rise for o in obs), rng(o.max_hip_drop for o in obs),
            rng(delays) if delays and key == "fall_still" else None))
    return out


def markdown_report(observations: Sequence[Observation], config: AppConfig, *, title: str,
                    note: str, detail: bool = True) -> str:
    from moeen.config import calibration_values
    lines = [f"# {title}", "", note, "", "## Calibration values used", "",
             "| Name | Value |", "|---|---|"]
    lines += [f"| `{k}` | {v:g} |" for k, v in calibration_values(config).items()]
    lines += ["", "## Summary per scenario", "",
              "| Scenario | Expected | Runs | Pass | Warn | Fail | Peak speed tl/s (min-max) "
              "| Torso turn deg | Max hip drop tl | Alert after landing s |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for s in summarize(observations):
        sc = SCENARIOS[s.scenario]
        delay = f"{s.alert_delay[0]:.1f}-{s.alert_delay[1]:.1f}" if s.alert_delay else "-"
        lines.append(f"| {sc.title} | {sc.expected} | {s.runs} | {s.passed} | {s.warned} | "
                     f"{s.failed} | {s.peak_velocity[0]:.2f}-{s.peak_velocity[1]:.2f} | "
                     f"{s.peak_angle_rise[0]:.0f}-{s.peak_angle_rise[1]:.0f} | "
                     f"{s.max_hip_drop[0]:.2f}-{s.max_hip_drop[1]:.2f} | {delay} |")
    problems = [o for o in observations if o.verdict != PASS]
    lines += ["", f"## Not passed ({len(problems)})", ""]
    if problems:
        lines += ["| Scenario | Variant | Verdict | States | Why |", "|---|---|---|---|---|"]
        lines += [f"| {o.scenario} | {o.variant} | {o.verdict} | {o.state_path} | {o.reason} |"
                  for o in problems]
    else:
        lines.append("None.")
    if detail:
        lines += ["", "## Every run", "",
                  "| Scenario | Variant | Verdict | States | Alert | Sounds | Peak speed | "
                  "Torso turn | Hip drop | Max score | Possible-fall s |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {o.scenario} | {o.variant} | {o.verdict} | {o.state_path} | {o.alert} | "
                  f"{o.sounds} | {o.peak_velocity:.2f} | {o.peak_angle_rise:.0f} | "
                  f"{o.max_hip_drop:.2f} | {o.max_score:.2f} | {o.possible_fall_s:.1f} |"
                  for o in observations]
    return "\n".join(lines) + "\n"
