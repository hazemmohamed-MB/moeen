"""Temporal decision layer: turns feature streams into detection states.

One state machine (``AssistanceDetector``) handles falls, sustained lying/low posture and
immobility. Pure Python - must not import OpenCV, MediaPipe or the camera
(tests/test_architecture.py).
"""

from moeen.detection.detector import AssistanceDetector
from moeen.detection.models import DetectorOutput, Evidence, Incident, Timers, Transition
from moeen.detection.states import Condition, DetectionState, Resolution, RiskLevel

__all__ = ["AssistanceDetector", "Condition", "DetectionState", "DetectorOutput", "Evidence",
           "Incident", "Resolution", "RiskLevel", "Timers", "Transition"]
