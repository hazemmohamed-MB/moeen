from pathlib import Path

import pytest

from moeen.config import (CALIBRATION_KEYS, DEFAULT_CALIBRATION_PATH, DEFAULT_CONFIG_PATH,
                          ConfigError, calibration_values, load_config)


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_default_config_loads_and_matches_yaml():
    cfg = load_config()
    assert cfg.camera.index == 0
    assert cfg.camera.width == 640 and cfg.camera.height == 480
    assert cfg.pose.model_variant == "full"
    assert cfg.display.show_window is True
    assert cfg.source_files == (str(DEFAULT_CONFIG_PATH), str(DEFAULT_CALIBRATION_PATH))


def test_override_file_is_deep_merged(tmp_path):
    override = write(tmp_path, "o.yaml", "camera:\n  index: 2\npose:\n  model_variant: lite\n")
    cfg = load_config(override_path=override)
    assert cfg.camera.index == 2
    assert cfg.camera.width == 640  # untouched keys keep base values
    assert cfg.pose.model_variant == "lite"


def test_cli_style_overrides_ignore_none():
    cfg = load_config().with_overrides({"camera": {"index": 1, "width": None}})
    assert cfg.camera.index == 1
    assert cfg.camera.width == 640


def test_int_accepted_for_float_field(tmp_path):
    p = write(tmp_path, "c.yaml", "camera:\n  open_timeout_seconds: 3\n")
    assert load_config(p).camera.open_timeout_seconds == 3.0


@pytest.mark.parametrize("text, fragment", [
    ("camera:\n  width: -5\n", "width/height must be positive"),
    ("camera:\n  index: one\n", "camera.index must be an integer"),
    ("camera:\n  backend: directx\n", "camera.backend"),
    ("camera:\n  colour: red\n", "unknown key(s) in 'camera': colour"),
    ("cameras:\n  index: 0\n", "unknown config section(s): cameras"),
    ("pose:\n  model_variant: xl\n", "pose.model_variant"),
    ("pose:\n  min_tracking_confidence: 1.5\n", "between 0 and 1"),
    ("display:\n  show_window: maybe\n", "must be true/false"),
    ("features:\n  upright_max_angle_deg: 70\n", "upright_max_angle_deg < horizontal_min_angle_deg"),
    ("features:\n  normal_hip_drop: 1.5\n", "normal_hip_drop must be smaller"),
    ("features:\n  velocity_window_seconds: 0\n", "velocity_window_seconds must be positive"),
    ("features:\n  min_visibility: 2\n", "between 0 and 1"),
    ("features:\n  history_seconds: 0.5\n", "must cover the motion"),
    ("fall_detection:\n  recovery_window_seconds: -1\n", "recovery_window_seconds must be positive"),
    ("fall_detection:\n  velocity_min_seconds: 0.9\n", "velocity_min_seconds must be shorter"),
    ("fall_detection:\n  confirm_posture_seconds: 3\n", "confirm_posture_seconds must be shorter"),
    ("fall_detection:\n  escalation_lookback_seconds: 30\n", "must not exceed recovery_window_seconds"),
    ("fall_detection:\n  alert_score_threshold: 1.5\n", "between 0 and 1"),
    ("fall_detection:\n  weight_velocity: -1\n", "weight_* must be >= 0"),
    ("fall_detection:\n  pose_loss_counts_as_abnormal: 1\n", "must be true/false"),
    ("immobility:\n  lying_monitor_seconds: 0\n", "lying_monitor_seconds must be positive"),
    ("immobility:\n  recent_candidate_factor: 1.5\n", "recent_candidate_factor must be in (0, 1]"),
    ("immobility:\n  low_still_alert_seconds: 30\n", "low_still_alert_seconds must be >="),
    ("immobility:\n  horizontal_alert_seconds: 20\n", "horizontal_alert_seconds must be 0 (off)"),
    ("immobility:\n  upright_still_monitor_seconds: 2\n", "upright_still_monitor_seconds must be 0"),
    ("immobility:\n  still_tolerance_seconds: -1\n", "still_tolerance_seconds must be >= 0"),
    ("- just\n- a list\n", "must be a mapping"),
])
def test_invalid_values_rejected(tmp_path, text, fragment):
    with pytest.raises(ConfigError) as err:
        load_config(write(tmp_path, "bad.yaml", text))
    assert fragment in str(err.value)


def test_invalid_override_rejected():
    with pytest.raises(ConfigError):
        load_config().with_overrides({"camera": {"height": 0}})


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_broken_yaml(tmp_path):
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write(tmp_path, "b.yaml", "camera: [unclosed\n"))


# ---------------------------------------------------------------- calibration file
def test_calibration_file_sets_the_named_thresholds(tmp_path):
    cal = write(tmp_path, "cal.yaml", "profile: test\nvalues:\n  fall_velocity_threshold: 2.7\n"
                                      "  recovery_window_seconds: 12\n  low_posture_hip_drop: 1.1\n")
    cfg = load_config(calibration_path=cal)
    assert cfg.fall_detection.fall_velocity_threshold == 2.7
    assert cfg.fall_detection.recovery_window_seconds == 12.0
    assert cfg.features.low_hip_drop == 1.1
    assert calibration_values(cfg)["fall_velocity_threshold"] == 2.7


def test_every_calibration_name_is_in_the_shipped_file_and_nowhere_else():
    import yaml
    shipped = yaml.safe_load(DEFAULT_CALIBRATION_PATH.read_text(encoding="utf-8"))["values"]
    assert set(shipped) == set(CALIBRATION_KEYS)               # all named values, clearly listed
    base = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    for name, ck in CALIBRATION_KEYS.items():
        assert ck.key not in (base.get(ck.section) or {}), f"{name} also set in default.yaml"
    cfg = load_config()
    assert calibration_values(cfg) == {k: float(v) for k, v in shipped.items()}


def test_override_and_cli_still_win_over_calibration(tmp_path):
    o = write(tmp_path, "o.yaml", "fall_detection:\n  fall_velocity_threshold: 3.3\n")
    assert load_config(override_path=o).fall_detection.fall_velocity_threshold == 3.3
    cfg = load_config().with_overrides({"fall_detection": {"recovery_window_seconds": 7}})
    assert cfg.fall_detection.recovery_window_seconds == 7.0


@pytest.mark.parametrize("text,fragment", [
    ("values:\n  fall_speed: 2\n", "unknown calibration value"),
    ("values:\n  fall_velocity_threshold: fast\n", "must be a number"),
    ("thresholds:\n  a: 1\n", "unknown top-level"),
    ("values:\n  recovery_window_seconds: -1\n", "recovery_window_seconds"),
])
def test_bad_calibration_rejected(tmp_path, text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_config(calibration_path=write(tmp_path, "c.yaml", text))


def test_base_file_may_not_also_set_a_calibrated_value(tmp_path):
    base = write(tmp_path, "base.yaml", "fall_detection:\n  fall_velocity_threshold: 2.0\n")
    assert load_config(base).fall_detection.fall_velocity_threshold == 2.0   # no calibration: fine
    write(tmp_path, "calibration.yaml", "values:\n  fall_velocity_threshold: 2.5\n")
    with pytest.raises(ConfigError, match="set them in config/calibration.yaml"):
        load_config(base)                        # the calibration next to it would silently win
