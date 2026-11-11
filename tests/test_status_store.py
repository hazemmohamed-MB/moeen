"""StatusStore: the thread-safe hand-off between the processing loop and the web server."""

import threading
import time

from moeen.runtime import Command, StatusStore


class Clock:
    def __init__(self):
        self.t = 10.0

    def __call__(self):
        return self.t


def test_snapshot_reports_its_age():
    clock = Clock()
    store = StatusStore(clock=clock)
    assert store.snapshot() == (None, None)
    store.publish({"state": "NORMAL"})
    clock.t += 2.5
    snap, age = store.snapshot()
    assert snap == {"state": "NORMAL"} and age == 2.5


def test_commands_are_drained_in_order_once():
    store = StatusStore()
    a, b = store.submit(Command("assistance", 1)), store.submit(Command("resolve", 2))
    assert store.drain() == [a, b]
    assert store.drain() == []


def test_wait_for_frame_wakes_on_new_frame_and_times_out():
    store = StatusStore()
    assert store.wait_for_frame(0, timeout=0.05) == (None, 0)          # timeout, no frame
    threading.Timer(0.05, store.set_frame, args=(b"jpg",)).start()
    t0 = time.monotonic()
    assert store.wait_for_frame(0, timeout=5) == (b"jpg", 1)
    assert time.monotonic() - t0 < 2


def test_stop_wakes_streams_and_fails_pending_and_late_commands():
    store = StatusStore()
    pending = store.submit(Command("assistance", 1))
    threading.Timer(0.05, store.stop).start()
    t0 = time.monotonic()
    store.wait_for_frame(0, timeout=5)
    assert time.monotonic() - t0 < 2 and store.stopped
    assert pending.wait(0) and "shutting down" in str(pending.error)
    late = store.submit(Command("resolve", 1))
    assert late.wait(0) and "shutting down" in str(late.error) and store.drain() == []
