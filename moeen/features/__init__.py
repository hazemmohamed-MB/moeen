"""Feature-extraction layer: measurements from pose landmarks (no alerting).

This package must not import OpenCV or MediaPipe so it can be tested without a camera
(enforced by tests/test_architecture.py).
"""

from moeen.features.extractor import BodyReference, FeatureExtractor
from moeen.features.history import FeatureHistory
from moeen.features.models import FeatureFrame, Point, PostureLabel, ScaleSource

__all__ = ["BodyReference", "FeatureExtractor", "FeatureFrame", "FeatureHistory", "Point",
           "PostureLabel", "ScaleSource"]
