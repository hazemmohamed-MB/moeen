"""Record and reload real pose sequences (JSON Lines), so features and - later - the detector
can be checked and regression-tested on genuine webcam data instead of synthetic motion.

File format (one JSON object per line):
    line 1: {"type": "header", "format": 1, ...metadata...}
    then:   {"t": <timestamp_ms>, "w": <width>, "h": <height>,
             "lm": [[x, y, z, visibility, presence], ... 33 entries] | null}

Only landmarks are stored - no images - so recordings are small and contain no video.
This module does not import OpenCV or MediaPipe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

from moeen.types import Landmark, PoseFrame

FORMAT_VERSION = 1
_DIGITS = 5


class RecordingError(ValueError):
    """The recording file is missing, malformed, or has an unsupported format."""


def _num(v: float | None) -> float | None:
    return None if v is None else round(float(v), _DIGITS)


def frame_to_record(frame: PoseFrame) -> dict[str, Any]:
    lms = None if not frame.has_pose else [
        [_num(lm.x), _num(lm.y), _num(lm.z), _num(lm.visibility), _num(lm.presence)]
        for lm in frame.landmarks or ()]
    return {"t": frame.timestamp_ms, "w": frame.image_width, "h": frame.image_height, "lm": lms}


def record_to_frame(rec: dict[str, Any]) -> PoseFrame:
    lms = rec.get("lm")
    landmarks = None if lms is None else tuple(Landmark(*row) for row in lms)
    return PoseFrame(int(rec["t"]), int(rec["w"]), int(rec["h"]), landmarks)


class PoseRecorder:
    """Writes PoseFrames to a JSONL file. Use as a context manager."""

    def __init__(self, path: Path | str, metadata: dict[str, Any] | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO | None = open(self.path, "w", encoding="utf-8")
        header = {"type": "header", "format": FORMAT_VERSION, **(metadata or {})}
        self._fh.write(json.dumps(header) + "\n")
        self.frames_written = 0

    def write(self, frame: PoseFrame) -> None:
        if self._fh is None:
            raise RecordingError("recorder is closed")
        self._fh.write(json.dumps(frame_to_record(frame), separators=(",", ":")) + "\n")
        self.frames_written += 1

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "PoseRecorder":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def load_recording(path: Path | str) -> tuple[dict[str, Any], list[PoseFrame]]:
    """Return (header, frames) from a recording file."""
    path = Path(path)
    if not path.is_file():
        raise RecordingError(f"recording not found: {path}")
    header: dict[str, Any] | None = None
    frames: list[PoseFrame] = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RecordingError(f"{path}:{n}: invalid JSON ({exc})") from exc
            if header is None:
                if obj.get("type") != "header":
                    raise RecordingError(f"{path}: first line must be a header")
                if obj.get("format") != FORMAT_VERSION:
                    raise RecordingError(f"{path}: unsupported format {obj.get('format')}")
                header = obj
                continue
            try:
                frames.append(record_to_frame(obj))
            except (KeyError, TypeError, ValueError) as exc:
                raise RecordingError(f"{path}:{n}: bad frame record ({exc})") from exc
    if header is None:
        raise RecordingError(f"{path}: empty file")
    return header, frames
