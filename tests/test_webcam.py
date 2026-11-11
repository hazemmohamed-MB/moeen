import cv2
import pytest

from fakes import FakeCapture, factory_for
from moeen.camera.webcam import CameraError, Webcam, resolve_backend
from moeen.config import CameraConfig

CFG = CameraConfig(index=3, width=320, height=240, fps=30,
                   open_timeout_seconds=0.3, read_failure_limit=3)


def test_open_failure_raises_clear_error_and_releases():
    cap = FakeCapture(opened=False)
    with pytest.raises(CameraError) as err:
        Webcam(CFG, factory_for(cap), system="Windows").open()
    msg = str(err.value)
    assert "camera index 3" in msg and "dshow" in msg
    assert "Privacy" in msg  # platform-specific hint
    assert cap.released == 1


def test_factory_exception_becomes_camera_error():
    def boom(index, api):
        raise RuntimeError("driver crashed")
    with pytest.raises(CameraError, match="driver crashed"):
        Webcam(CFG, boom).open()


def test_opened_but_no_frames_times_out():
    cap = FakeCapture(good_reads=0)
    with pytest.raises(CameraError, match="returned no frames"):
        Webcam(CFG, factory_for(cap)).open()
    assert cap.released == 1


def test_open_applies_settings_and_delivers_latest_frames():
    cap = FakeCapture(width=320, height=240)
    factory = factory_for(cap)
    with Webcam(CFG, factory, system="Linux") as cam:
        assert factory.calls == [(3, cv2.CAP_V4L2)]
        assert cap.props[cv2.CAP_PROP_FRAME_WIDTH] == 320
        assert cap.props[cv2.CAP_PROP_FRAME_HEIGHT] == 240
        assert cap.props[cv2.CAP_PROP_FPS] == 30
        assert (cam.actual_width, cam.actual_height) == (320, 240)
        assert cam.is_running
        f1 = cam.read_latest()
        f2 = cam.read_latest(after_id=f1.frame_id)
        assert f2.frame_id > f1.frame_id
        assert f2.timestamp >= f1.timestamp
        assert f2.image.shape == (240, 320, 3)
    assert not cam.is_running
    assert cap.released == 1


def test_camera_lost_mid_stream_raises():
    cap = FakeCapture(good_reads=5)
    with Webcam(CFG, factory_for(cap)) as cam:
        last = 0
        with pytest.raises(CameraError, match="stopped delivering frames"):
            for _ in range(100):
                last = cam.read_latest(after_id=last, timeout=1.0).frame_id


def test_close_is_idempotent_and_read_after_close_fails():
    cap = FakeCapture()
    cam = Webcam(CFG, factory_for(cap)).open()
    first = cam.read_latest()
    cam.close()
    cam.close()
    assert cap.released == 1
    with pytest.raises(CameraError):
        cam.read_latest(after_id=first.frame_id + 10_000, timeout=0.2)


@pytest.mark.parametrize("system, expected", [
    ("Windows", "dshow"), ("Darwin", "avfoundation"), ("Linux", "v4l2"), ("Plan9", "any")])
def test_auto_backend_per_platform(system, expected):
    assert resolve_backend("auto", system)[0] == expected


def test_explicit_backend():
    assert resolve_backend("msmf") == ("msmf", cv2.CAP_MSMF)
