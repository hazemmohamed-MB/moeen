"""Pose-estimator interface.

The rest of Moeen talks to pose estimation only through this protocol. MediaPipe is the
primary implementation; a YOLOv8-Pose adapter could be added later behind the same
interface without touching downstream code.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from moeen.types import PoseFrame


@runtime_checkable
class PoseEstimator(Protocol):
    """Estimates the pose of a single person in a BGR frame."""

    name: str

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> PoseFrame:
        """Run pose estimation on one frame.

        Args:
            frame_bgr: H x W x 3 uint8 image in OpenCV's BGR channel order.
            timestamp_ms: monotonic timestamp of the frame in milliseconds.
        """
        ...

    def close(self) -> None:
        """Release model resources."""
        ...
