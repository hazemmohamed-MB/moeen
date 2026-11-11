"""Centralized configuration for Moeen.

All tunable settings live in ``config/default.yaml``, except the detection thresholds that
are calibrated for the camera setup: those live, under plain names, in
``config/calibration.yaml`` (see ``CALIBRATION_KEYS``). Load order, later wins:

    default.yaml  <  calibration.yaml  <  --override-config file  <  command-line flags

Every value is validated and exposed as frozen dataclasses, so no other module needs to
hard-code a setting.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH: Path = PROJECT_ROOT / "config" / "default.yaml"
DEFAULT_CALIBRATION_PATH: Path = PROJECT_ROOT / "config" / "calibration.yaml"

CAMERA_BACKENDS: tuple[str, ...] = ("auto", "any", "dshow", "msmf", "avfoundation", "v4l2")
MODEL_VARIANTS: tuple[str, ...] = ("lite", "full", "heavy")


class ConfigError(ValueError):
    """Raised when the configuration file is missing, malformed, or has invalid values."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _unit_interval(name: str, value: float) -> None:
    _require(0.0 <= value <= 1.0, f"{name} must be between 0 and 1 (got {value})")


@dataclass(frozen=True)
class CameraConfig:
    """Webcam capture settings."""

    index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    backend: str = "auto"
    open_timeout_seconds: float = 5.0
    read_failure_limit: int = 30

    def __post_init__(self) -> None:
        _require(self.index >= 0, f"camera.index must be >= 0 (got {self.index})")
        _require(self.width > 0 and self.height > 0,
                 f"camera.width/height must be positive (got {self.width}x{self.height})")
        _require(self.fps > 0, f"camera.fps must be positive (got {self.fps})")
        _require(self.backend in CAMERA_BACKENDS,
                 f"camera.backend must be one of {CAMERA_BACKENDS} (got {self.backend!r})")
        _require(self.open_timeout_seconds > 0, "camera.open_timeout_seconds must be positive")
        _require(self.read_failure_limit >= 1, "camera.read_failure_limit must be >= 1")


@dataclass(frozen=True)
class PoseConfig:
    """MediaPipe PoseLandmarker settings."""

    model_variant: str = "full"
    model_dir: str = "models"
    num_poses: int = 1
    min_pose_detection_confidence: float = 0.5
    min_pose_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5

    def __post_init__(self) -> None:
        _require(self.model_variant in MODEL_VARIANTS,
                 f"pose.model_variant must be one of {MODEL_VARIANTS} (got {self.model_variant!r})")
        _require(self.num_poses >= 1, "pose.num_poses must be >= 1")
        _unit_interval("pose.min_pose_detection_confidence", self.min_pose_detection_confidence)
        _unit_interval("pose.min_pose_presence_confidence", self.min_pose_presence_confidence)
        _unit_interval("pose.min_tracking_confidence", self.min_tracking_confidence)

    def model_dir_path(self, root: Path = PROJECT_ROOT) -> Path:
        """Absolute model directory (relative paths are resolved against the project root)."""
        path = Path(self.model_dir)
        return path if path.is_absolute() else root / path


@dataclass(frozen=True)
class FeatureConfig:
    """Feature-extraction settings (measurements and posture labels only - no alerting)."""

    history_seconds: float = 10.0
    min_visibility: float = 0.5
    min_presence: float = 0.5
    velocity_window_seconds: float = 0.3
    max_gap_seconds: float = 0.5
    motion_window_seconds: float = 1.0
    motion_min_coverage: float = 0.5
    default_torso_length: float = 0.25
    torso_reference_tau_seconds: float = 2.0
    standing_rise_tau_seconds: float = 0.5
    standing_fall_tau_seconds: float = 30.0
    normal_hip_drop: float = 0.6
    upright_max_angle_deg: float = 30.0
    horizontal_min_angle_deg: float = 60.0
    horizontal_min_aspect: float = 1.3
    low_hip_drop: float = 1.2
    lying_min_hip_drop: float = 0.6

    def __post_init__(self) -> None:
        for name in ("history_seconds", "velocity_window_seconds", "max_gap_seconds",
                     "motion_window_seconds", "default_torso_length",
                     "torso_reference_tau_seconds", "standing_rise_tau_seconds",
                     "standing_fall_tau_seconds", "horizontal_min_aspect", "low_hip_drop",
                     "lying_min_hip_drop", "normal_hip_drop"):
            _require(getattr(self, name) > 0, f"features.{name} must be positive")
        _require(self.normal_hip_drop < self.low_hip_drop,
                 "features.normal_hip_drop must be smaller than features.low_hip_drop")
        _unit_interval("features.min_visibility", self.min_visibility)
        _unit_interval("features.min_presence", self.min_presence)
        _unit_interval("features.motion_min_coverage", self.motion_min_coverage)
        _require(0 < self.upright_max_angle_deg < self.horizontal_min_angle_deg < 180,
                 "features: need 0 < upright_max_angle_deg < horizontal_min_angle_deg < 180")
        _require(self.history_seconds >= max(self.motion_window_seconds,
                                             self.velocity_window_seconds),
                 "features.history_seconds must cover the motion and velocity windows")


@dataclass(frozen=True)
class FallDetectionConfig:
    """Fall state-machine thresholds. Time values are seconds; angles are degrees;
    velocities are torso lengths per second (positive = downward)."""

    candidate_window_seconds: float = 0.6
    baseline_window_seconds: float = 1.0
    fall_velocity_threshold: float = 2.0
    velocity_min_seconds: float = 0.1
    torso_angle_change_deg: float = 35.0
    candidate_low_posture_score: float = 0.5
    confirm_window_seconds: float = 2.0
    confirm_posture_seconds: float = 0.3
    recovery_window_seconds: float = 10.0
    recovery_hold_seconds: float = 1.5
    escalation_lookback_seconds: float = 3.0
    abnormal_posture_fraction: float = 0.7
    low_motion_threshold: float = 0.08
    max_extension_seconds: float = 20.0
    alert_score_threshold: float = 0.6
    alert_clear_hold_seconds: float = 3.0
    resolved_hold_seconds: float = 3.0
    pose_loss_counts_as_abnormal: bool = True
    weight_velocity: float = 0.25
    weight_angle: float = 0.15
    weight_posture: float = 0.25
    weight_stillness: float = 0.15
    weight_persistence: float = 0.20

    def __post_init__(self) -> None:
        for name in ("candidate_window_seconds", "baseline_window_seconds",
                     "fall_velocity_threshold", "velocity_min_seconds", "torso_angle_change_deg",
                     "confirm_window_seconds", "confirm_posture_seconds",
                     "recovery_window_seconds", "recovery_hold_seconds",
                     "escalation_lookback_seconds", "low_motion_threshold",
                     "alert_clear_hold_seconds", "resolved_hold_seconds"):
            _require(getattr(self, name) > 0, f"fall_detection.{name} must be positive")
        _require(self.max_extension_seconds >= 0, "fall_detection.max_extension_seconds must be >= 0")
        _require(self.velocity_min_seconds < self.candidate_window_seconds,
                 "fall_detection.velocity_min_seconds must be shorter than candidate_window_seconds")
        _require(self.confirm_posture_seconds < self.confirm_window_seconds,
                 "fall_detection.confirm_posture_seconds must be shorter than confirm_window_seconds")
        _require(self.escalation_lookback_seconds <= self.recovery_window_seconds,
                 "fall_detection.escalation_lookback_seconds must not exceed recovery_window_seconds")
        _require(self.recovery_hold_seconds < self.recovery_window_seconds,
                 "fall_detection.recovery_hold_seconds must be shorter than recovery_window_seconds")
        _require(self.torso_angle_change_deg < 180, "fall_detection.torso_angle_change_deg must be < 180")
        for name in ("candidate_low_posture_score", "abnormal_posture_fraction",
                     "alert_score_threshold"):
            _unit_interval(f"fall_detection.{name}", getattr(self, name))
        weights = self.weights()
        _require(all(w >= 0 for w in weights.values()) and sum(weights.values()) > 0,
                 "fall_detection.weight_* must be >= 0 and not all zero")

    def weights(self) -> dict[str, float]:
        return {"velocity": self.weight_velocity, "angle": self.weight_angle,
                "posture": self.weight_posture, "stillness": self.weight_stillness,
                "persistence": self.weight_persistence}


@dataclass(frozen=True)
class ImmobilityConfig:
    """Sustained lying/low-posture and immobility thresholds (seconds; motion in torso lengths)."""

    lying_monitor_seconds: float = 5.0
    posture_tolerance_seconds: float = 1.0
    still_motion_threshold: float = 0.06
    still_tolerance_seconds: float = 0.5
    horizontal_still_alert_seconds: float = 60.0
    low_still_alert_seconds: float = 120.0
    horizontal_alert_seconds: float = 300.0
    upright_still_monitor_seconds: float = 300.0
    monitor_clear_seconds: float = 5.0
    recent_candidate_seconds: float = 60.0
    recent_candidate_factor: float = 0.5
    rearm_requires_upright: bool = True

    def __post_init__(self) -> None:
        for name in ("lying_monitor_seconds", "still_motion_threshold",
                     "horizontal_still_alert_seconds", "low_still_alert_seconds",
                     "monitor_clear_seconds"):
            _require(getattr(self, name) > 0, f"immobility.{name} must be positive")
        for name in ("posture_tolerance_seconds", "still_tolerance_seconds",
                     "horizontal_alert_seconds", "upright_still_monitor_seconds",
                     "recent_candidate_seconds"):
            _require(getattr(self, name) >= 0, f"immobility.{name} must be >= 0")
        _require(0 < self.recent_candidate_factor <= 1,
                 "immobility.recent_candidate_factor must be in (0, 1]")
        _require(self.lying_monitor_seconds < self.horizontal_still_alert_seconds,
                 "immobility.lying_monitor_seconds must be shorter than horizontal_still_alert_seconds")
        _require(self.horizontal_still_alert_seconds <= self.low_still_alert_seconds,
                 "immobility.low_still_alert_seconds must be >= horizontal_still_alert_seconds "
                 "(a clearly horizontal body is the stronger evidence)")
        _require(self.horizontal_alert_seconds == 0
                 or self.horizontal_alert_seconds > self.horizontal_still_alert_seconds,
                 "immobility.horizontal_alert_seconds must be 0 (off) or longer than "
                 "horizontal_still_alert_seconds")
        _require(self.upright_still_monitor_seconds == 0
                 or self.upright_still_monitor_seconds >= self.lying_monitor_seconds,
                 "immobility.upright_still_monitor_seconds must be 0 (off) or >= lying_monitor_seconds")


@dataclass(frozen=True)
class DatabaseConfig:
    """Local SQLite event history."""

    enabled: bool = True
    path: str = "data/moeen.db"

    def __post_init__(self) -> None:
        _require(bool(self.path.strip()), "database.path must not be empty")

    def path_resolved(self, root: Path = PROJECT_ROOT) -> Path:
        """Absolute database path (relative paths are resolved against the project root)."""
        p = Path(self.path)
        return p if p.is_absolute() else root / p


@dataclass(frozen=True)
class DashboardConfig:
    """Local Flask API + browser dashboard."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 5000
    status_poll_ms: int = 1000
    events_poll_ms: int = 3000
    stale_after_seconds: float = 3.0
    command_timeout_seconds: float = 2.0
    preview_enabled: bool = True
    preview_fps: float = 8.0
    preview_jpeg_quality: int = 70

    def __post_init__(self) -> None:
        _require(bool(self.host.strip()), "dashboard.host must not be empty")
        _require(0 <= self.port <= 65535, "dashboard.port must be 0-65535 (0 = any free port)")
        _require(self.status_poll_ms >= 200, "dashboard.status_poll_ms must be >= 200")
        _require(self.events_poll_ms >= 500, "dashboard.events_poll_ms must be >= 500")
        _require(self.stale_after_seconds > 0, "dashboard.stale_after_seconds must be positive")
        _require(self.command_timeout_seconds > 0, "dashboard.command_timeout_seconds must be positive")
        _require(0 < self.preview_fps <= 30, "dashboard.preview_fps must be in (0, 30]")
        _require(10 <= self.preview_jpeg_quality <= 100, "dashboard.preview_jpeg_quality must be 10-100")


SOUND_BACKENDS = ("auto", "winsound", "afplay", "paplay", "pw-play", "aplay", "bell", "none")
SOUND_SEVERITIES = ("LOW", "MEDIUM", "HIGH")


@dataclass(frozen=True)
class SoundConfig:
    """Local audible alert (PRD: on-screen alert + local sound)."""

    enabled: bool = True
    min_severity: str = "HIGH"           # sound only for alerts at or above this severity
    repeat_seconds: float = 30.0         # repeat while the alert stays unanswered (0 = once)
    max_plays_per_alert: int = 5         # including the first play
    cooldown_seconds: float = 10.0       # minimum gap between any two sounds (all incidents)
    backend: str = "auto"
    tone_hz: float = 880.0
    volume: float = 0.6
    play_timeout_seconds: float = 6.0
    max_failures: int = 3                # consecutive failures before a backend is given up

    def __post_init__(self) -> None:
        _require(self.min_severity in SOUND_SEVERITIES,
                 f"sound.min_severity must be one of {', '.join(SOUND_SEVERITIES)}")
        _require(self.backend in SOUND_BACKENDS,
                 f"sound.backend must be one of {', '.join(SOUND_BACKENDS)}")
        _require(self.repeat_seconds >= 0, "sound.repeat_seconds must be >= 0 (0 = play once)")
        _require(self.max_plays_per_alert >= 1, "sound.max_plays_per_alert must be >= 1")
        _require(self.cooldown_seconds >= 0, "sound.cooldown_seconds must be >= 0")
        _require(100 <= self.tone_hz <= 4000, "sound.tone_hz must be 100-4000")
        _unit_interval("sound.volume", self.volume)
        _require(self.play_timeout_seconds > 0, "sound.play_timeout_seconds must be positive")
        _require(self.max_failures >= 1, "sound.max_failures must be >= 1")


@dataclass(frozen=True)
class DisplayConfig:
    """Live preview window settings."""

    show_window: bool = True
    window_name: str = "Moeen - live pose preview (q / Esc to quit)"
    mirror: bool = True
    landmark_visibility_threshold: float = 0.5
    fps_window_seconds: float = 1.0
    console_log_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        _require(bool(self.window_name), "display.window_name must not be empty")
        _unit_interval("display.landmark_visibility_threshold", self.landmark_visibility_threshold)
        _require(self.fps_window_seconds > 0, "display.fps_window_seconds must be positive")
        _require(self.console_log_interval_seconds > 0,
                 "display.console_log_interval_seconds must be positive")


@dataclass(frozen=True)
class AppConfig:
    """Top-level configuration object passed around the application."""

    camera: CameraConfig = field(default_factory=CameraConfig)
    pose: PoseConfig = field(default_factory=PoseConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    fall_detection: FallDetectionConfig = field(default_factory=FallDetectionConfig)
    immobility: ImmobilityConfig = field(default_factory=ImmobilityConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    sound: SoundConfig = field(default_factory=SoundConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    source_files: tuple[str, ...] = ()

    def with_overrides(self, overrides: Mapping[str, Mapping[str, Any]]) -> "AppConfig":
        """Return a new validated config with ``{"section": {"key": value}}`` overrides applied.

        ``None`` values are ignored, so argparse results can be passed directly.
        """
        merged = self.to_dict()
        for section, values in overrides.items():
            for key, value in values.items():
                if value is not None:
                    merged.setdefault(section, {})[key] = value
        return _build(merged, self.source_files)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "camera": dataclasses.asdict(self.camera),
            "pose": dataclasses.asdict(self.pose),
            "features": dataclasses.asdict(self.features),
            "fall_detection": dataclasses.asdict(self.fall_detection),
            "immobility": dataclasses.asdict(self.immobility),
            "database": dataclasses.asdict(self.database),
            "dashboard": dataclasses.asdict(self.dashboard),
            "sound": dataclasses.asdict(self.sound),
            "display": dataclasses.asdict(self.display),
        }


_SECTIONS: dict[str, type] = {"camera": CameraConfig, "pose": PoseConfig,
                              "features": FeatureConfig, "fall_detection": FallDetectionConfig,
                              "immobility": ImmobilityConfig, "database": DatabaseConfig,
                              "dashboard": DashboardConfig, "sound": SoundConfig,
                              "display": DisplayConfig}


def _coerce(section: str, key: str, expected: Any, value: Any) -> Any:
    """Check a YAML value against the dataclass field type (int is accepted for float fields)."""
    where = f"{section}.{key}"
    if expected in (bool, "bool"):
        _require(isinstance(value, bool), f"{where} must be true/false (got {value!r})")
        return value
    if expected in (int, "int"):
        _require(isinstance(value, int) and not isinstance(value, bool),
                 f"{where} must be an integer (got {value!r})")
        return value
    if expected in (float, "float"):
        _require(isinstance(value, (int, float)) and not isinstance(value, bool),
                 f"{where} must be a number (got {value!r})")
        return float(value)
    if expected in (str, "str"):
        _require(isinstance(value, str), f"{where} must be a string (got {value!r})")
        return value
    return value


def _build_section(section: str, raw: Any) -> Any:
    cls = _SECTIONS[section]
    if raw is None:
        raw = {}
    _require(isinstance(raw, Mapping), f"section '{section}' must be a mapping")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = sorted(set(raw) - set(fields))
    _require(not unknown, f"unknown key(s) in '{section}': {', '.join(unknown)}")
    kwargs = {k: _coerce(section, k, fields[k].type, v) for k, v in raw.items()}
    return cls(**kwargs)


def _build(data: Mapping[str, Any], sources: tuple[str, ...]) -> AppConfig:
    unknown = sorted(set(data) - set(_SECTIONS))
    _require(not unknown, f"unknown config section(s): {', '.join(unknown)}")
    return AppConfig(
        camera=_build_section("camera", data.get("camera")),
        pose=_build_section("pose", data.get("pose")),
        features=_build_section("features", data.get("features")),
        fall_detection=_build_section("fall_detection", data.get("fall_detection")),
        immobility=_build_section("immobility", data.get("immobility")),
        database=_build_section("database", data.get("database")),
        dashboard=_build_section("dashboard", data.get("dashboard")),
        sound=_build_section("sound", data.get("sound")),
        display=_build_section("display", data.get("display")),
        source_files=sources,
    )


def _deep_merge(base: dict[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _deep_merge(dict(out[key]), value)
        else:
            out[key] = value
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    _require(isinstance(data, Mapping), f"top level of {path} must be a mapping")
    return dict(data)


@dataclass(frozen=True)
class CalibrationKey:
    section: str
    key: str
    unit: str
    meaning: str


# Plain calibration names (PRD section 11) -> the internal setting each one controls.
# A value is set in exactly one place: here-named values belong in config/calibration.yaml,
# not in default.yaml (enforced by load_config).
CALIBRATION_KEYS: dict[str, CalibrationKey] = {
    "decision_history_seconds": CalibrationKey(
        "fall_detection", "escalation_lookback_seconds", "s",
        "history window the detector judges at the end of the recovery window "
        "(share of low/horizontal frames, mean motion)"),
    "fall_velocity_threshold": CalibrationKey(
        "fall_detection", "fall_velocity_threshold", "torso lengths/s",
        "downward body-center speed that starts a possible fall"),
    "torso_angle_change_deg": CalibrationKey(
        "fall_detection", "torso_angle_change_deg", "deg",
        "torso rotation (toward horizontal) that must accompany the fast drop"),
    "torso_horizontal_deg": CalibrationKey(
        "features", "horizontal_min_angle_deg", "deg",
        "torso tilt from vertical beyond which the posture counts as horizontal (lying)"),
    "low_posture_hip_drop": CalibrationKey(
        "features", "low_hip_drop", "torso lengths",
        "hips this far below their standing height = low posture (floor level)"),
    "recovery_window_seconds": CalibrationKey(
        "fall_detection", "recovery_window_seconds", "s",
        "time after a confirmed fall for the person to get up before escalation"),
    "immobility_alert_seconds": CalibrationKey(
        "immobility", "horizontal_still_alert_seconds", "s",
        "lying and not moving this long raises an alert (halved right after a fall candidate)"),
    "fall_still_motion_threshold": CalibrationKey(
        "fall_detection", "low_motion_threshold", "torso lengths",
        "mean movement at or below this at the end of the recovery window = not getting up; "
        "must sit above the camera's jitter on a still person"),
    "immobility_motion_threshold": CalibrationKey(
        "immobility", "still_motion_threshold", "torso lengths",
        "movement at or below this counts as 'not moving' for the immobility timer"),
    "alert_score_threshold": CalibrationKey(
        "fall_detection", "alert_score_threshold", "0-1 system score",
        "minimum rule-based score for the normal fall escalation (not a probability)"),
}


def _read_calibration(path: Path) -> tuple[dict[str, Any], str]:
    """Translate a calibration file (plain names) into nested config overrides."""
    data = _read_yaml(path)
    unknown_top = sorted(set(data) - {"profile", "values"})
    _require(not unknown_top, f"{path}: unknown top-level key(s): {', '.join(unknown_top)} "
                              "(expected 'profile' and 'values')")
    values = data.get("values") or {}
    _require(isinstance(values, Mapping), f"{path}: 'values' must be a mapping")
    unknown = sorted(set(values) - set(CALIBRATION_KEYS))
    _require(not unknown, f"{path}: unknown calibration value(s): {', '.join(unknown)}. "
                          f"Known: {', '.join(CALIBRATION_KEYS)}")
    nested: dict[str, Any] = {}
    for name, value in values.items():
        _require(isinstance(value, (int, float)) and not isinstance(value, bool),
                 f"{path}: calibration value {name} must be a number (got {value!r})")
        ck = CALIBRATION_KEYS[name]
        nested.setdefault(ck.section, {})[ck.key] = value
    return nested, str(data.get("profile") or path.stem)


def calibration_values(config: "AppConfig") -> dict[str, float]:
    """The effective value of every calibration name (for logs, overlays and reports)."""
    out = {}
    for name, ck in CALIBRATION_KEYS.items():
        out[name] = getattr(getattr(config, ck.section), ck.key)
    return out


def load_config(path: Path | str | None = None,
                override_path: Path | str | None = None,
                calibration_path: Path | str | None | bool = True) -> AppConfig:
    """Load and validate configuration.

    Args:
        path: base config file (defaults to ``config/default.yaml``).
        override_path: optional YAML file whose values are deep-merged over the base
            (e.g. a room-specific demo config).
        calibration_path: calibration file with plain-named thresholds. ``True`` (default)
            uses ``config/calibration.yaml`` next to the base file if it exists; ``False`` or
            ``None`` skips calibration (the code defaults apply); a path must exist.
    """
    base_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data = _read_yaml(base_path)
    sources = [str(base_path)]
    if calibration_path is True:
        auto = base_path.parent / DEFAULT_CALIBRATION_PATH.name
        calibration_path = auto if auto.is_file() else None
    if calibration_path:
        # one place per value: a base file must not also set what the calibration sets
        doubled = sorted(name for name, ck in CALIBRATION_KEYS.items()
                         if isinstance(data.get(ck.section), Mapping) and ck.key in data[ck.section])
        _require(not doubled, f"{base_path} sets calibrated value(s) {', '.join(doubled)}; set "
                              "them in config/calibration.yaml instead (one place per value)")
        nested, _profile = _read_calibration(Path(calibration_path))
        data = _deep_merge(data, nested)
        sources.append(str(calibration_path))
    if override_path is not None:
        data = _deep_merge(data, _read_yaml(Path(override_path)))
        sources.append(str(override_path))
    return _build(data, tuple(sources))
