"""Test doubles for hardware and model boundaries.

These replace the *device* (cv2.VideoCapture) and the *model* (PoseLandmarker) so the
surrounding code can be tested without a webcam. They do not stand in for detection
results and are never used to claim that pose estimation works.
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import cv2
import numpy as np

from moeen.pose.models import EXPECTED_BUNDLE_MEMBERS
from moeen.types import Landmark, PoseFrame


class FakeCapture:
    """Mimics the cv2.VideoCapture methods used by Webcam."""

    def __init__(self, opened: bool = True, width: int = 64, height: int = 48,
                 good_reads: int | None = None, delay: float = 0.002) -> None:
        self.opened = opened
        self.width, self.height = width, height
        self.good_reads = good_reads  # None = unlimited; afterwards read() fails
        self.delay = delay
        self.reads = 0
        self.released = 0
        self.props: dict[int, float] = {}

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        time.sleep(self.delay)
        if self.good_reads is not None and self.reads >= self.good_reads:
            return False, None
        self.reads += 1
        img = np.full((self.height, self.width, 3), self.reads % 256, np.uint8)
        return True, img

    def set(self, prop_id: int, value: float) -> bool:
        self.props[prop_id] = value
        return True

    def get(self, prop_id: int) -> float:
        return self.props.get(prop_id, 0.0)

    def release(self) -> None:
        self.released += 1


def factory_for(capture: FakeCapture):
    calls: list[tuple[int, int]] = []

    def factory(index: int, api: int) -> FakeCapture:
        calls.append((index, api))
        return capture

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


def make_fake_bundle(path: Path) -> Path:
    """A zip with the right member names but junk content (passes the file-level check only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name in EXPECTED_BUNDLE_MEMBERS:
            z.writestr(name, b"not a real tflite model")
    return path


def upright_landmarks(visibility: float = 0.9) -> tuple[Landmark, ...]:
    """33 landmarks spread over the image, for drawing tests (geometry is irrelevant here)."""
    return tuple(Landmark(x=0.2 + 0.6 * (i % 6) / 5, y=0.1 + 0.8 * (i // 6) / 5, z=0.0,
                          visibility=visibility, presence=0.9) for i in range(33))


class FakeEstimator:
    """PoseEstimator stand-in that reports a pose on every other frame."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.closed = False

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> PoseFrame:
        self.calls.append(timestamp_ms)
        h, w = frame_bgr.shape[:2]
        lms = upright_landmarks() if len(self.calls) % 2 else None
        return PoseFrame(timestamp_ms, w, h, lms)

    def close(self) -> None:
        self.closed = True


__all__ = ["FakeCapture", "FakeEstimator", "factory_for", "make_fake_bundle",
           "upright_landmarks", "cv2"]


class SequenceEstimator:
    """PoseEstimator stand-in that replays a prepared list of PoseFrames (e.g. a synthetic
    fall), ignoring the camera image. Repeats the last frame when the list runs out."""

    name = "sequence"

    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0
        self.closed = False

    def detect(self, frame_bgr, timestamp_ms):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        if self.i > len(self.frames):          # keep timestamps increasing after the end
            f = PoseFrame(f.timestamp_ms + 33 * (self.i - len(self.frames)), f.image_width,
                          f.image_height, f.landmarks)
        return f

    def close(self):
        self.closed = True
