"""Laptop webcam capture.

``Webcam`` wraps ``cv2.VideoCapture`` with:

* configurable camera index, frame size, FPS request and backend;
* a clear :class:`CameraError` when the camera cannot be opened or stops delivering frames;
* a background grabber thread that keeps only the *latest* frame, so a slow consumer
  (pose estimation) always processes the most recent image instead of a growing backlog.

The OpenCV capture object is created through an injectable factory so this module can be
tested without real hardware.
"""

from __future__ import annotations

import logging
import platform
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import cv2
import numpy as np

from moeen.config import CameraConfig

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """The webcam could not be opened, or it stopped delivering frames."""


class CaptureLike(Protocol):
    """The subset of ``cv2.VideoCapture`` that Moeen uses."""

    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...
    def set(self, prop_id: int, value: float) -> bool: ...
    def get(self, prop_id: int) -> float: ...
    def release(self) -> None: ...


CaptureFactory = Callable[[int, int], CaptureLike]

_BACKENDS: dict[str, int] = {
    "any": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "avfoundation": cv2.CAP_AVFOUNDATION,
    "v4l2": cv2.CAP_V4L2,
}


def resolve_backend(name: str, system: str | None = None) -> tuple[str, int]:
    """Map a backend name from the config to an OpenCV API id.

    ``auto`` picks DirectShow on Windows (MSMF often takes many seconds to open a laptop
    camera), AVFoundation on macOS and V4L2 on Linux.
    """
    if name != "auto":
        return name, _BACKENDS[name]
    system = system or platform.system()
    chosen = {"Windows": "dshow", "Darwin": "avfoundation", "Linux": "v4l2"}.get(system, "any")
    return chosen, _BACKENDS[chosen]


def _default_capture_factory(index: int, api: int) -> CaptureLike:
    return cv2.VideoCapture(index, api)


@dataclass(frozen=True)
class Frame:
    """A captured frame.

    Attributes:
        image: BGR image (H x W x 3, uint8) as delivered by OpenCV.
        frame_id: increasing counter, starting at 1.
        timestamp: ``time.monotonic()`` seconds when the frame was grabbed.
    """

    image: np.ndarray
    frame_id: int
    timestamp: float


def _troubleshooting_hint(system: str) -> str:
    hints = [
        "close other apps that may be using the camera (Zoom, Teams, browser tabs)",
        "try another index, e.g. --camera-index 1",
        "try another backend, e.g. --camera-backend any",
    ]
    if system == "Darwin":
        hints.insert(0, "allow camera access for your terminal app in "
                        "System Settings > Privacy & Security > Camera, then restart the terminal")
    elif system == "Windows":
        hints.insert(0, "check Settings > Privacy & security > Camera > "
                        "'Let desktop apps access your camera' is ON")
    return "; ".join(hints)


class Webcam:
    """Threaded latest-frame webcam reader. Use as a context manager."""

    def __init__(self, config: CameraConfig, capture_factory: CaptureFactory | None = None,
                 system: str | None = None) -> None:
        self.config = config
        self._factory = capture_factory or _default_capture_factory
        self._system = system or platform.system()
        self.backend_name, self._backend_id = resolve_backend(config.backend, self._system)

        self._cap: CaptureLike | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._error: str | None = None
        self._frame_counter = 0

        self.actual_width: int = 0
        self.actual_height: int = 0
        self.reported_fps: float = 0.0

    # ------------------------------------------------------------------ lifecycle
    def open(self) -> "Webcam":
        """Open the camera, apply the requested settings and wait for the first frame.

        Raises:
            CameraError: if the device cannot be opened or no frame arrives in time.
        """
        cfg = self.config
        log.info("Opening camera index=%d backend=%s", cfg.index, self.backend_name)
        try:
            cap = self._factory(cfg.index, self._backend_id)
        except Exception as exc:  # OpenCV can raise on some platforms instead of returning
            raise CameraError(f"Could not create capture for camera index {cfg.index} "
                              f"(backend {self.backend_name}): {exc}") from exc
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            raise CameraError(
                f"Could not open camera index {cfg.index} with backend '{self.backend_name}'. "
                f"Hints: {_troubleshooting_hint(self._system)}.")
        self._cap = cap

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # ignored by some backends; harmless

        first = self._read_first_frame(cfg.open_timeout_seconds)
        self.actual_height, self.actual_width = first.shape[:2]
        self.reported_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        log.info("Camera opened: %dx%d (requested %dx%d), driver-reported fps=%.1f",
                 self.actual_width, self.actual_height, cfg.width, cfg.height, self.reported_fps)
        self._publish(first)

        self._stop.clear()
        self._thread = threading.Thread(target=self._grab_loop, name="moeen-webcam", daemon=True)
        self._thread.start()
        return self

    def _read_first_frame(self, timeout: float) -> np.ndarray:
        assert self._cap is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ok, image = self._cap.read()
            if ok and image is not None and getattr(image, "size", 0) > 0:
                return image
            time.sleep(0.02)
        self._cap.release()
        self._cap = None
        raise CameraError(
            f"Camera index {self.config.index} opened but returned no frames within "
            f"{timeout:.1f} s. Hints: {_troubleshooting_hint(self._system)}.")

    def close(self) -> None:
        """Stop the grabber thread and release the device. Safe to call more than once."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._cond:
            self._cond.notify_all()

    def __enter__(self) -> "Webcam":
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ frames
    def _publish(self, image: np.ndarray) -> None:
        with self._cond:
            self._frame_counter += 1
            self._latest = Frame(image=image, frame_id=self._frame_counter,
                                 timestamp=time.monotonic())
            self._cond.notify_all()

    def _grab_loop(self) -> None:
        failures = 0
        while not self._stop.is_set():
            cap = self._cap
            if cap is None:
                break
            ok, image = cap.read()
            if ok and image is not None and getattr(image, "size", 0) > 0:
                failures = 0
                self._publish(image)
                continue
            failures += 1
            if failures >= self.config.read_failure_limit:
                with self._cond:
                    self._error = (f"Camera stopped delivering frames "
                                   f"({failures} consecutive failed reads). "
                                   "Was it unplugged or taken by another app?")
                    self._cond.notify_all()
                log.error(self._error)
                break
            time.sleep(0.01)

    def read_latest(self, after_id: int = 0, timeout: float = 2.0) -> Frame:
        """Return the newest frame whose ``frame_id`` is greater than ``after_id``.

        Blocks up to ``timeout`` seconds for a new frame.

        Raises:
            CameraError: if the camera failed, was closed, or no new frame arrived in time.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if self._error is not None:
                    raise CameraError(self._error)
                if self._latest is not None and self._latest.frame_id > after_id:
                    return self._latest
                if self._stop.is_set():
                    raise CameraError("Camera is closed.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CameraError(f"No new camera frame within {timeout:.1f} s.")
                self._cond.wait(remaining)
