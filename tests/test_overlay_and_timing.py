import numpy as np
import pytest

from fakes import upright_landmarks
from moeen.pose.overlay import draw_pose, draw_status
from moeen.timing import FpsMeter
from moeen.types import PoseFrame


def blank(h=240, w=320):
    return np.zeros((h, w, 3), np.uint8)


def test_draw_pose_draws_visible_landmarks():
    img = blank()
    drawn = draw_pose(img, PoseFrame(0, 320, 240, upright_landmarks(0.9)), 0.5)
    assert drawn == 33
    assert img.any()


def test_low_visibility_landmarks_are_not_drawn():
    img = blank()
    assert draw_pose(img, PoseFrame(0, 320, 240, upright_landmarks(0.1)), 0.5) == 0
    assert not img.any()


def test_no_pose_leaves_image_untouched():
    img = blank()
    assert draw_pose(img, PoseFrame(0, 320, 240, None)) == 0
    assert not img.any()


def test_draw_status_only_touches_top_left():
    img = np.full((240, 320, 3), 100, np.uint8)
    draw_status(img, ["FPS 30.0", "Pose: no person"])
    assert (img[:20, :60] != 100).any()
    assert (img[200:, 250:] == 100).all()


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_fps_meter_steady_rate():
    clock = FakeClock()
    meter = FpsMeter(window_seconds=1.0, clock=clock)
    for _ in range(60):
        meter.tick()
        clock.t += 1 / 20
    assert meter.fps == pytest.approx(20.0, rel=0.01)
    assert meter.total_frames == 60


def test_fps_meter_adapts_to_slowdown():
    clock = FakeClock()
    meter = FpsMeter(window_seconds=1.0, clock=clock)
    for _ in range(30):
        meter.tick()
        clock.t += 1 / 30
    for _ in range(20):
        meter.tick()
        clock.t += 1 / 10
    assert meter.fps == pytest.approx(10.0, rel=0.01)


def test_fps_meter_needs_two_ticks():
    meter = FpsMeter(clock=FakeClock())
    assert meter.fps == 0.0
    meter.tick()
    assert meter.fps == 0.0
    with pytest.raises(ValueError):
        FpsMeter(window_seconds=0)
