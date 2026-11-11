from mediapipe.tasks.python import vision

from moeen.pose import landmark_utils as lu
from moeen.pose.overlay import pose_connections
from moeen.types import Landmark


def test_index_constants_match_installed_mediapipe():
    enum = {m.name: m.value for m in vision.PoseLandmark}
    assert len(enum) == lu.NUM_LANDMARKS
    for name in ("NOSE", "LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP",
                 "LEFT_KNEE", "RIGHT_KNEE", "LEFT_ANKLE", "RIGHT_ANKLE", "LEFT_WRIST",
                 "RIGHT_WRIST", "LEFT_EAR", "RIGHT_EAR", "LEFT_EYE", "RIGHT_EYE"):
        assert getattr(lu, name) == enum[name], name


def test_left_right_sides_match_landmark_names():
    for member in vision.PoseLandmark:
        if "LEFT" in member.name:
            assert member.value in lu.LEFT_SIDE, member.name
        elif "RIGHT" in member.name:
            assert member.value in lu.RIGHT_SIDE, member.name
        else:
            assert member.value not in lu.LEFT_SIDE | lu.RIGHT_SIDE, member.name


def test_connections_come_from_mediapipe_and_are_valid():
    edges = pose_connections()
    assert len(edges) == len(vision.PoseLandmarksConnections.POSE_LANDMARKS)
    assert all(0 <= a < 33 and 0 <= b < 33 for a, b in edges)
    assert (lu.LEFT_SHOULDER, lu.RIGHT_SHOULDER) in edges


def test_visibility_and_pixel_helpers():
    assert lu.is_visible(Landmark(0, 0, 0, visibility=0.6), 0.5)
    assert not lu.is_visible(Landmark(0, 0, 0, visibility=0.4), 0.5)
    assert lu.is_visible(Landmark(0, 0, 0, visibility=None), 0.5)
    assert lu.to_pixel(Landmark(0.5, 0.25, 0), 640, 480) == (320, 120)
