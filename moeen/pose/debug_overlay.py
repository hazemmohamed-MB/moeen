"""Compact evidence panel for calibration (toggle with ``d`` in the preview window).

It sits under the status box at the top of the picture, away from a person on the floor.

Five short lines, each "measured value / threshold", with ``>`` in front when that piece of
evidence currently points toward an alert. It shows exactly the numbers the detector uses,
next to the calibration values they are compared with, so a demo can be tuned by watching
which line flips:

    Evidence (> = past threshold)          d: hide
    > fall speed  3.42 / 2.00 tl/s
    > torso turn   +88 / 35 deg
    > posture     HORIZONTAL  tilt 89/60 deg  hips +1.62/1.20
    > stillness   0.012 / 0.060 tl  still 12/60 s
      score       0.55 / 0.60  down 100% of 3 s (need 70%)

The row builder is pure (no OpenCV), so it is unit-tested; ``draw_debug_panel`` draws it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

import cv2
import numpy as np

if TYPE_CHECKING:
    from moeen.config import AppConfig
    from moeen.detection import DetectorOutput
    from moeen.features import FeatureFrame

HEADER = "Evidence (> = past threshold)   d: hide"


@dataclass(frozen=True)
class EvidenceRow:
    label: str
    text: str
    met: bool          # this evidence currently supports an alert


def _f(v: float | None, spec: str) -> str:
    return "-" if v is None else format(v, spec)


def evidence_rows(output: "DetectorOutput | None", features: "FeatureFrame | None",
                  config: "AppConfig") -> list[EvidenceRow]:
    if output is None:
        return []
    e = output.evidence
    fd, fc, ic = config.fall_detection, config.features, config.immobility
    vel = e.peak_down_velocity
    rise = e.torso_angle_rise_deg
    tilt = features.torso_angle_deg if features is not None else None
    drop = features.hip_drop if features is not None else None
    motion = features.motion_magnitude if features is not None else None
    frac = e.abnormal_posture_fraction
    still_limit = ic.horizontal_still_alert_seconds * (ic.recent_candidate_factor
                                                       if e.recent_fall_candidate else 1.0)
    return [
        EvidenceRow("fall speed", f"{_f(vel, '.2f')} / {fd.fall_velocity_threshold:.2f} tl/s",
                    vel is not None and vel >= fd.fall_velocity_threshold),
        EvidenceRow("torso turn", f"{_f(rise, '+.0f')} / {fd.torso_angle_change_deg:.0f} deg",
                    rise is not None and rise >= fd.torso_angle_change_deg),
        EvidenceRow("posture", f"{e.posture}  tilt {_f(tilt, '.0f')}/{fc.horizontal_min_angle_deg:.0f}"
                               f" deg  hips {_f(drop, '+.2f')}/{fc.low_hip_drop:.2f}",
                    e.posture in ("LOW", "HORIZONTAL")),
        EvidenceRow("stillness", f"{_f(motion, '.3f')} / {ic.still_motion_threshold:.3f} tl"
                                 f"  still {e.still_sustained_s:.0f}/{still_limit:.0f} s",
                    motion is not None and motion <= ic.still_motion_threshold),
        EvidenceRow("score", f"{output.score:.2f} / {fd.alert_score_threshold:.2f}  down "
                             f"{'-' if frac is None else f'{100 * frac:.0f}%'} of "
                             f"{fd.escalation_lookback_seconds:.0f} s "
                             f"(need {100 * fd.abnormal_posture_fraction:.0f}%)",
                    output.score >= fd.alert_score_threshold),
    ]


def debug_lines(rows: Sequence[EvidenceRow]) -> list[str]:
    if not rows:
        return []
    width = max(len(r.label) for r in rows)
    return [HEADER] + [f"{'>' if r.met else ' '} {r.label:<{width}}  {r.text}" for r in rows]


def draw_debug_panel(image: np.ndarray, lines: Sequence[str],
                     origin: tuple[int, int] = (10, 10)) -> None:
    """Small semi-transparent panel, by default under the status box at the top-left - the
    top of the frame, so it never covers a person lying on the floor (in place)."""
    if not lines:
        return
    h, w = image.shape[:2]
    scale = max(0.38, min(w, h) / 1150)
    font = cv2.FONT_HERSHEY_SIMPLEX
    sizes = [cv2.getTextSize(t, font, scale, 1)[0] for t in lines]
    line_h = max(s[1] for s in sizes) + max(4, int(8 * scale))
    box_w = min(w - 8, max(s[0] for s in sizes) + 12)
    box_h = line_h * len(lines) + 8
    x0, y0 = origin[0], min(origin[1], max(0, h - box_h))
    overlay = image.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + box_w, y0 + box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, image, 0.4, 0, dst=image)
    for i, text in enumerate(lines):
        color = (180, 180, 180) if i == 0 else (
            (80, 200, 255) if text.startswith(">") else (235, 235, 235))
        cv2.putText(image, text, (x0 + 6, y0 + line_h * (i + 1)), font, scale, color, 1, cv2.LINE_AA)
