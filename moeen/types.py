"""Library-independent data types shared across Moeen.

These types deliberately do not depend on OpenCV or MediaPipe, so feature
extraction and detection code (later phases) can be unit-tested without a camera
or a pose model.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Landmark:
    """One body landmark in normalized image coordinates.

    Attributes:
        x: horizontal position, 0 = left edge, 1 = right edge of the image.
        y: vertical position, 0 = top edge, 1 = bottom edge of the image.
        z: relative depth (smaller = closer to the camera); same scale as x.
        visibility: model's likelihood that the landmark is visible (not occluded), or None.
        presence: model's likelihood that the landmark is inside the frame, or None.
    """

    x: float
    y: float
    z: float
    visibility: float | None = None
    presence: float | None = None


@dataclass(frozen=True)
class PoseFrame:
    """Pose estimation result for one video frame.

    Attributes:
        timestamp_ms: monotonic timestamp of the frame in milliseconds.
        image_width / image_height: pixel size of the frame the landmarks refer to.
        landmarks: the 33 landmarks of the detected person, or None if no person was found.
    """

    timestamp_ms: int
    image_width: int
    image_height: int
    landmarks: tuple[Landmark, ...] | None = None

    @property
    def has_pose(self) -> bool:
        return self.landmarks is not None and len(self.landmarks) > 0
