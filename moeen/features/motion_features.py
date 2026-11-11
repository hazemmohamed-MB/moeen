"""Temporal measurements: vertical velocity and motion magnitude (pure, no OpenCV/MediaPipe)."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Sequence

from moeen.features.posture_features import Vec


def regression_slope(ts: Sequence[float], ys: Sequence[float]) -> float | None:
    """Least-squares slope dy/dt. Needs >= 2 samples spanning a non-zero time.

    A regression over a short window is much less sensitive to landmark jitter than a
    two-frame difference, and it handles irregular frame intervals naturally.
    """
    n = len(ts)
    if n < 2 or n != len(ys):
        return None
    mt = sum(ts) / n
    my = sum(ys) / n
    sxx = sum((t - mt) ** 2 for t in ts)
    if sxx <= 1e-12:
        return None
    return sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / sxx


class VelocityTracker:
    """Vertical velocity of one tracked point from a short sliding window of positions."""

    def __init__(self, window_seconds: float, max_gap_seconds: float) -> None:
        self.window = window_seconds
        self.max_gap = max_gap_seconds
        self._samples: deque[tuple[float, float]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def update(self, t: float, y: float | None) -> float | None:
        """Add a sample (``y=None`` means not measurable) and return the current slope.

        A gap longer than ``max_gap_seconds`` restarts tracking, so the velocity never spans
        a period where the person was not observed.
        """
        if y is None:
            if self._samples and t - self._samples[-1][0] > self.max_gap:
                self._samples.clear()
            return None
        if self._samples and t - self._samples[-1][0] > self.max_gap:
            self._samples.clear()
        self._samples.append((t, y))
        while self._samples and self._samples[0][0] < t - self.window:
            self._samples.popleft()
        if len(self._samples) < 2 or self._samples[-1][0] - self._samples[0][0] < self.window * 0.3:
            return None
        ts, ys = zip(*self._samples)
        return regression_slope(ts, ys)


@dataclass(frozen=True)
class MotionSample:
    t: float
    points: dict[int, Vec]   # keypoint index -> position (frame-height units)


def rms_spread(samples: Sequence[MotionSample], min_samples: int = 3) -> float | None:
    """Mean over keypoints of the RMS distance from that keypoint's average position.

    This measures *how much the body moved* within the samples. Unlike summing
    frame-to-frame displacements, it does not grow with the frame rate, and detector
    jitter only contributes its (small) standard deviation instead of accumulating.
    Keypoints seen in fewer than ``min_samples`` samples are ignored.
    """
    tracks: dict[int, list[Vec]] = {}
    for s in samples:
        for i, p in s.points.items():
            tracks.setdefault(i, []).append(p)
    spreads = []
    for pts in tracks.values():
        if len(pts) < min_samples:
            continue
        mx = sum(p.x for p in pts) / len(pts)
        my = sum(p.y for p in pts) / len(pts)
        spreads.append(math.sqrt(sum((p.x - mx) ** 2 + (p.y - my) ** 2 for p in pts) / len(pts)))
    return sum(spreads) / len(spreads) if spreads else None


class MotionTracker:
    """Rolling-window motion magnitude (RMS keypoint displacement, frame heights).

    Only the most recent *contiguous* run of pose samples is used (a gap longer than
    ``max_gap_seconds`` starts a new run), so time without a detected person is never
    counted as "no motion", and a person re-appearing elsewhere is not counted as motion.
    """

    def __init__(self, window_seconds: float, max_gap_seconds: float) -> None:
        self.window = window_seconds
        self.max_gap = max_gap_seconds
        self._samples: deque[MotionSample] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def update(self, t: float, points: dict[int, Vec] | None) -> tuple[float | None, float]:
        """Add a frame (``points=None`` if no pose). Returns (magnitude, coverage).

        ``coverage`` is the time span of the current run inside the window divided by the
        window length (0..1). ``magnitude`` is None when fewer than 3 samples are available.
        """
        if self._samples and t - self._samples[-1].t > self.max_gap:
            self._samples.clear()
        if points:
            self._samples.append(MotionSample(t, points))
        while self._samples and self._samples[0].t < t - self.window:
            self._samples.popleft()
        if len(self._samples) < 2:
            return None, 0.0
        coverage = min(1.0, (self._samples[-1].t - self._samples[0].t) / self.window)
        return rms_spread(self._samples), coverage
