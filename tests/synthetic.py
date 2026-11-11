"""SYNTHETIC landmark sequences for unit tests.

A simple 2-D stick figure (proportions in torso lengths) is posed by keyframes and projected
to normalized image coordinates, producing the same 33-landmark layout MediaPipe returns.

These sequences test that the feature code measures geometry and motion in the right
DIRECTION (e.g. "a fall produces a larger downward velocity than sitting"). They are
idealized: they are NOT evidence that the system works on real people or real cameras.
Real-world behaviour must be checked with recordings from the webcam
(python -m moeen.app --record ...; python scripts/replay_features.py ...).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Sequence

from moeen.pose import landmark_utils as lu
from moeen.types import Landmark, PoseFrame

FRAME_W, FRAME_H = 640, 480

# Body proportions relative to the torso (shoulder center -> hip center) length.
THIGH, SHIN = 0.9, 0.9
UPPER_ARM, FOREARM = 0.6, 0.55
HEAD = 0.38                    # shoulder center -> nose
SHOULDER_HALF, HIP_HALF = 0.22, 0.14   # half widths (a 3/4 view, so narrower than frontal)


@dataclass(frozen=True)
class Pose2D:
    """Body configuration. Angles in degrees; positions in frame-height units.

    torso_deg: hip->shoulder direction from straight up; + leans toward +x.
    thigh_deg / shin_deg: limb direction from straight down; + points toward +x.
    arm_deg: arm direction relative to "torso down"; 0 = hanging along the body.
    """

    hip_x: float = 0.667     # 640x480 frame: 0.667 frame heights = horizontal center
    hip_y: float = 0.50
    torso_deg: float = 0.0
    thigh_deg: float = 0.0
    shin_deg: float = 0.0
    arm_deg: float = 8.0
    torso: float = 0.22      # torso length, frame heights (person size / distance)


STAND = Pose2D()
# Sitting on a chair: hips ~0.9 torso lengths lower, thighs horizontal, shins vertical.
CHAIR = Pose2D(hip_y=0.70, torso_deg=8.0, thigh_deg=90.0, shin_deg=0.0)
# Lying on the floor (side view), head toward +x, legs toward -x.
LYING = Pose2D(hip_y=0.86, torso_deg=90.0, thigh_deg=-90.0, shin_deg=-90.0, arm_deg=10.0)
# Sitting on the floor, legs stretched out forward.
FLOOR_SIT = Pose2D(hip_y=0.86, torso_deg=10.0, thigh_deg=90.0, shin_deg=90.0)


def _unit_up(deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return math.sin(r), -math.cos(r)


def _unit_down(deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return math.sin(r), math.cos(r)


def landmarks_for(p: Pose2D) -> list[tuple[float, float]]:
    """33 landmark positions in frame-height units for a body configuration."""
    T = p.torso
    ux, uy = _unit_up(p.torso_deg)            # torso "up" direction
    px, py = -uy, ux                           # perpendicular (body width direction)
    hip = (p.hip_x, p.hip_y)
    sh = (hip[0] + T * ux, hip[1] + T * uy)

    def off(c, half, sign):
        return (c[0] + sign * half * T * px, c[1] + sign * half * T * py)

    pts: list[tuple[float, float]] = [(0.0, 0.0)] * 33
    l_sh, r_sh = off(sh, SHOULDER_HALF, +1), off(sh, SHOULDER_HALF, -1)
    l_hip, r_hip = off(hip, HIP_HALF, +1), off(hip, HIP_HALF, -1)
    pts[lu.LEFT_SHOULDER], pts[lu.RIGHT_SHOULDER] = l_sh, r_sh
    pts[lu.LEFT_HIP], pts[lu.RIGHT_HIP] = l_hip, r_hip

    nose = (sh[0] + HEAD * T * ux, sh[1] + HEAD * T * uy)
    pts[lu.NOSE] = nose
    for i, (a, b) in {1: (0.03, -0.04), 2: (0.05, -0.05), 3: (0.07, -0.05), 4: (-0.03, -0.04),
                      5: (-0.05, -0.05), 6: (-0.07, -0.05), 7: (0.10, -0.02), 8: (-0.10, -0.02),
                      9: (0.03, 0.06), 10: (-0.03, 0.06)}.items():
        # a: along body width, b: along torso up (negative = toward the top of the head)
        pts[i] = (nose[0] + a * T * px - b * T * ux, nose[1] + a * T * py - b * T * uy)

    # arms: direction = torso-down rotated by arm_deg (outward on each side)
    for side, s_pt, el, wr, extra in ((+1, l_sh, lu.LEFT_ELBOW, lu.LEFT_WRIST, (17, 19, 21)),
                                     (-1, r_sh, lu.RIGHT_ELBOW, lu.RIGHT_WRIST, (18, 20, 22))):
        a = math.radians(p.arm_deg) * side
        dx, dy = -ux, -uy
        rx, ry = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
        e = (s_pt[0] + UPPER_ARM * T * rx, s_pt[1] + UPPER_ARM * T * ry)
        w = (e[0] + FOREARM * T * rx, e[1] + FOREARM * T * ry)
        pts[el], pts[wr] = e, w
        for k, j in enumerate(extra):
            pts[j] = (w[0] + 0.08 * T * rx + 0.03 * (k - 1) * T * px,
                      w[1] + 0.08 * T * ry + 0.03 * (k - 1) * T * py)

    tx, ty = _unit_down(p.thigh_deg)
    sx, sy = _unit_down(p.shin_deg)
    for h, kn, an, heel, toe in ((l_hip, lu.LEFT_KNEE, lu.LEFT_ANKLE, 29, 31),
                                 (r_hip, lu.RIGHT_KNEE, lu.RIGHT_ANKLE, 30, 32)):
        k = (h[0] + THIGH * T * tx, h[1] + THIGH * T * ty)
        a = (k[0] + SHIN * T * sx, k[1] + SHIN * T * sy)
        pts[kn], pts[an] = k, a
        fx, fy = sy, -sx                      # foot direction: shin rotated by 90 degrees
        pts[heel] = (a[0] - 0.05 * T * fx, a[1] - 0.05 * T * fy)
        pts[toe] = (a[0] + 0.15 * T * fx, a[1] + 0.15 * T * fy)
    return pts


def lerp_pose(a: Pose2D, b: Pose2D, u: float) -> Pose2D:
    u = 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, u)))  # smooth ease-in/out
    return Pose2D(*(x + (y - x) * u for x, y in zip(
        (a.hip_x, a.hip_y, a.torso_deg, a.thigh_deg, a.shin_deg, a.arm_deg, a.torso),
        (b.hip_x, b.hip_y, b.torso_deg, b.thigh_deg, b.shin_deg, b.arm_deg, b.torso))))


def keyframes(*points: tuple[float, Pose2D]) -> Callable[[float], Pose2D]:
    """Piecewise smooth interpolation between (time_s, pose) keyframes; holds at the ends."""
    pts = sorted(points, key=lambda kv: kv[0])

    def fn(t: float) -> Pose2D:
        if t <= pts[0][0]:
            return pts[0][1]
        for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
            if t <= t1:
                return lerp_pose(p0, p1, (t - t0) / (t1 - t0) if t1 > t0 else 1.0)
        return pts[-1][1]
    return fn


def render(fn: Callable[[float], Pose2D], duration: float, fps: float = 30.0, *,
           noise: float = 0.0, seed: int = 0, width: int = FRAME_W, height: int = FRAME_H,
           visibility: float = 0.95, hidden: Iterable[int] = (),
           drop_frames: Callable[[float], bool] | None = None,
           start_ms: int = 0) -> list[PoseFrame]:
    """Sample ``fn`` at ``fps`` and return PoseFrames.

    noise: Gaussian landmark jitter (std, frame heights) - mimics real detector jitter.
    hidden: landmark indices reported with low visibility (occluded).
    drop_frames: predicate on time; True -> frame has no detected person.
    """
    rng = random.Random(seed)
    hidden = set(hidden)
    aspect = width / height
    frames: list[PoseFrame] = []
    n = int(round(duration * fps))
    for i in range(n + 1):
        t = i / fps
        ts = start_ms + int(round(t * 1000))
        if drop_frames is not None and drop_frames(t):
            frames.append(PoseFrame(ts, width, height, None))
            continue
        pts = landmarks_for(fn(t))
        lms = tuple(
            Landmark(x=(x + rng.gauss(0, noise)) / aspect, y=y + rng.gauss(0, noise), z=0.0,
                     visibility=0.1 if j in hidden else visibility, presence=0.95)
            for j, (x, y) in enumerate(pts))
        frames.append(PoseFrame(ts, width, height, lms))
    return frames


# ---------------------------------------------------------------- named scenarios
def standing(duration: float = 8.0) -> Callable[[float], Pose2D]:
    return keyframes((0.0, STAND), (duration, STAND))


def bending(duration: float = 8.0, depth_deg: float = 80.0) -> Callable[[float], Pose2D]:
    """Forward bend at the waist (e.g. picking something up) and back: hips stay high."""
    bent = replace(STAND, hip_x=STAND.hip_x - 0.03, hip_y=STAND.hip_y + 0.01,
                   torso_deg=depth_deg, arm_deg=-depth_deg + 5)
    return keyframes((0.0, STAND), (2.0, STAND), (3.5, bent), (4.5, bent), (6.0, STAND),
                     (duration, STAND))


def sitting(duration: float = 10.0, sit_seconds: float = 1.4) -> Callable[[float], Pose2D]:
    """Sit down normally on a chair and stay seated."""
    mid = replace(lerp_pose(STAND, CHAIR, 0.5), torso_deg=25.0)
    return keyframes((0.0, STAND), (2.0, STAND), (2.0 + sit_seconds / 2, mid),
                     (2.0 + sit_seconds, CHAIR), (duration, CHAIR))


def fall(duration: float = 8.0, fall_seconds: float = 0.7) -> Callable[[float], Pose2D]:
    """Rapid fall from standing to lying on the floor, then remain lying."""
    return keyframes((0.0, STAND), (2.0, STAND), (2.0 + fall_seconds, LYING), (duration, LYING))


def lie_down_slowly(duration: float = 15.0) -> Callable[[float], Pose2D]:
    """Intentional, controlled lying down: sit on the floor first, then lie back."""
    return keyframes((0.0, STAND), (2.0, STAND), (4.5, FLOOR_SIT), (7.0, LYING), (duration, LYING))


def lying_only(duration: float = 6.0) -> Callable[[float], Pose2D]:
    """Already lying when first observed (no standing reference available)."""
    return keyframes((0.0, LYING), (duration, LYING))


def fall_then_recover(duration: float = 12.0) -> Callable[[float], Pose2D]:
    """Fall, lie still briefly, then get up to standing."""
    sit_up = replace(FLOOR_SIT, torso_deg=20.0)
    return keyframes((0.0, STAND), (2.0, STAND), (2.7, LYING), (6.0, LYING),
                     (7.2, sit_up), (8.7, STAND), (duration, STAND))


def fast_squat_and_stand(duration: float = 10.0, down_seconds: float = 0.5,
                         hold_seconds: float = 0.6) -> Callable[[float], Pose2D]:
    """False fall-like motion: drop quickly into a deep squat (torso stays fairly upright),
    then stand up again. Fast and low, but no large torso rotation."""
    squat = Pose2D(hip_y=0.78, torso_deg=25.0, thigh_deg=80.0, shin_deg=-20.0)
    t0 = 2.0
    return keyframes((0.0, STAND), (t0, STAND), (t0 + down_seconds, squat),
                     (t0 + down_seconds + hold_seconds, squat),
                     (t0 + down_seconds + hold_seconds + 0.8, STAND), (duration, STAND))


def stumble_and_catch(duration: float = 8.0) -> Callable[[float], Pose2D]:
    """False fall-like motion: trip, lurch forward and down, catch yourself, stand up."""
    lurch = Pose2D(hip_y=0.62, torso_deg=50.0, thigh_deg=40.0, shin_deg=-10.0, arm_deg=60.0)
    return keyframes((0.0, STAND), (2.0, STAND), (2.35, lurch), (2.6, lurch), (3.4, STAND),
                     (duration, STAND))


def fall_then_struggle(duration: float = 45.0) -> Callable[[float], Pose2D]:
    """Fall, then stay on the floor while moving the arms (trying but failing to get up)."""
    base = fall(duration)

    def fn(t: float) -> Pose2D:
        p = base(t)
        if t < 4.0:
            return p
        return replace(p, arm_deg=10.0 + 80.0 * (0.5 - 0.5 * math.cos(2 * math.pi * 0.7 * t)),
                       torso_deg=90.0 + 12.0 * math.sin(2 * math.pi * 0.4 * t))
    return fn


def fall_then_recover_late(duration: float = 40.0, get_up_at: float = 20.0) -> Callable[[float], Pose2D]:
    """Fall, lie still long enough to trigger an alert, then get up."""
    sit_up = replace(FLOOR_SIT, torso_deg=20.0)
    return keyframes((0.0, STAND), (2.0, STAND), (2.7, LYING), (get_up_at, LYING),
                     (get_up_at + 1.2, sit_up), (get_up_at + 2.7, STAND), (duration, STAND))


def with_movement_bursts(fn: Callable[[float], Pose2D], start: float, every: float,
                         burst: float = 1.5) -> Callable[[float], Pose2D]:
    """Add a short arm movement (``burst`` s) every ``every`` s after ``start``: a resting
    person who still moves now and then."""
    def out(t: float) -> Pose2D:
        p = fn(t)
        if t >= start and ((t - start) % every) < burst:
            phase = ((t - start) % every) / burst
            return replace(p, arm_deg=p.arm_deg + 70.0 * math.sin(math.pi * phase))
        return p
    return out


def lie_down_and_rest(duration: float = 120.0, move_every: float | None = None) -> Callable[[float], Pose2D]:
    """Intentional lying down (via sitting on the floor), then resting. With ``move_every``
    the person moves the arms briefly every that many seconds; without it they stay still."""
    fn = lie_down_slowly(duration)
    return with_movement_bursts(fn, 9.0, move_every) if move_every else fn


def floor_sit_and_play(duration: float = 300.0) -> Callable[[float], Pose2D]:
    """Sit down on the floor slowly and keep moving the arms (e.g. playing with a child)."""
    base = keyframes((0.0, STAND), (2.0, STAND), (4.5, FLOOR_SIT), (duration, FLOOR_SIT))

    def fn(t: float) -> Pose2D:
        p = base(t)
        if t < 5.0:
            return p
        return replace(p, arm_deg=20.0 + 50.0 * (0.5 - 0.5 * math.cos(2 * math.pi * 0.5 * t)))
    return fn


SQUAT_LOW = Pose2D(hip_y=0.78, torso_deg=25.0, thigh_deg=80.0, shin_deg=-20.0)


def drop_low_and_stay(duration: float = 150.0, down_seconds: float = 0.5) -> Callable[[float], Pose2D]:
    """Drop quickly into a low crouch (a fall-like candidate without torso rotation) and stay
    there without moving."""
    return keyframes((0.0, STAND), (2.0, STAND), (2.0 + down_seconds, SQUAT_LOW), (duration, SQUAT_LOW))


def lower_slowly_and_stay(duration: float = 150.0) -> Callable[[float], Pose2D]:
    """Reach the same low crouch slowly (no fall candidate) and stay without moving."""
    return keyframes((0.0, STAND), (2.0, STAND), (5.0, SQUAT_LOW), (duration, SQUAT_LOW))


def arm_waving(duration: float = 6.0, speed_hz: float = 1.0,
               amplitude_deg: float = 60.0) -> Callable[[float], Pose2D]:
    """Standing in place while swinging the arms (for motion-magnitude tests)."""
    def fn(t: float) -> Pose2D:
        return replace(STAND, arm_deg=8.0 + amplitude_deg * (0.5 - 0.5 * math.cos(2 * math.pi * speed_hz * t)))
    return fn


def scaled(fn: Callable[[float], Pose2D], factor: float,
           anchor_y: float = 0.95) -> Callable[[float], Pose2D]:
    """Same motion seen from farther away / closer (person size scaled about the floor line)."""
    def out(t: float) -> Pose2D:
        p = fn(t)
        return replace(p, torso=p.torso * factor, hip_y=anchor_y - (anchor_y - p.hip_y) * factor,
                       hip_x=0.667 + (p.hip_x - 0.667) * factor)
    return out


def times(frames: Sequence[PoseFrame]) -> list[float]:
    return [f.timestamp_ms / 1000 for f in frames]
