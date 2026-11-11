"""SIMULATED laptop-webcam versions of the 7 calibration scenarios.

The stick figure from ``synthetic.py`` performs each scenario with natural variation (speed,
depth, sway; drawn from a seeded RNG), and is "filmed" under typical laptop-webcam
conditions:

    fps       30 (normal) or 15 (heavy model / slow laptop)
    distance  near (torso 0.22 frame heights, ~2.5 m) or far (torso 0.14, ~4 m, whole body
              on the floor still in view)
    light     good (landmark jitter sd 0.003 frame heights) or dim (sd 0.008, ~5% of
              frames without a detected person while on the floor, and tracking glitches:
              ~0.5% of frames where the whole skeleton jumps 0.03-0.08 frame heights for
              1-2 frames, as MediaPipe sometimes does in poor light)

Jitter is independent per frame and per landmark - harsher than MediaPipe's tracking-mode
jitter, which is smoothed over time. These runs check the decision logic and how much
margin each threshold has. They are NOT observations of real people; record the scenarios
with the webcam for that (README: "Calibration").
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, replace
from typing import Callable

import synthetic as syn
from synthetic import CHAIR, FLOOR_SIT, LYING, STAND, Pose2D, keyframes

FN = Callable[[float], Pose2D]


@dataclass(frozen=True)
class Condition:
    fps: float
    distance: str     # near | far
    light: str        # good | dim

    @property
    def tag(self) -> str:
        return f"{int(self.fps)}fps-{self.distance}-{self.light}"

    @property
    def noise(self) -> float:
        return 0.003 if self.light == "good" else 0.008

    @property
    def scale(self) -> float:
        return 1.0 if self.distance == "near" else 0.65


CONDITIONS = [Condition(f, d, l) for f, d, l in
              itertools.product((30.0, 15.0), ("near", "far"), ("good", "dim"))]


# ---------------------------------------------------------------- movement helpers
def with_sway(fn: FN, rng: random.Random, amount: float = 1.0) -> FN:
    """Small natural body sway and arm movement (a living person is never perfectly still)."""
    f1, f2 = rng.uniform(0.15, 0.35), rng.uniform(0.4, 0.8)
    p1, p2 = rng.uniform(0, 6.3), rng.uniform(0, 6.3)

    def out(t: float) -> Pose2D:
        p = fn(t)
        return replace(p, hip_x=p.hip_x + amount * 0.004 * math.sin(2 * math.pi * f1 * t + p1),
                       torso_deg=p.torso_deg + amount * 1.5 * math.sin(2 * math.pi * f2 * t + p2),
                       arm_deg=p.arm_deg + amount * 3.0 * math.sin(2 * math.pi * f1 * 1.7 * t + p2))
    return out


def breathing(fn: FN, start: float) -> FN:
    """A still person on the floor: only tiny chest movement after ``start``."""
    def out(t: float) -> Pose2D:
        p = fn(t)
        if t < start:
            return p
        return replace(p, torso_deg=p.torso_deg + 0.6 * math.sin(2 * math.pi * 0.25 * t))
    return out


def stand_up_from_floor(t0: float, sit_s: float, stand_s: float) -> list[tuple[float, Pose2D]]:
    sit_up = replace(FLOOR_SIT, torso_deg=20.0)
    kneel = Pose2D(hip_y=0.70, torso_deg=15.0, thigh_deg=10.0, shin_deg=-80.0)
    return [(t0 + sit_s, sit_up), (t0 + sit_s + stand_s * 0.5, kneel), (t0 + sit_s + stand_s, STAND)]


# ---------------------------------------------------------------- the 7 scenarios
def standing(rng: random.Random) -> tuple[FN, float, None]:
    base = keyframes((0.0, STAND), (20.0, STAND))
    fn = with_sway(base, rng, 1.5)

    def gestures(t: float) -> Pose2D:   # a wave and a stretch, like someone waiting
        p = fn(t)
        if 6.0 <= t <= 8.0:
            p = replace(p, arm_deg=p.arm_deg + 120 * math.sin(math.pi * (t - 6.0) / 2.0))
        if 13.0 <= t <= 14.5:
            p = replace(p, torso_deg=p.torso_deg - 12 * math.sin(math.pi * (t - 13.0) / 1.5))
        return p
    return gestures, 20.0, None


def walking(rng: random.Random) -> tuple[FN, float, None]:
    """Walk across the room and back, then toward the camera and away (size changes)."""
    speed = rng.uniform(0.35, 0.5)            # frame heights per second (~0.8-1.2 m/s)
    step_hz = rng.uniform(1.7, 2.1)
    x_min, x_max = 0.30, 1.03
    cross = (x_max - x_min) / speed

    def fn(t: float) -> Pose2D:
        phase = 2 * math.pi * step_hz * t / 2     # one leg cycle = two steps
        if t < 2 * cross:                          # across and back
            u = (t % (2 * cross)) / cross
            x = x_min + (x_max - x_min) * (u if u <= 1 else 2 - u)
            direction = 1 if u <= 1 else -1
            size = 1.0
        else:                                      # toward the camera and back (3 s each way)
            v = min(1.0, (t - 2 * cross) / 6.0)
            size = 1.0 + 0.35 * math.sin(math.pi * v)
            x, direction = 0.667, 0
        swing = 25 * math.sin(phase)
        bob = 0.09 * 0.22 * abs(math.sin(phase))   # hips rise mid-stance, ~4-5 cm
        torso = 0.22 * size
        return Pose2D(hip_x=x, hip_y=0.5 - bob,   # laptop camera at about hip height
                      torso_deg=4.0 * direction, thigh_deg=swing, shin_deg=swing * 0.6 - 5 * abs(swing) / 25,
                      arm_deg=8.0 + 18 * math.sin(phase + math.pi), torso=torso)
    return fn, 2 * cross + 6.0, None


def sitting(rng: random.Random) -> tuple[FN, float, None]:
    sit_s = rng.choice([rng.uniform(0.9, 1.5), rng.uniform(0.55, 0.7)])   # normal or "plop"
    mid = replace(syn.lerp_pose(STAND, CHAIR, 0.5), torso_deg=rng.uniform(20, 35))
    t0 = 3.0
    base = keyframes((0.0, STAND), (t0, STAND), (t0 + sit_s / 2, mid), (t0 + sit_s, CHAIR),
                     (t0 + sit_s + 15, CHAIR), (t0 + sit_s + 15.6, mid),
                     (t0 + sit_s + 16.4, STAND), (t0 + sit_s + 20, STAND))
    return with_sway(base, rng), t0 + sit_s + 20, None


def bending(rng: random.Random) -> tuple[FN, float, None]:
    if rng.random() < 0.5:     # bend at the waist
        depth = rng.uniform(75, 95)
        low = replace(STAND, hip_x=STAND.hip_x - 0.03, hip_y=STAND.hip_y + 0.01,
                      torso_deg=depth, arm_deg=-depth + 5)
    else:                      # squat and lean to pick something up
        low = Pose2D(hip_y=0.5 + 0.22 * rng.uniform(0.7, 0.9), torso_deg=rng.uniform(40, 55),
                     thigh_deg=70.0, shin_deg=-25.0, arm_deg=-30.0)
    down = rng.uniform(0.6, 1.2)
    hold = rng.uniform(1.0, 3.0)
    t0 = 3.0
    base = keyframes((0.0, STAND), (t0, STAND), (t0 + down, low), (t0 + down + hold, low),
                     (t0 + down + hold + 1.0, STAND), (t0 + down + hold + 6, STAND))
    return with_sway(base, rng), t0 + down + hold + 6, None


def slow_lying(rng: random.Random) -> tuple[FN, float, None]:
    t0 = 3.0
    sit = rng.uniform(2.0, 3.0)
    lie = rng.uniform(2.0, 3.5)
    base = keyframes((0.0, STAND), (t0, STAND), (t0 + sit, FLOOR_SIT), (t0 + sit + lie, LYING),
                     (t0 + sit + lie + 75, LYING))
    return breathing(base, t0 + sit + lie), t0 + sit + lie + 75, None


def fall_recover(rng: random.Random) -> tuple[FN, float, float]:
    t0 = 3.0
    fall_s = rng.uniform(0.5, 0.9)
    on_floor = rng.uniform(1.0, 2.5)
    land = t0 + fall_s
    pts = [(0.0, STAND), (t0, STAND), (land, LYING), (land + on_floor, LYING),
           *stand_up_from_floor(land + on_floor, rng.uniform(0.8, 1.2), rng.uniform(1.2, 1.8))]
    end = pts[-1][0] + 8.0
    return keyframes(*pts, (end, STAND)), end, land


FALL_SPEEDS = (0.6, 0.9, 1.2)      # seconds from standing to the floor: fast, typical, staged/slow


def fall_still(rng: random.Random, fall_s: float | None = None) -> tuple[FN, float, float]:
    t0 = 3.0
    fall_s = fall_s if fall_s is not None else rng.choice(FALL_SPEEDS)
    land = t0 + fall_s
    base = keyframes((0.0, STAND), (t0, STAND), (land, LYING), (land + 40, LYING))
    return breathing(base, land + 0.5), land + 40, land


def with_glitches(frames, rng: random.Random, rate: float = 0.005):
    """Occasional 1-2 frame skeleton jumps (a tracking glitch), as in poor light."""
    from moeen.types import Landmark, PoseFrame
    out = list(frames)
    i = 0
    while i < len(out):
        if out[i].landmarks is not None and rng.random() < rate:
            ang = rng.uniform(0, 2 * math.pi)
            mag = rng.uniform(0.03, 0.08)
            dx, dy = mag * math.cos(ang), mag * math.sin(ang)
            aspect = out[i].image_width / out[i].image_height
            for j in range(i, min(len(out), i + rng.choice((1, 2)))):
                f = out[j]
                if f.landmarks is None:
                    continue
                out[j] = PoseFrame(f.timestamp_ms, f.image_width, f.image_height, tuple(
                    Landmark(l.x + dx / aspect, l.y + dy, l.z, l.visibility, l.presence)
                    for l in f.landmarks))
            i += 3
        else:
            i += 1
    return out


SCENARIO_FNS = {"standing": standing, "walking": walking, "sitting": sitting, "bending": bending,
                "slow_lying": slow_lying, "fall_recover": fall_recover, "fall_still": fall_still}


def render_scenario(key: str, cond: Condition, seed: int, **kw):
    """-> (pose frames, landing time or None, variant tag)."""
    rng = random.Random(f"{key}-{seed}")
    fn, duration, land = SCENARIO_FNS[key](rng, **kw)
    if cond.scale != 1.0:
        fn = syn.scaled(fn, cond.scale)
    drop = None
    if cond.light == "dim" and land is not None or (cond.light == "dim" and key == "slow_lying"):
        drng = random.Random(f"drop-{key}-{seed}")
        after = land if land is not None else 8.0
        lost = {round(t, 3) for t in [x / cond.fps for x in range(int(duration * cond.fps) + 1)]
                if t > after and drng.random() < 0.05}
        drop = lambda t: round(t, 3) in lost  # noqa: E731
    frames = syn.render(fn, duration, cond.fps, noise=cond.noise, seed=seed, drop_frames=drop)
    if cond.light == "dim":
        frames = with_glitches(frames, random.Random(f"glitch-{key}-{seed}"))
    extra = f"-fall{kw['fall_s']:.1f}s" if "fall_s" in kw else ""
    return frames, land, f"{cond.tag}-s{seed}{extra}"


def all_runs(seeds=(1, 2, 3)):
    """Every scenario x condition x seed (fall_still: every fall speed instead of a random one)."""
    for key in SCENARIO_FNS:
        for cond in CONDITIONS:
            for seed in seeds:
                if key == "fall_still":
                    for fs in FALL_SPEEDS:
                        yield (key, *render_scenario(key, cond, seed, fall_s=fs))
                else:
                    yield (key, *render_scenario(key, cond, seed))
