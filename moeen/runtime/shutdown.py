"""Clean shutdown on SIGTERM (e.g. ``kill <pid>``), not just Ctrl+C."""

from __future__ import annotations

import contextlib
import signal
from typing import Iterator


def _raise_keyboard_interrupt(signum, frame) -> None:  # noqa: ARG001 - signal API
    raise KeyboardInterrupt


@contextlib.contextmanager
def sigterm_as_keyboard_interrupt() -> Iterator[None]:
    """Inside the block, SIGTERM raises KeyboardInterrupt so the same clean-up path as
    Ctrl+C runs (camera released, web server stopped, events closed). Only the main thread
    can install signal handlers; elsewhere (or on platforms without SIGTERM) this does nothing.
    """
    previous = None
    if hasattr(signal, "SIGTERM"):
        try:
            previous = signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        except ValueError:          # not the main thread
            previous = None
    try:
        yield
    finally:
        if previous is not None:
            with contextlib.suppress(ValueError):
                signal.signal(signal.SIGTERM, previous)
