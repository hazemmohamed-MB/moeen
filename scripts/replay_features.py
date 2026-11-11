"""Run the feature extractor on a recorded session and print/save the feature timeline.

Usage (from the project root):
    python scripts/replay_features.py data/recordings/sit_01.jsonl
    python scripts/replay_features.py data/recordings/sit_01.jsonl --csv data/sit_01_features.csv
    python scripts/replay_features.py data/recordings/*.jsonl          # summary per file

Use this to check what the features measure on REAL movements recorded with
    python -m moeen.app --record data/recordings/<name>.jsonl --label "<what you did>"
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moeen.config import ConfigError, load_config  # noqa: E402
from moeen.features import FeatureExtractor  # noqa: E402
from moeen.pose.recording import RecordingError, load_recording  # noqa: E402


def summarize(name: str, header: dict, frames: list) -> None:
    present = [f for f in frames if f.pose_present]
    dur = (frames[-1].timestamp_ms - frames[0].timestamp_ms) / 1000 if len(frames) > 1 else 0.0
    print(f"\n== {name}  label='{header.get('label', '')}'  {len(frames)} frames, {dur:.1f} s, "
          f"pose in {100 * len(present) / max(1, len(frames)):.0f}%")
    if not present:
        return
    counts = Counter(f.posture.value for f in present)
    print("   posture time share: " + ", ".join(
        f"{k} {100 * v / len(present):.0f}%" for k, v in counts.most_common()))

    def ext(field, fn, spec=".2f"):
        vals = [getattr(f, field) for f in present if getattr(f, field) is not None]
        return format(fn(vals), spec) if vals else "-"
    print(f"   hip velocity (torso lengths/s, + = down): max down {ext('hip_velocity', max, '+.2f')}, "
          f"max up {ext('hip_velocity', min, '+.2f')}")
    print(f"   torso angle max {ext('torso_angle_deg', max, '.0f')} deg, "
          f"hip drop max {ext('hip_drop', max, '+.2f')}, motion max {ext('motion_magnitude', max, '.3f')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recordings", nargs="+", help="one or more .jsonl recordings")
    parser.add_argument("--csv", help="write the full feature timeline of a single recording here")
    parser.add_argument("--config", help="config file (default: config/default.yaml)")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 4
    if args.csv and len(args.recordings) != 1:
        print("--csv needs exactly one recording")
        return 2

    status = 0
    for path in args.recordings:
        try:
            header, poses = load_recording(path)
        except RecordingError as exc:
            print(f"[FAIL] {exc}")
            status = 1
            continue
        extractor = FeatureExtractor(cfg.features)
        frames = [extractor.update(p) for p in poses]
        summarize(Path(path).name, header, frames)
        if args.csv and frames:
            out = Path(args.csv)
            out.parent.mkdir(parents=True, exist_ok=True)
            rows = [f.to_dict() for f in frames]
            with open(out, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            print(f"   wrote {len(rows)} rows to {out}")
    return status


if __name__ == "__main__":
    sys.exit(main())
