"""Pure-Python helpers for the 33-point BlazePose landmark layout.

The index constants mirror ``mediapipe.tasks.python.vision.PoseLandmark``; a unit test
checks them against the installed MediaPipe so a layout change cannot go unnoticed.
This module does not import MediaPipe or OpenCV.
"""

from __future__ import annotations

from moeen.types import Landmark

NUM_LANDMARKS = 33

NOSE = 0
LEFT_EYE = 2
RIGHT_EYE = 5
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28

# The person's left/right side. Face points 1-6 are grouped (1-3 left eye, 4-6 right eye);
# from index 7 onward, odd = left and even = right.
LEFT_SIDE: frozenset[int] = frozenset({1, 2, 3} | {i for i in range(7, NUM_LANDMARKS) if i % 2 == 1})
RIGHT_SIDE: frozenset[int] = frozenset({4, 5, 6} | {i for i in range(8, NUM_LANDMARKS) if i % 2 == 0})


def is_visible(landmark: Landmark, threshold: float) -> bool:
    """True if the landmark's visibility is at least ``threshold``.

    Landmarks without a visibility value (``None``) are treated as visible.
    """
    return landmark.visibility is None or landmark.visibility >= threshold


def to_pixel(landmark: Landmark, width: int, height: int) -> tuple[int, int]:
    """Convert normalized coordinates to integer pixel coordinates."""
    return int(round(landmark.x * width)), int(round(landmark.y * height))
