"""Structural rules: the feature layer stays independent of the camera, OpenCV and MediaPipe."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PURE_PACKAGES = ["moeen/features", "moeen/detection"]
FORBIDDEN = {"cv2", "mediapipe", "moeen.camera", "moeen.pose.pose_estimator", "moeen.pose.overlay",
             "moeen.app"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", [p for pkg in PURE_PACKAGES for p in (ROOT / pkg).glob("*.py")],
                         ids=lambda p: p.name)
def test_feature_modules_do_not_import_camera_or_vision_libraries(path):
    bad = {m for m in imported_modules(path)
           if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)}
    assert not bad, f"{path.name} imports {bad}"


def test_detection_and_features_never_touch_the_database():
    # Detector logic must stay testable without a database (Phase 5 requirement).
    for pkg in PURE_PACKAGES:
        for path in (ROOT / pkg).glob("*.py"):
            mods = imported_modules(path)
            bad = {m for m in mods if m == "sqlite3" or m.startswith("moeen.database")
                   or m.startswith("moeen.alerts")}
            assert not bad, f"{path.name} imports {bad}"


def test_detector_does_not_read_the_wall_clock():
    # The detector's only clock is FeatureFrame.timestamp_ms, so tests are deterministic.
    for path in (ROOT / "moeen/detection").glob("*.py"):
        mods = imported_modules(path)
        assert "time" not in mods and "datetime" not in mods, path.name


def test_landmark_utils_is_pure():
    assert not imported_modules(ROOT / "moeen/pose/landmark_utils.py") & {"cv2", "mediapipe"}


@pytest.mark.parametrize("path", [p for pkg in ("moeen/api", "moeen/runtime")
                                  for p in (ROOT / pkg).glob("*.py")], ids=lambda p: p.name)
def test_web_side_never_opens_the_camera_or_pose_model(path):
    # Phase 6: the Python processing loop owns the webcam; the web server only reads what the
    # loop publishes and queues actions for it.
    bad = {m for m in imported_modules(path)
           if any(m == f or m.startswith(f + ".") for f in
                  ("mediapipe", "moeen.camera", "moeen.pose.pose_estimator", "moeen.app"))}
    assert not bad, f"{path.name} imports {bad}"


def test_alert_sound_policy_uses_only_detector_time():
    # cooldown / repeat timing must follow detector timestamps, so it is deterministic in tests
    mods = imported_modules(ROOT / "moeen/alerts/alert_manager.py")
    assert not mods & {"time", "datetime", "subprocess", "cv2"}, mods
