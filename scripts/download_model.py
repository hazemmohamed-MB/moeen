"""Download the official MediaPipe PoseLandmarker model(s) into ./models.

Usage (from the project root):
    python scripts/download_model.py                 # the variant set in config/default.yaml
    python scripts/download_model.py --variant lite
    python scripts/download_model.py --variant all --force
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moeen.config import ConfigError, load_config  # noqa: E402
from moeen.pose.models import MODELS, model_path, validate_model_file  # noqa: E402


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "moeen-prototype"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 16):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    problems = validate_model_file(tmp)
    if problems:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("downloaded file is not a valid model: " + "; ".join(problems))
    shutil.move(str(tmp), dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", choices=[*MODELS, "all"],
                        help="model variant (default: pose.model_variant from config)")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args()

    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 4
    variants = list(MODELS) if args.variant == "all" else [args.variant or cfg.pose.model_variant]
    model_dir = cfg.pose.model_dir_path(ROOT)
    model_dir.mkdir(parents=True, exist_ok=True)

    status = 0
    for variant in variants:
        spec = MODELS[variant]
        dest = model_path(model_dir, variant)
        if dest.exists() and not args.force and not validate_model_file(dest):
            print(f"[skip] {dest.relative_to(ROOT)} already present ({dest.stat().st_size / 1e6:.1f} MB)")
            continue
        print(f"[get ] {variant}: {spec.url}")
        try:
            download(spec.url, dest)
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            print(f"[FAIL] {variant}: {exc}")
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                print("       macOS python.org builds: run 'Install Certificates.command' from "
                      "your Python folder, then retry.")
            print(f"       Manual fallback: download the URL above in a browser and save it as {dest}")
            status = 1
            continue
        print(f"[ ok ] saved {dest.relative_to(ROOT)} ({dest.stat().st_size / 1e6:.1f} MB)")
    return status


if __name__ == "__main__":
    sys.exit(main())
