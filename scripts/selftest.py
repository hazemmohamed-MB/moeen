"""Moeen self-test - checks the installation WITHOUT using the webcam.

Usage (from the project root):
    python scripts/selftest.py
    python scripts/selftest.py --image path/to/photo_of_a_person.jpg

Checks: Python/package versions, conflicting OpenCV installs, config validity, the installed
MediaPipe Tasks API, the model file, a real PoseLandmarker inference (blank frame, plus your
photo if --image is given), overlay drawing, and whether OpenCV can open windows.
Exit code 0 = all required checks passed.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import platform
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f" - {detail}" if detail else ""))


def check_versions() -> bool:
    record("INFO", "Python", f"{platform.python_version()} on {platform.system()} {platform.machine()}")
    ok = True
    for mod in ("numpy", "cv2", "mediapipe", "yaml"):
        try:
            m = __import__(mod)
            record("PASS", f"import {mod}", getattr(m, "__version__", "?"))
        except Exception as exc:  # noqa: BLE001
            record("FAIL", f"import {mod}", str(exc))
            ok = False
    return ok


def check_opencv_conflicts() -> bool:
    installed = {d.metadata["Name"].lower() for d in md.distributions() if d.metadata["Name"]}
    cv_pkgs = sorted(n for n in installed if n.startswith("opencv-"))
    if len(cv_pkgs) > 1:
        record("WARN", "OpenCV packages", f"several installed {cv_pkgs}; they overwrite each other's "
               "cv2. Fix: pip uninstall -y " + " ".join(cv_pkgs) + " && pip install -r requirements.txt")
        return True
    record("PASS", "OpenCV packages", ", ".join(cv_pkgs) or "none found via pip metadata")
    return True


def check_config():
    from moeen.config import ConfigError, load_config
    try:
        cfg = load_config()
    except ConfigError as exc:
        record("FAIL", "config/default.yaml", str(exc))
        return None
    c = cfg.camera
    record("PASS", "config/default.yaml",
           f"camera index={c.index} {c.width}x{c.height} backend={c.backend}; model={cfg.pose.model_variant}")
    return cfg


def check_api() -> bool:
    from moeen.pose.pose_estimator import check_mediapipe_api, mediapipe_version
    problems = check_mediapipe_api()
    if problems:
        record("FAIL", "MediaPipe Tasks API", f"mediapipe {mediapipe_version()}: " + "; ".join(problems))
        return False
    record("PASS", "MediaPipe Tasks API", f"PoseLandmarker (VIDEO mode) available in {mediapipe_version()}")
    return True


def check_model(cfg) -> bool:
    from moeen.pose.models import model_path, validate_model_file
    path = model_path(cfg.pose.model_dir_path(ROOT), cfg.pose.model_variant)
    problems = validate_model_file(path)
    if problems:
        record("FAIL", "model file", "; ".join(problems) +
               f" -> run: python scripts/download_model.py --variant {cfg.pose.model_variant}")
        return False
    record("PASS", "model file", f"{path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB)")
    return True


def check_inference(cfg, image_path: str | None) -> bool:
    import cv2
    import numpy as np

    from moeen.pose.overlay import draw_pose, pose_connections
    from moeen.pose.pose_estimator import MediaPipePoseEstimator

    ok = True
    with MediaPipePoseEstimator(cfg.pose) as est:
        blank = np.zeros((cfg.camera.height, cfg.camera.width, 3), np.uint8)
        t0 = time.perf_counter()
        n = 15
        for i in range(n):
            pose = est.detect(blank, i * 33)
        ms = (time.perf_counter() - t0) * 1000 / n
        if pose.has_pose:
            record("FAIL", "inference on blank frame", "a pose was reported on an all-black image")
            ok = False
        else:
            record("PASS", "inference on blank frame", f"0 poses as expected, {ms:.1f} ms/frame "
                   "(detector only; with a person in view expect more)")

    if image_path:
        img = cv2.imread(image_path)
        if img is None:
            record("FAIL", "inference on --image", f"cannot read {image_path}")
            return False
        # Fresh estimator so tracking state from the blank frames does not matter.
        with MediaPipePoseEstimator(cfg.pose) as est:
            t0 = time.perf_counter()
            n = 10
            for i in range(n):
                pose = est.detect(img, i * 33)
            ms = (time.perf_counter() - t0) * 1000 / n
        if not pose.has_pose:
            record("WARN", "inference on --image", "no person found - use a photo with a clearly "
                   "visible full or upper body")
        else:
            drawn = draw_pose(img, pose, cfg.display.landmark_visibility_threshold)
            out = ROOT / "data" / "selftest_overlay.jpg"
            out.parent.mkdir(exist_ok=True)
            cv2.imwrite(str(out), img)
            record("PASS", "inference on --image",
                   f"{len(pose.landmarks)} landmarks, {drawn} drawn, {ms:.1f} ms/frame; "
                   f"overlay saved to {out.relative_to(ROOT)}")

    record("PASS" if len(pose_connections()) > 0 else "FAIL", "skeleton connections",
           f"{len(pose_connections())} edges from the installed MediaPipe")
    return ok


def check_gui() -> None:
    import cv2
    info = cv2.getBuildInformation()
    gui = info.split("GUI:", 1)[1].split("Media I/O:", 1)[0] if "GUI:" in info else ""
    if "YES" in gui:
        backend = gui.strip().splitlines()[0].strip() if gui.strip() else "?"
        record("PASS", "OpenCV window support", f"GUI backend {backend}")
    else:
        record("WARN", "OpenCV window support", "this OpenCV build reports no GUI backend; the "
               "preview window will not open (headless build installed?)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", help="optional photo of a person to run real pose inference on")
    args = parser.parse_args()

    print("Moeen self-test (no camera needed)\n" + "-" * 40)
    try:
        if check_versions():
            check_opencv_conflicts()
            cfg = check_config()
            if cfg is not None and check_api() and check_model(cfg):
                check_inference(cfg, args.image)
            check_gui()
    except Exception:  # noqa: BLE001 - report anything unexpected as a failure
        record("FAIL", "unexpected error", traceback.format_exc().strip().splitlines()[-1])
        traceback.print_exc()

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    warned = [r for r in RESULTS if r[0] == "WARN"]
    print("-" * 40)
    if failed:
        print(f"SELF-TEST FAILED: {len(failed)} failure(s), {len(warned)} warning(s)")
        return 1
    print(f"SELF-TEST PASSED ({len(warned)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
