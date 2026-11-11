"""Time-windowed history of feature frames (for the temporal detector in later phases)."""

from __future__ import annotations

from collections import deque
from typing import Any, Iterator

from moeen.features.models import FeatureFrame


class FeatureHistory:
    """Keeps the feature frames of the last ``max_seconds`` (by frame timestamp)."""

    def __init__(self, max_seconds: float) -> None:
        if max_seconds <= 0:
            raise ValueError("max_seconds must be positive")
        self.max_ms = int(max_seconds * 1000)
        self._frames: deque[FeatureFrame] = deque()

    def append(self, frame: FeatureFrame) -> None:
        self._frames.append(frame)
        cutoff = frame.timestamp_ms - self.max_ms
        while self._frames and self._frames[0].timestamp_ms < cutoff:
            self._frames.popleft()

    def clear(self) -> None:
        self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)

    def __iter__(self) -> Iterator[FeatureFrame]:
        return iter(self._frames)

    @property
    def latest(self) -> FeatureFrame | None:
        return self._frames[-1] if self._frames else None

    def window(self, seconds: float) -> list[FeatureFrame]:
        """Frames whose timestamp is within ``seconds`` of the latest frame."""
        if not self._frames:
            return []
        cutoff = self._frames[-1].timestamp_ms - int(seconds * 1000)
        return [f for f in self._frames if f.timestamp_ms >= cutoff]

    def values(self, field: str, seconds: float | None = None) -> list[Any]:
        """Non-None values of ``field`` over the window (or the whole history)."""
        frames = self.window(seconds) if seconds is not None else list(self._frames)
        return [v for v in (getattr(f, field) for f in frames) if v is not None]

    def fraction(self, predicate, seconds: float) -> float:
        """Fraction of frames in the window for which ``predicate(frame)`` is true."""
        frames = self.window(seconds)
        return sum(1 for f in frames if predicate(f)) / len(frames) if frames else 0.0
