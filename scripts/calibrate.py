"""Run the 7 calibration scenarios and write an observation report.

Usage (from the project root):
    python scripts/calibrate.py --synthetic                      # simulated webcam conditions
    python scripts/calibrate.py --synthetic --set fall_velocity_threshold=1.8   # try a value
    python scripts/calibrate.py data/recordings/*.jsonl          # REAL recordings (preferred)
    python scripts/calibrate.py data/recordings/x.jsonl --scenario bending

Recordings are matched to a scenario by their --label or file name (standing, walking,
sitting, bending, slow_lying, fall_recover, fall_still). Record them with:
    python -m moeen.app --record data/recordings/fall_still_01.jsonl --label "fall_still"

The report (Markdown) goes to data/calibration/. Exit code 0 = no FAIL, 1 = some FAIL.
Results describe this prototype under the recorded/simulated conditions only; they are not
a measure of medical accuracy or real-world safety.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moeen.calibration import (FAIL, SCENARIOS, markdown_report, observe,  # noqa: E402
                               scenario_for, summarize)
from moeen.config import CALIBRATION_KEYS, ConfigError, load_config  # noqa: E402

SIM_NOTE = ("**Simulated runs.** A stick figure performs each scenario with random variation "
            "and is 'filmed' at 15/30 fps, near/far, good/dim light (landmark jitter, dropped "
            "frames). This checks the decision logic and threshold margins only - it is not an "
            "observation of real people. Academic prototype; no medical or safety claim.")
REAL_NOTE = ("**Real recordings** made with the laptop webcam. Results hold for this camera, "
             "room and these people only. Academic prototype; no medical or safety claim.")


def parse_set(items):
    out = {}
    for item in items or []:
        name, _, value = item.partition("=")
        if name not in CALIBRATION_KEYS:
            raise ConfigError(f"--set: unknown calibration name {name!r}; known: {', '.join(CALIBRATION_KEYS)}")
        try:
            out[name] = float(value)
        except ValueError:
            raise ConfigError(f"--set {name}: {value!r} is not a number") from None
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("recordings", nargs="*", help=".jsonl pose recordings")
    p.add_argument("--synthetic", action="store_true", help="run the simulated webcam scenarios")
    p.add_argument("--seeds", type=int, default=3, help="simulated runs per scenario and condition")
    p.add_argument("--scenario", choices=list(SCENARIOS), help="scenario for all given recordings")
    p.add_argument("--config")
    p.add_argument("--calibration", metavar="PATH")
    p.add_argument("--set", action="append", metavar="NAME=VALUE",
                   help="try a calibration value without editing the file (repeatable)")
    p.add_argument("--out", help="report path (default data/calibration/<time>-<kind>.md)")
    p.add_argument("--brief", action="store_true", help="leave the every-run table out of the report")
    args = p.parse_args(argv)
    if not args.synthetic and not args.recordings:
        p.error("give recordings or --synthetic")
    try:
        cfg = load_config(args.config, calibration_path=args.calibration or True)
        tried = parse_set(args.set)
        if tried:
            cfg = cfg.with_overrides({CALIBRATION_KEYS[n].section: {CALIBRATION_KEYS[n].key: v}
                                      for n, v in tried.items()} if len(tried) == 1 else
                                     _group(tried))
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 4

    observations = []
    if args.synthetic:
        sys.path.insert(0, str(ROOT / "tests"))
        from webcam_scenarios import all_runs
        for key, frames, land, variant in all_runs(seeds=tuple(range(1, args.seeds + 1))):
            observations.append(observe(frames, cfg, key, variant, landing_s=land))
    for path in args.recordings:
        from moeen.pose.recording import RecordingError, load_recording
        try:
            header, frames = load_recording(path)
        except (RecordingError, OSError) as exc:
            print(f"skipping {path}: {exc}")
            continue
        key = args.scenario or scenario_for(f"{header.get('label', '')} {Path(path).stem}")
        if key is None:
            print(f"skipping {path}: cannot tell the scenario from its label/name; use --scenario")
            continue
        observations.append(observe(frames, cfg, key, Path(path).stem))
    if not observations:
        print("Nothing to evaluate.")
        return 1

    kind = "synthetic" if args.synthetic and not args.recordings else (
        "recordings" if not args.synthetic else "mixed")
    note = SIM_NOTE if kind == "synthetic" else REAL_NOTE if kind == "recordings" else SIM_NOTE + "\n\n" + REAL_NOTE
    if tried:
        note += "\n\nTried values (not saved): " + ", ".join(f"`{k}={v:g}`" for k, v in tried.items())
    report = markdown_report(observations, cfg, title=f"Moeen calibration report ({kind})",
                             note=note, detail=not args.brief)
    out = Path(args.out) if args.out else ROOT / "data" / "calibration" / (
        f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{kind}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    print(f"{'scenario':<14}{'runs':>5}{'pass':>6}{'warn':>6}{'fail':>6}   peak speed tl/s   torso turn deg")
    for s in summarize(observations):
        print(f"{s.scenario:<14}{s.runs:>5}{s.passed:>6}{s.warned:>6}{s.failed:>6}   "
              f"{s.peak_velocity[0]:5.2f} - {s.peak_velocity[1]:5.2f}    "
              f"{s.peak_angle_rise[0]:4.0f} - {s.peak_angle_rise[1]:4.0f}")
    fails = [o for o in observations if o.verdict == FAIL]
    for o in fails[:15]:
        print(f"  FAIL {o.scenario} [{o.variant}]: {o.reason}")
    if len(fails) > 15:
        print(f"  ... {len(fails) - 15} more in the report")
    print(f"Report: {out}")
    return 1 if fails else 0


def _group(tried):
    out: dict = {}
    for n, v in tried.items():
        out.setdefault(CALIBRATION_KEYS[n].section, {})[CALIBRATION_KEYS[n].key] = v
    return out


if __name__ == "__main__":
    sys.exit(main())
