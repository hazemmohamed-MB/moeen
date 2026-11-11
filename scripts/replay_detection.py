"""Run features + the detection state machine (falls, lying, immobility) on recorded sessions
and print the state timeline.

Usage (from the project root):
    python scripts/replay_detection.py data/recordings/fall_01.jsonl
    python scripts/replay_detection.py data/recordings/*.jsonl            # one summary per file
    python scripts/replay_detection.py data/recordings/fall_01.jsonl --csv data/fall_01_states.csv
    python scripts/replay_detection.py data/recordings/*.jsonl --override-config demo/room.yaml

Record sessions with:
    python -m moeen.app --record data/recordings/<name>.jsonl --label "<what you did>"

Use it to tune config/default.yaml (fall_detection and immobility sections) on REAL
movements: every transition is printed with the evidence that caused it.
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
from moeen.detection import AssistanceDetector, DetectionState  # noqa: E402
from moeen.features import FeatureExtractor  # noqa: E402
from moeen.pose.recording import RecordingError, load_recording  # noqa: E402


def replay(cfg, poses):
    extractor = FeatureExtractor(cfg.features)
    detector = AssistanceDetector(cfg.fall_detection, cfg.immobility)
    return [detector.update(extractor.update(p)) for p in poses]


def summarize(name: str, header: dict, outs: list) -> None:
    if not outs:
        print(f"\n== {name}: no frames")
        return
    t0 = outs[0].timestamp_ms
    dur = (outs[-1].timestamp_ms - t0) / 1000
    print(f"\n== {name}  label='{header.get('label', '')}'  {len(outs)} frames, {dur:.1f} s")
    shares = Counter(o.state.value for o in outs)
    print("   time share: " + ", ".join(f"{k} {100 * v / len(outs):.0f}%" for k, v in shares.most_common()))
    trans = [t for o in outs for t in o.transitions]
    if not trans:
        print("   no transitions (stayed NORMAL)")
    for t in trans:
        print(f"   {(t.timestamp_ms - t0) / 1000:7.2f} s  {t.from_state.value:>15} -> "
              f"{t.to_state.value:<15} {t.reason}")
    alert_outs = [o for o in outs if any(t.to_state is DetectionState.ALERT for t in o.transitions)]
    by_kind = ", ".join(f"{o.incident.condition.value}/{o.incident.severity.value}" for o in alert_outs)
    print(f"   max score {max(o.score for o in outs):.2f}; alerts: {len(alert_outs)}"
          f"{' (' + by_kind + ')' if by_kind else ''}; final state: {outs[-1].state.value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recordings", nargs="+")
    parser.add_argument("--csv", help="per-frame state/score timeline for a single recording")
    parser.add_argument("--config", help="config file (default: config/default.yaml)")
    parser.add_argument("--override-config", help="YAML merged over --config (for tuning)")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config, args.override_config)
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
        outs = replay(cfg, poses)
        summarize(Path(path).name, header, outs)
        if args.csv and outs:
            out = Path(args.csv)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["t_s", "state", "condition", "risk", "score", "posture",
                            "peak_down_velocity", "torso_angle_rise_deg", "abnormal_fraction",
                            "mean_motion", "upright_hold_s", "low_sustained_s",
                            "still_sustained_s", "status"])
                t0 = outs[0].timestamp_ms
                for o in outs:
                    e = o.evidence
                    w.writerow([f"{(o.timestamp_ms - t0) / 1000:.3f}", o.state.value,
                                o.condition.value if o.condition else "", o.risk_level.value,
                                f"{o.score:.3f}", e.posture, e.peak_down_velocity,
                                e.torso_angle_rise_deg, e.abnormal_posture_fraction, e.mean_motion,
                                f"{e.upright_hold_s:.2f}", f"{e.low_sustained_s:.1f}",
                                f"{e.still_sustained_s:.1f}", o.status])
            print(f"   wrote {len(outs)} rows to {out}")
    return status


if __name__ == "__main__":
    sys.exit(main())
