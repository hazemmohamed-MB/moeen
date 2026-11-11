"""Thread-safe hand-off between the camera/processing loop and the Flask dashboard.

* The processing loop *publishes* the latest status snapshot and preview frame.
* Flask *reads* them, and *submits* commands (e.g. "assistance recorded") that the loop
  applies on its own thread - so detector state is only ever changed by one thread.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Command:
    """A dashboard action to be applied by the processing loop."""

    kind: str                     # "assistance" | "resolve"
    event_id: int
    note: str | None = None
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None

    def finish(self, result: Any = None, error: BaseException | None = None) -> None:
        self.result, self.error = result, error
        self.done.set()

    def wait(self, timeout: float) -> bool:
        return self.done.wait(timeout)


class StatusStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._published_at: float | None = None
        self._frame_cond = threading.Condition()
        self._frame: bytes | None = None
        self._frame_seq = 0
        self._commands: queue.Queue[Command] = queue.Queue()
        self._pipeline_running = False
        self._stopped = threading.Event()

    # ------------------------------------------------------------------ status
    def publish(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._published_at = self._clock()

    def snapshot(self) -> tuple[dict[str, Any] | None, float | None]:
        """(latest snapshot, its age in seconds) - (None, None) before the first publish."""
        with self._lock:
            if self._snapshot is None:
                return None, None
            return self._snapshot, max(0.0, self._clock() - self._published_at)

    def set_pipeline_running(self, running: bool) -> None:
        with self._lock:
            self._pipeline_running = running

    @property
    def pipeline_running(self) -> bool:
        with self._lock:
            return self._pipeline_running

    # ------------------------------------------------------------------ preview frames
    def set_frame(self, jpeg: bytes) -> None:
        with self._frame_cond:
            self._frame = jpeg
            self._frame_seq += 1
            self._frame_cond.notify_all()

    def latest_frame(self) -> tuple[bytes | None, int]:
        with self._frame_cond:
            return self._frame, self._frame_seq

    def wait_for_frame(self, after_seq: int, timeout: float) -> tuple[bytes | None, int]:
        """Block until a frame newer than ``after_seq`` exists, the store stops, or timeout."""
        with self._frame_cond:
            self._frame_cond.wait_for(lambda: self._frame_seq > after_seq or self._stopped.is_set(),
                                      timeout)
            return self._frame, self._frame_seq

    # ------------------------------------------------------------------ commands
    def submit(self, command: Command) -> Command:
        if self._stopped.is_set():          # nobody will drain the queue any more
            command.finish(error=RuntimeError("the application is shutting down"))
        else:
            self._commands.put(command)
        return command

    def drain(self) -> list[Command]:
        out: list[Command] = []
        while True:
            try:
                out.append(self._commands.get_nowait())
            except queue.Empty:
                return out

    # ------------------------------------------------------------------ shutdown
    def stop(self) -> None:
        """Wake every waiting preview stream so the web server can shut down promptly."""
        self._stopped.set()
        with self._frame_cond:
            self._frame_cond.notify_all()
        for cmd in self.drain():
            cmd.finish(error=RuntimeError("the application is shutting down"))

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()
