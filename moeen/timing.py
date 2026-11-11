"""Frame-rate measurement."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable


class FpsMeter:
    """Sliding-window FPS counter.

    Call :meth:`tick` once per processed frame; :attr:`fps` is the number of frames per
    second over the last ``window_seconds``.
    """

    def __init__(self, window_seconds: float = 1.0,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = window_seconds
        self._clock = clock
        self._ticks: deque[float] = deque()
        self.total_frames = 0

    def tick(self) -> float:
        now = self._clock()
        self._ticks.append(now)
        self.total_frames += 1
        cutoff = now - self.window_seconds
        while self._ticks and self._ticks[0] < cutoff:
            self._ticks.popleft()
        return self.fps

    @property
    def fps(self) -> float:
        if len(self._ticks) < 2:
            return 0.0
        span = self._ticks[-1] - self._ticks[0]
        return (len(self._ticks) - 1) / span if span > 0 else 0.0
