"""Camera-only check (no pose model): opens the webcam and measures the real frame rate.

Usage (from the project root):
    python scripts/check_camera.py                    # camera from config, 3 s measurement
    python scripts/check_camera.py --camera-index 1 --show
    python scripts/check_camera.py --probe            # try indices 0-4 and report which open
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from moeen.camera.webcam import CameraError, Webcam  # noqa: E402
from moeen.config import ConfigError, load_config  # noqa: E402


def measure(cfg, seconds: float, show: bool) -> int:
    with Webcam(cfg.camera) as cam:
        print(f"Opened camera index {cfg.camera.index} via backend '{cam.backend_name}'")
        print(f"  requested {cfg.camera.width}x{cfg.camera.height} @ {cfg.camera.fps} fps")
        print(f"  actual    {cam.actual_width}x{cam.actual_height}, driver-reported fps {cam.reported_fps:.1f}")
        frames, last_id, t0 = 0, 0, time.monotonic()
        while time.monotonic() - t0 < seconds:
            frame = cam.read_latest(after_id=last_id)
            last_id = frame.frame_id
            frames += 1
            if show:
                cv2.imshow("Moeen camera check (q to quit)", frame.image)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
        elapsed = time.monotonic() - t0
        if show:
            cv2.destroyAllWindows()
        print(f"  measured  {frames / elapsed:.1f} fps over {elapsed:.1f} s")
    print("CAMERA OK")
    return 0


def probe(cfg) -> int:
    found = []
    for idx in range(5):
        try:
            with Webcam(cfg.with_overrides({"camera": {"index": idx, "open_timeout_seconds": 3.0}}).camera) as cam:
                print(f"  index {idx}: OK  {cam.actual_width}x{cam.actual_height}")
                found.append(idx)
        except CameraError:
            print(f"  index {idx}: not available")
    print(f"Working camera indices: {found or 'none'}")
    return 0 if found else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--camera-backend")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--show", action="store_true", help="show the raw camera window")
    parser.add_argument("--probe", action="store_true", help="try camera indices 0-4")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    try:
        cfg = load_config().with_overrides({"camera": {
            "index": args.camera_index, "width": args.width, "height": args.height,
            "backend": args.camera_backend}})
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 4
    try:
        return probe(cfg) if args.probe else measure(cfg, args.seconds, args.show)
    except CameraError as exc:
        print(f"CAMERA FAILED: {exc}")
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
