"""Registry of the official MediaPipe PoseLandmarker model files.

URLs are the versioned (``/float16/1/``) links used in Google's own MediaPipe samples
(google-ai-edge/mediapipe-samples-web, src/tasks/pose-landmarker.ts).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

_BASE = "https://storage.googleapis.com/mediapipe-models/pose_landmarker"

# A .task file is a zip bundle containing these two TFLite networks.
EXPECTED_BUNDLE_MEMBERS: tuple[str, ...] = ("pose_detector.tflite", "pose_landmarks_detector.tflite")


@dataclass(frozen=True)
class ModelSpec:
    variant: str
    filename: str
    url: str


MODELS: dict[str, ModelSpec] = {
    v: ModelSpec(v, f"pose_landmarker_{v}.task",
                 f"{_BASE}/pose_landmarker_{v}/float16/1/pose_landmarker_{v}.task")
    for v in ("lite", "full", "heavy")
}


def model_path(model_dir: Path, variant: str) -> Path:
    """Where the model file for ``variant`` is expected on disk."""
    return Path(model_dir) / MODELS[variant].filename


def validate_model_file(path: Path) -> list[str]:
    """Return a list of problems with a model file (empty list = looks valid)."""
    path = Path(path)
    if not path.is_file():
        return [f"file not found: {path}"]
    if not zipfile.is_zipfile(path):
        return [f"not a valid .task bundle (not a zip archive): {path}"]
    with zipfile.ZipFile(path) as bundle:
        names = set(bundle.namelist())
    missing = [m for m in EXPECTED_BUNDLE_MEMBERS if m not in names]
    return [f"bundle is missing {m}" for m in missing]
