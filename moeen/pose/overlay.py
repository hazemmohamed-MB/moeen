"""Drawing helpers for the live preview (skeleton + status text).

The skeleton connections are read from the installed MediaPipe
(``vision.PoseLandmarksConnections.POSE_LANDMARKS``) instead of being copied by hand.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Sequence

import cv2
import numpy as np

from moeen.pose.landmark_utils import LEFT_SIDE, RIGHT_SIDE, is_visible, to_pixel
from moeen.types import PoseFrame

if TYPE_CHECKING:
    from moeen.detection.models import DetectorOutput
    from moeen.features.models import FeatureFrame

# BGR colour per detection state (on-screen indication; NORMAL draws no border)
STATE_COLORS: dict[str, tuple[int, int, int]] = {
    "POSSIBLE_FALL": (0, 200, 255),      # amber
    "MONITORING": (0, 230, 230),         # yellow
    "RECOVERY_WINDOW": (0, 140, 255),    # orange
    "ALERT": (0, 0, 255),                # red
    "RESOLVED": (0, 200, 0),             # green
}

# BGR colours
_LEFT = (255, 160, 0)     # blue-ish: person's left side
_RIGHT = (0, 140, 255)    # orange: person's right side
_CENTER = (230, 230, 230)
_TEXT = (255, 255, 255)
_TEXT_BG = (0, 0, 0)


@lru_cache(maxsize=1)
def pose_connections() -> tuple[tuple[int, int], ...]:
    """Skeleton edges as (start, end) landmark indices, from the installed MediaPipe."""
    from mediapipe.tasks.python import vision
    return tuple((c.start, c.end) for c in vision.PoseLandmarksConnections.POSE_LANDMARKS)


def _color_for(index: int) -> tuple[int, int, int]:
    if index in LEFT_SIDE:
        return _LEFT
    if index in RIGHT_SIDE:
        return _RIGHT
    return _CENTER


def draw_pose(image: np.ndarray, pose: PoseFrame, visibility_threshold: float = 0.5) -> int:
    """Draw the skeleton of ``pose`` onto ``image`` in place.

    Landmarks below ``visibility_threshold`` (and edges touching them) are skipped.

    Returns:
        Number of landmarks drawn.
    """
    if not pose.has_pose:
        return 0
    assert pose.landmarks is not None
    h, w = image.shape[:2]
    scale = max(1, round(min(w, h) / 360))
    pts = [to_pixel(lm, w, h) for lm in pose.landmarks]
    visible = [is_visible(lm, visibility_threshold) for lm in pose.landmarks]

    for start, end in pose_connections():
        if start < len(pts) and end < len(pts) and visible[start] and visible[end]:
            color = _color_for(end) if _color_for(start) == _color_for(end) else _CENTER
            cv2.line(image, pts[start], pts[end], color, 2 * scale, cv2.LINE_AA)
    drawn = 0
    for i, (pt, vis) in enumerate(zip(pts, visible)):
        if vis:
            cv2.circle(image, pt, 3 * scale, _color_for(i), -1, cv2.LINE_AA)
            drawn += 1
    return drawn


def draw_features(image: np.ndarray, features: "FeatureFrame | None") -> None:
    """Draw the measured torso axis (shoulder center - hip center) and the body center.

    Purely informational: shows what the feature layer measures, not an alert.
    """
    if features is None or not features.pose_present:
        return
    h, w = image.shape[:2]
    scale = max(1, round(min(w, h) / 360))

    def px(p):
        return int(round(p.x * w)), int(round(p.y * h))

    if features.shoulder_center is not None and features.hip_center is not None:
        cv2.line(image, px(features.shoulder_center), px(features.hip_center), (255, 255, 255),
                 3 * scale, cv2.LINE_AA)
    for p in (features.shoulder_center, features.hip_center):
        if p is not None:
            cv2.circle(image, px(p), 4 * scale, (255, 255, 255), -1, cv2.LINE_AA)
    if features.body_center is not None:
        cv2.circle(image, px(features.body_center), 6 * scale, (0, 0, 0), -1, cv2.LINE_AA)
        cv2.circle(image, px(features.body_center), 4 * scale, (0, 255, 255), -1, cv2.LINE_AA)


def feature_status_lines(features: "FeatureFrame | None") -> list[str]:
    """Human-readable feature summary for the preview window."""
    if features is None:
        return []
    if not features.pose_present:
        return ["Features: no person"]

    def fmt(v, spec):
        return "-" if v is None else format(v, spec)

    return [
        f"Posture {features.posture.value}  torso {fmt(features.torso_angle_deg, '.0f')} deg"
        f"  hip drop {fmt(features.hip_drop, '+.2f')}",
        f"hip v {fmt(features.hip_velocity, '+.2f')} tl/s  motion {fmt(features.motion_magnitude, '.3f')}"
        f"  scale:{features.scale_source.value}",
    ]


def detection_status_lines(output: "DetectorOutput | None") -> list[str]:
    """State, score and the most relevant timer for the preview window."""
    if output is None:
        return []
    t = output.timers
    cond = f" [{output.condition.value}]" if output.condition is not None else ""
    line = (f"STATE {output.state.value}{cond}  risk {output.risk_level.value}  "
            f"score {output.score:.2f} (system score)")
    if t.confirm_remaining_s is not None:
        line += f"  confirm {t.confirm_remaining_s:.1f}s"
    elif t.extension_remaining_s is not None:
        line += f"  escalate in {t.extension_remaining_s:.0f}s"
    elif t.recovery_remaining_s is not None:
        line += f"  recovery {t.recovery_remaining_s:.1f}s left"
    elif t.escalation_in_s is not None:
        line += f"  alert in {t.escalation_in_s:.0f}s"
    elif t.alert_elapsed_s is not None:
        line += f"  alert {t.alert_elapsed_s:.0f}s"
    return [line, output.status[:90]]


def alert_status_line(event: dict | None, sound: dict | None) -> str | None:
    """One line about the stored event and the alert sound, e.g.
    ``Event #3 NEW (unanswered) | sound: on (afplay), played 1x | a = assistance, m = mute``."""
    parts = []
    if event is not None:
        label = {"NEW": "NEW (unanswered)", "MONITORING": "MONITORING"}.get(event["status"],
                                                                           event["status"])
        parts.append(f"Event #{event['id']} {label}")
    if sound is not None:
        if not sound.get("enabled"):
            parts.append("sound: off")
        elif not sound.get("available"):
            parts.append("sound: no audio output")
        elif sound.get("muted"):
            parts.append("sound: MUTED")
        else:
            played = f", played {sound['plays']}x" if sound.get("plays") else ""
            parts.append(f"sound: on ({sound.get('backend')}){played}")
    if not parts:
        return None
    keys = "a = assistance, m = mute" if event is not None and event["status"] == "NEW" else "m = mute"
    return " | ".join(parts) + f" | {keys}"


def draw_state_banner(image: np.ndarray, output: "DetectorOutput | None") -> int:
    """Coloured border for non-NORMAL states, plus a thin top strip for ALERT (in place).

    The strip is at the TOP so it never hides a person lying near the bottom of the frame.
    Returns the strip height in pixels (0 if none), so text can be placed below it.
    """
    if output is None:
        return 0
    color = STATE_COLORS.get(output.state.value)
    if color is None:
        return 0
    h, w = image.shape[:2]
    thickness = max(4, min(w, h) // 60) * (2 if output.state.value == "ALERT" else 1)
    cv2.rectangle(image, (0, 0), (w - 1, h - 1), color, thickness)
    if output.state.value != "ALERT":
        return 0
    cond = output.condition.value if output.condition is not None else ""
    text = {"FALL": "ALERT - possible fall, no recovery: check on the person",
            "IMMOBILITY": "ALERT - down and not moving: check on the person",
            "LYING": "ALERT - lying for a long time: check on the person"}.get(
        cond, "ALERT - check on the person")
    scale = max(0.45, min(w, h) / 900)
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    strip = th + base + 10
    cv2.rectangle(image, (0, 0), (w, strip), color, -1)
    cv2.putText(image, text, (max(4, (w - tw) // 2), th + 5), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (255, 255, 255), 1, cv2.LINE_AA)
    return strip


def draw_status(image: np.ndarray, lines: Sequence[str], origin: tuple[int, int] = (10, 10)) -> int:
    """Draw text lines with a dark background box in the top-left corner (in place).
    Returns the y coordinate just below the box."""
    if not lines:
        return origin[1]
    h, w = image.shape[:2]
    font_scale = max(0.5, min(w, h) / 900)
    thickness = 1 if font_scale < 0.8 else 2
    sizes = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)[0] for t in lines]
    line_h = max(s[1] for s in sizes) + int(10 * font_scale)
    box_w = max(s[0] for s in sizes) + 16
    x0, y0 = origin
    overlay = image.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + box_w, y0 + line_h * len(lines) + 8), _TEXT_BG, -1)
    cv2.addWeighted(overlay, 0.55, image, 0.45, 0, dst=image)
    for i, text in enumerate(lines):
        y = y0 + 4 + line_h * (i + 1) - int(4 * font_scale)
        cv2.putText(image, text, (x0 + 8, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, _TEXT,
                    thickness, cv2.LINE_AA)
    return y0 + line_h * len(lines) + 8
