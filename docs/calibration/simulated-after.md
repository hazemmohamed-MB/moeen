# Moeen calibration report (synthetic)

**Simulated runs.** A stick figure performs each scenario with random variation and is 'filmed' at 15/30 fps, near/far, good/dim light (landmark jitter, dropped frames). This checks the decision logic and threshold margins only - it is not an observation of real people. Academic prototype; no medical or safety claim.

## Calibration values used

| Name | Value |
|---|---|
| `decision_history_seconds` | 3 |
| `fall_velocity_threshold` | 2 |
| `torso_angle_change_deg` | 35 |
| `torso_horizontal_deg` | 60 |
| `low_posture_hip_drop` | 1.2 |
| `recovery_window_seconds` | 10 |
| `immobility_alert_seconds` | 60 |
| `fall_still_motion_threshold` | 0.1 |
| `immobility_motion_threshold` | 0.06 |
| `alert_score_threshold` | 0.6 |

## Summary per scenario

| Scenario | Expected | Runs | Pass | Warn | Fail | Peak speed tl/s (min-max) | Torso turn deg | Max hip drop tl | Alert after landing s |
|---|---|---|---|---|---|---|---|---|---|
| Standing | no event, no alert | 24 | 24 | 0 | 0 | 0.07-2.44 | 13-19 | 0.04-0.41 | - |
| Walking | no event, no alert | 24 | 24 | 0 | 0 | 0.35-1.15 | 3-13 | 0.08-0.20 | - |
| Sitting down on a chair | no event, no alert | 24 | 24 | 0 | 0 | 1.10-2.53 | 19-37 | 0.94-1.42 | - |
| Bending to pick something up | no event, no alert | 24 | 16 | 8 | 0 | 1.19-2.25 | 41-93 | 0.08-0.99 | - |
| Lying down slowly and staying | no fall incident, no HIGH alert, no sound (watching / a MEDIUM alert after long stillness is allowed) | 24 | 24 | 0 | 0 | 0.94-2.03 | 54-71 | 1.67-2.13 | - |
| Quick fall + immediate recovery | no alert; a possible-fall state may appear but must be cancelled | 24 | 24 | 0 | 0 | 3.91-5.23 | 91-98 | 1.66-1.84 | - |
| Fall + remain still | FALL alert, HIGH severity, sound, within recovery window + 5 s of landing | 72 | 72 | 0 | 0 | 2.73-6.31 | 90-99 | 1.67-2.23 | 9.8-10.6 |

## Not passed (8)

| Scenario | Variant | Verdict | States | Why |
|---|---|---|---|---|
| bending | 30fps-near-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |
| bending | 30fps-near-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |
| bending | 30fps-far-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |
| bending | 30fps-far-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |
| bending | 15fps-near-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |
| bending | 15fps-near-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |
| bending | 15fps-far-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |
| bending | 15fps-far-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | possible-fall check shown for 1.9 s (not stored, no alert) |

## Every run

| Scenario | Variant | Verdict | States | Alert | Sounds | Peak speed | Torso turn | Hip drop | Max score | Possible-fall s |
|---|---|---|---|---|---|---|---|---|---|---|
| standing | 30fps-near-good-s1 | PASS | NORMAL | - | 0 | 0.08 | 14 | 0.04 | 0.03 | 0.0 |
| standing | 30fps-near-good-s2 | PASS | NORMAL | - | 0 | 0.07 | 13 | 0.05 | 0.03 | 0.0 |
| standing | 30fps-near-good-s3 | PASS | NORMAL | - | 0 | 0.10 | 15 | 0.05 | 0.04 | 0.0 |
| standing | 30fps-near-dim-s1 | PASS | NORMAL | - | 0 | 0.21 | 16 | 0.10 | 0.04 | 0.0 |
| standing | 30fps-near-dim-s2 | PASS | NORMAL | - | 0 | 0.93 | 15 | 0.27 | 0.07 | 0.0 |
| standing | 30fps-near-dim-s3 | PASS | NORMAL | - | 0 | 0.33 | 17 | 0.23 | 0.04 | 0.0 |
| standing | 30fps-far-good-s1 | PASS | NORMAL | - | 0 | 0.12 | 15 | 0.06 | 0.04 | 0.0 |
| standing | 30fps-far-good-s2 | PASS | NORMAL | - | 0 | 0.11 | 14 | 0.07 | 0.03 | 0.0 |
| standing | 30fps-far-good-s3 | PASS | NORMAL | - | 0 | 0.16 | 16 | 0.07 | 0.04 | 0.0 |
| standing | 30fps-far-dim-s1 | PASS | NORMAL | - | 0 | 0.32 | 18 | 0.16 | 0.05 | 0.0 |
| standing | 30fps-far-dim-s2 | PASS | NORMAL | - | 0 | 1.44 | 16 | 0.41 | 0.11 | 0.0 |
| standing | 30fps-far-dim-s3 | PASS | NORMAL | - | 0 | 0.51 | 19 | 0.35 | 0.05 | 0.0 |
| standing | 15fps-near-good-s1 | PASS | NORMAL | - | 0 | 0.08 | 13 | 0.04 | 0.03 | 0.0 |
| standing | 15fps-near-good-s2 | PASS | NORMAL | - | 0 | 0.11 | 13 | 0.05 | 0.03 | 0.0 |
| standing | 15fps-near-good-s3 | PASS | NORMAL | - | 0 | 0.10 | 14 | 0.05 | 0.03 | 0.0 |
| standing | 15fps-near-dim-s1 | PASS | NORMAL | - | 0 | 0.21 | 15 | 0.10 | 0.04 | 0.0 |
| standing | 15fps-near-dim-s2 | PASS | NORMAL | - | 0 | 1.58 | 15 | 0.21 | 0.11 | 0.0 |
| standing | 15fps-near-dim-s3 | PASS | NORMAL | - | 0 | 0.26 | 15 | 0.13 | 0.04 | 0.0 |
| standing | 15fps-far-good-s1 | PASS | NORMAL | - | 0 | 0.12 | 13 | 0.06 | 0.03 | 0.0 |
| standing | 15fps-far-good-s2 | PASS | NORMAL | - | 0 | 0.17 | 14 | 0.07 | 0.03 | 0.0 |
| standing | 15fps-far-good-s3 | PASS | NORMAL | - | 0 | 0.15 | 14 | 0.07 | 0.04 | 0.0 |
| standing | 15fps-far-dim-s1 | PASS | NORMAL | - | 0 | 0.33 | 15 | 0.16 | 0.05 | 0.0 |
| standing | 15fps-far-dim-s2 | PASS | NORMAL | - | 0 | 2.44 | 16 | 0.32 | 0.17 | 0.0 |
| standing | 15fps-far-dim-s3 | PASS | NORMAL | - | 0 | 0.40 | 16 | 0.19 | 0.05 | 0.0 |
| walking | 30fps-near-good-s1 | PASS | NORMAL | - | 0 | 0.37 | 4 | 0.10 | 0.03 | 0.0 |
| walking | 30fps-near-good-s2 | PASS | NORMAL | - | 0 | 0.37 | 4 | 0.09 | 0.03 | 0.0 |
| walking | 30fps-near-good-s3 | PASS | NORMAL | - | 0 | 0.37 | 3 | 0.09 | 0.03 | 0.0 |
| walking | 30fps-near-dim-s1 | PASS | NORMAL | - | 0 | 0.43 | 10 | 0.15 | 0.05 | 0.0 |
| walking | 30fps-near-dim-s2 | PASS | NORMAL | - | 0 | 0.84 | 8 | 0.13 | 0.06 | 0.0 |
| walking | 30fps-near-dim-s3 | PASS | NORMAL | - | 0 | 0.49 | 8 | 0.14 | 0.04 | 0.0 |
| walking | 30fps-far-good-s1 | PASS | NORMAL | - | 0 | 0.39 | 7 | 0.11 | 0.04 | 0.0 |
| walking | 30fps-far-good-s2 | PASS | NORMAL | - | 0 | 0.40 | 6 | 0.10 | 0.04 | 0.0 |
| walking | 30fps-far-good-s3 | PASS | NORMAL | - | 0 | 0.41 | 5 | 0.11 | 0.03 | 0.0 |
| walking | 30fps-far-dim-s1 | PASS | NORMAL | - | 0 | 0.49 | 13 | 0.19 | 0.06 | 0.0 |
| walking | 30fps-far-dim-s2 | PASS | NORMAL | - | 0 | 1.15 | 11 | 0.20 | 0.09 | 0.0 |
| walking | 30fps-far-dim-s3 | PASS | NORMAL | - | 0 | 0.58 | 10 | 0.19 | 0.05 | 0.0 |
| walking | 15fps-near-good-s1 | PASS | NORMAL | - | 0 | 0.35 | 4 | 0.08 | 0.03 | 0.0 |
| walking | 15fps-near-good-s2 | PASS | NORMAL | - | 0 | 0.39 | 3 | 0.10 | 0.03 | 0.0 |
| walking | 15fps-near-good-s3 | PASS | NORMAL | - | 0 | 0.38 | 3 | 0.09 | 0.03 | 0.0 |
| walking | 15fps-near-dim-s1 | PASS | NORMAL | - | 0 | 0.42 | 8 | 0.13 | 0.04 | 0.0 |
| walking | 15fps-near-dim-s2 | PASS | NORMAL | - | 0 | 0.49 | 8 | 0.13 | 0.05 | 0.0 |
| walking | 15fps-near-dim-s3 | PASS | NORMAL | - | 0 | 0.45 | 8 | 0.14 | 0.04 | 0.0 |
| walking | 15fps-far-good-s1 | PASS | NORMAL | - | 0 | 0.36 | 7 | 0.10 | 0.03 | 0.0 |
| walking | 15fps-far-good-s2 | PASS | NORMAL | - | 0 | 0.42 | 5 | 0.11 | 0.04 | 0.0 |
| walking | 15fps-far-good-s3 | PASS | NORMAL | - | 0 | 0.40 | 4 | 0.11 | 0.03 | 0.0 |
| walking | 15fps-far-dim-s1 | PASS | NORMAL | - | 0 | 0.50 | 13 | 0.16 | 0.05 | 0.0 |
| walking | 15fps-far-dim-s2 | PASS | NORMAL | - | 0 | 0.68 | 9 | 0.18 | 0.06 | 0.0 |
| walking | 15fps-far-dim-s3 | PASS | NORMAL | - | 0 | 0.56 | 11 | 0.18 | 0.05 | 0.0 |
| sitting | 30fps-near-good-s1 | PASS | NORMAL | - | 0 | 1.20 | 26 | 0.94 | 0.26 | 0.0 |
| sitting | 30fps-near-good-s2 | PASS | NORMAL | - | 0 | 1.37 | 35 | 0.95 | 0.29 | 0.0 |
| sitting | 30fps-near-good-s3 | PASS | NORMAL | - | 0 | 1.81 | 19 | 0.95 | 0.29 | 0.0 |
| sitting | 30fps-near-dim-s1 | PASS | NORMAL | - | 0 | 1.10 | 29 | 1.15 | 0.30 | 0.0 |
| sitting | 30fps-near-dim-s2 | PASS | NORMAL | - | 0 | 1.53 | 36 | 1.18 | 0.31 | 0.0 |
| sitting | 30fps-near-dim-s3 | PASS | NORMAL | - | 0 | 1.82 | 20 | 1.21 | 0.31 | 0.0 |
| sitting | 30fps-far-good-s1 | PASS | NORMAL | - | 0 | 1.19 | 27 | 0.96 | 0.27 | 0.0 |
| sitting | 30fps-far-good-s2 | PASS | NORMAL | - | 0 | 1.37 | 36 | 0.98 | 0.29 | 0.0 |
| sitting | 30fps-far-good-s3 | PASS | NORMAL | - | 0 | 1.82 | 19 | 0.97 | 0.29 | 0.0 |
| sitting | 30fps-far-dim-s1 | PASS | NORMAL | - | 0 | 1.21 | 31 | 1.28 | 0.33 | 0.0 |
| sitting | 30fps-far-dim-s2 | PASS | NORMAL | - | 0 | 2.42 | 37 | 1.33 | 0.35 | 0.0 |
| sitting | 30fps-far-dim-s3 | PASS | NORMAL | - | 0 | 1.82 | 23 | 1.38 | 0.33 | 0.0 |
| sitting | 15fps-near-good-s1 | PASS | NORMAL | - | 0 | 1.18 | 26 | 0.94 | 0.25 | 0.0 |
| sitting | 15fps-near-good-s2 | PASS | NORMAL | - | 0 | 1.36 | 34 | 0.95 | 0.29 | 0.0 |
| sitting | 15fps-near-good-s3 | PASS | NORMAL | - | 0 | 1.77 | 19 | 0.95 | 0.28 | 0.0 |
| sitting | 15fps-near-dim-s1 | PASS | NORMAL | - | 0 | 1.17 | 27 | 1.17 | 0.30 | 0.0 |
| sitting | 15fps-near-dim-s2 | PASS | NORMAL | - | 0 | 1.60 | 34 | 1.18 | 0.32 | 0.0 |
| sitting | 15fps-near-dim-s3 | PASS | NORMAL | - | 0 | 1.73 | 19 | 1.24 | 0.39 | 0.0 |
| sitting | 15fps-far-good-s1 | PASS | NORMAL | - | 0 | 1.17 | 26 | 0.96 | 0.26 | 0.0 |
| sitting | 15fps-far-good-s2 | PASS | NORMAL | - | 0 | 1.36 | 34 | 0.98 | 0.29 | 0.0 |
| sitting | 15fps-far-good-s3 | PASS | NORMAL | - | 0 | 1.76 | 19 | 0.97 | 0.29 | 0.0 |
| sitting | 15fps-far-dim-s1 | PASS | NORMAL | - | 0 | 1.18 | 27 | 1.32 | 0.34 | 0.0 |
| sitting | 15fps-far-dim-s2 | PASS | NORMAL | - | 0 | 2.53 | 34 | 1.34 | 0.36 | 0.0 |
| sitting | 15fps-far-dim-s3 | PASS | NORMAL | - | 0 | 2.40 | 21 | 1.42 | 0.43 | 0.0 |
| bending | 30fps-near-good-s1 | PASS | NORMAL | - | 0 | 1.38 | 42 | 0.78 | 0.27 | 0.0 |
| bending | 30fps-near-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.25 | 47 | 0.84 | 0.39 | 1.9 |
| bending | 30fps-near-good-s3 | PASS | NORMAL | - | 0 | 1.20 | 86 | 0.09 | 0.25 | 0.0 |
| bending | 30fps-near-dim-s1 | PASS | NORMAL | - | 0 | 1.45 | 43 | 0.86 | 0.30 | 0.0 |
| bending | 30fps-near-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.24 | 49 | 0.92 | 0.40 | 1.9 |
| bending | 30fps-near-dim-s3 | PASS | NORMAL | - | 0 | 1.21 | 90 | 0.16 | 0.28 | 0.0 |
| bending | 30fps-far-good-s1 | PASS | NORMAL | - | 0 | 1.40 | 42 | 0.80 | 0.28 | 0.0 |
| bending | 30fps-far-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.25 | 48 | 0.86 | 0.39 | 1.9 |
| bending | 30fps-far-good-s3 | PASS | NORMAL | - | 0 | 1.20 | 87 | 0.11 | 0.26 | 0.0 |
| bending | 30fps-far-dim-s1 | PASS | NORMAL | - | 0 | 1.51 | 45 | 0.92 | 0.32 | 0.0 |
| bending | 30fps-far-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.24 | 50 | 0.99 | 0.42 | 1.9 |
| bending | 30fps-far-dim-s3 | PASS | NORMAL | - | 0 | 1.22 | 93 | 0.23 | 0.29 | 0.0 |
| bending | 15fps-near-good-s1 | PASS | NORMAL | - | 0 | 1.36 | 42 | 0.77 | 0.26 | 0.0 |
| bending | 15fps-near-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.24 | 48 | 0.83 | 0.39 | 1.9 |
| bending | 15fps-near-good-s3 | PASS | NORMAL | - | 0 | 1.19 | 86 | 0.08 | 0.25 | 0.0 |
| bending | 15fps-near-dim-s1 | PASS | NORMAL | - | 0 | 1.39 | 42 | 0.88 | 0.28 | 0.0 |
| bending | 15fps-near-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.24 | 51 | 0.88 | 0.42 | 1.9 |
| bending | 15fps-near-dim-s3 | PASS | NORMAL | - | 0 | 1.21 | 88 | 0.13 | 0.26 | 0.0 |
| bending | 15fps-far-good-s1 | PASS | NORMAL | - | 0 | 1.37 | 41 | 0.79 | 0.26 | 0.0 |
| bending | 15fps-far-good-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.24 | 49 | 0.84 | 0.40 | 1.9 |
| bending | 15fps-far-good-s3 | PASS | NORMAL | - | 0 | 1.19 | 86 | 0.09 | 0.25 | 0.0 |
| bending | 15fps-far-dim-s1 | PASS | NORMAL | - | 0 | 1.55 | 44 | 0.96 | 0.32 | 0.0 |
| bending | 15fps-far-dim-s2 | WARN | NORMAL > POSSIBLE_FALL > NORMAL | - | 0 | 2.24 | 54 | 0.93 | 0.46 | 1.9 |
| bending | 15fps-far-dim-s3 | PASS | NORMAL | - | 0 | 1.27 | 90 | 0.18 | 0.28 | 0.0 |
| slow_lying | 30fps-near-good-s1 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.8 s | 0 | 1.05 | 64 | 1.68 | 0.60 | 0.0 |
| slow_lying | 30fps-near-good-s2 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 69.6 s | 0 | 0.99 | 55 | 1.67 | 0.60 | 0.0 |
| slow_lying | 30fps-near-good-s3 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.9 s | 0 | 0.96 | 67 | 1.67 | 0.60 | 0.0 |
| slow_lying | 30fps-near-dim-s1 | PASS | NORMAL > MONITORING | - | 0 | 1.10 | 67 | 1.90 | 0.53 | 0.0 |
| slow_lying | 30fps-near-dim-s2 | PASS | NORMAL > MONITORING | - | 0 | 1.11 | 58 | 1.95 | 0.39 | 0.0 |
| slow_lying | 30fps-near-dim-s3 | PASS | NORMAL > MONITORING | - | 0 | 1.01 | 69 | 1.89 | 0.45 | 0.0 |
| slow_lying | 30fps-far-good-s1 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.9 s | 0 | 1.07 | 65 | 1.71 | 0.60 | 0.0 |
| slow_lying | 30fps-far-good-s2 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 69.6 s | 0 | 1.03 | 56 | 1.70 | 0.60 | 0.0 |
| slow_lying | 30fps-far-good-s3 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.9 s | 0 | 0.97 | 68 | 1.69 | 0.60 | 0.0 |
| slow_lying | 30fps-far-dim-s1 | PASS | NORMAL > MONITORING | - | 0 | 1.18 | 71 | 2.04 | 0.43 | 0.0 |
| slow_lying | 30fps-far-dim-s2 | PASS | NORMAL > MONITORING | - | 0 | 1.42 | 61 | 2.13 | 0.40 | 0.0 |
| slow_lying | 30fps-far-dim-s3 | PASS | NORMAL > MONITORING | - | 0 | 1.06 | 71 | 2.03 | 0.43 | 0.0 |
| slow_lying | 15fps-near-good-s1 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.8 s | 0 | 1.01 | 62 | 1.68 | 0.60 | 0.0 |
| slow_lying | 15fps-near-good-s2 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 69.6 s | 0 | 0.98 | 54 | 1.67 | 0.60 | 0.0 |
| slow_lying | 15fps-near-good-s3 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.9 s | 0 | 0.94 | 67 | 1.67 | 0.60 | 0.0 |
| slow_lying | 15fps-near-dim-s1 | PASS | NORMAL > MONITORING | - | 0 | 1.06 | 64 | 1.86 | 0.51 | 0.0 |
| slow_lying | 15fps-near-dim-s2 | PASS | NORMAL > MONITORING | - | 0 | 1.32 | 56 | 1.94 | 0.39 | 0.0 |
| slow_lying | 15fps-near-dim-s3 | PASS | NORMAL > MONITORING | - | 0 | 1.08 | 69 | 1.76 | 0.49 | 0.0 |
| slow_lying | 15fps-far-good-s1 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.8 s | 0 | 1.02 | 63 | 1.70 | 0.60 | 0.0 |
| slow_lying | 15fps-far-good-s2 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 69.7 s | 0 | 1.00 | 55 | 1.70 | 0.60 | 0.0 |
| slow_lying | 15fps-far-good-s3 | PASS | NORMAL > MONITORING > ALERT | IMMOBILITY/MEDIUM at 68.9 s | 0 | 0.98 | 68 | 1.70 | 0.60 | 0.0 |
| slow_lying | 15fps-far-dim-s1 | PASS | NORMAL > MONITORING | - | 0 | 1.12 | 66 | 1.99 | 0.43 | 0.0 |
| slow_lying | 15fps-far-dim-s2 | PASS | NORMAL > MONITORING | - | 0 | 2.03 | 58 | 2.11 | 0.40 | 0.0 |
| slow_lying | 15fps-far-dim-s3 | PASS | NORMAL > MONITORING | - | 0 | 1.20 | 71 | 1.83 | 0.43 | 0.0 |
| fall_recover | 30fps-near-good-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.94 | 92 | 1.68 | 0.73 | 0.4 |
| fall_recover | 30fps-near-good-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.11 | 91 | 1.68 | 0.68 | 0.4 |
| fall_recover | 30fps-near-good-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.28 | 92 | 1.67 | 0.74 | 0.4 |
| fall_recover | 30fps-near-dim-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.99 | 94 | 1.75 | 0.72 | 0.4 |
| fall_recover | 30fps-near-dim-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.21 | 92 | 1.77 | 0.67 | 0.4 |
| fall_recover | 30fps-near-dim-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.29 | 95 | 1.74 | 0.72 | 0.4 |
| fall_recover | 30fps-far-good-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.96 | 92 | 1.70 | 0.73 | 0.4 |
| fall_recover | 30fps-far-good-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.14 | 91 | 1.71 | 0.67 | 0.4 |
| fall_recover | 30fps-far-good-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.28 | 93 | 1.70 | 0.73 | 0.4 |
| fall_recover | 30fps-far-dim-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.04 | 96 | 1.81 | 0.72 | 0.4 |
| fall_recover | 30fps-far-dim-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.30 | 93 | 1.84 | 0.68 | 0.4 |
| fall_recover | 30fps-far-dim-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.28 | 98 | 1.79 | 0.72 | 0.4 |
| fall_recover | 15fps-near-good-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.91 | 91 | 1.66 | 0.72 | 0.5 |
| fall_recover | 15fps-near-good-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.02 | 92 | 1.67 | 0.67 | 0.4 |
| fall_recover | 15fps-near-good-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.26 | 91 | 1.66 | 0.73 | 0.4 |
| fall_recover | 15fps-near-dim-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.95 | 93 | 1.71 | 0.72 | 0.5 |
| fall_recover | 15fps-near-dim-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.01 | 94 | 1.74 | 0.68 | 0.5 |
| fall_recover | 15fps-near-dim-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.87 | 93 | 1.71 | 0.72 | 0.4 |
| fall_recover | 15fps-far-good-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.93 | 91 | 1.68 | 0.72 | 0.5 |
| fall_recover | 15fps-far-good-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.02 | 92 | 1.69 | 0.68 | 0.4 |
| fall_recover | 15fps-far-good-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 4.28 | 92 | 1.68 | 0.73 | 0.4 |
| fall_recover | 15fps-far-dim-s1 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.97 | 94 | 1.75 | 0.72 | 0.5 |
| fall_recover | 15fps-far-dim-s2 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 3.99 | 96 | 1.79 | 0.68 | 0.5 |
| fall_recover | 15fps-far-dim-s3 | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > NORMAL | - | 0 | 5.23 | 95 | 1.75 | 0.72 | 0.4 |
| fall_still | 30fps-near-good-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.6 s | 1 | 5.42 | 92 | 1.69 | 1.00 | 0.3 |
| fall_still | 30fps-near-good-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.77 | 92 | 1.69 | 0.99 | 0.4 |
| fall_still | 30fps-near-good-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.86 | 91 | 1.69 | 0.93 | 0.4 |
| fall_still | 30fps-near-good-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.42 | 91 | 1.68 | 1.00 | 0.4 |
| fall_still | 30fps-near-good-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.79 | 91 | 1.68 | 0.99 | 0.4 |
| fall_still | 30fps-near-good-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.89 | 91 | 1.68 | 0.93 | 0.4 |
| fall_still | 30fps-near-good-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.42 | 92 | 1.67 | 1.00 | 0.4 |
| fall_still | 30fps-near-good-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.74 | 92 | 1.67 | 0.98 | 0.4 |
| fall_still | 30fps-near-good-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.84 | 92 | 1.67 | 0.93 | 0.4 |
| fall_still | 30fps-near-dim-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.6 s | 1 | 5.42 | 94 | 2.00 | 1.00 | 0.3 |
| fall_still | 30fps-near-dim-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.86 | 94 | 2.01 | 0.99 | 0.4 |
| fall_still | 30fps-near-dim-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.84 | 94 | 2.01 | 0.93 | 0.4 |
| fall_still | 30fps-near-dim-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.43 | 95 | 1.77 | 1.00 | 0.4 |
| fall_still | 30fps-near-dim-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.86 | 93 | 1.77 | 0.99 | 0.4 |
| fall_still | 30fps-near-dim-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.95 | 93 | 1.77 | 0.93 | 0.4 |
| fall_still | 30fps-near-dim-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.44 | 94 | 1.95 | 1.00 | 0.4 |
| fall_still | 30fps-near-dim-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.75 | 96 | 1.96 | 0.98 | 0.4 |
| fall_still | 30fps-near-dim-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.82 | 96 | 1.96 | 0.93 | 0.4 |
| fall_still | 30fps-far-good-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.6 s | 1 | 5.42 | 93 | 1.72 | 1.00 | 0.3 |
| fall_still | 30fps-far-good-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.80 | 92 | 1.72 | 0.99 | 0.4 |
| fall_still | 30fps-far-good-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.86 | 92 | 1.72 | 0.93 | 0.4 |
| fall_still | 30fps-far-good-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.42 | 93 | 1.71 | 1.00 | 0.4 |
| fall_still | 30fps-far-good-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.81 | 92 | 1.71 | 0.99 | 0.4 |
| fall_still | 30fps-far-good-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.91 | 91 | 1.71 | 0.93 | 0.4 |
| fall_still | 30fps-far-good-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.43 | 93 | 1.69 | 1.00 | 0.4 |
| fall_still | 30fps-far-good-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.75 | 93 | 1.70 | 0.98 | 0.4 |
| fall_still | 30fps-far-good-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.83 | 93 | 1.70 | 0.93 | 0.4 |
| fall_still | 30fps-far-dim-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.6 s | 1 | 5.41 | 97 | 2.20 | 0.97 | 0.3 |
| fall_still | 30fps-far-dim-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.5 s | 1 | 3.93 | 96 | 2.22 | 0.97 | 0.4 |
| fall_still | 30fps-far-dim-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.5 s | 1 | 2.99 | 96 | 2.22 | 0.91 | 0.4 |
| fall_still | 30fps-far-dim-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.43 | 98 | 1.84 | 0.97 | 0.4 |
| fall_still | 30fps-far-dim-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.93 | 94 | 1.84 | 0.97 | 0.4 |
| fall_still | 30fps-far-dim-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 3.00 | 94 | 1.84 | 0.91 | 0.4 |
| fall_still | 30fps-far-dim-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.45 | 98 | 2.12 | 0.98 | 0.4 |
| fall_still | 30fps-far-dim-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.8 s | 2 | 3.75 | 99 | 2.14 | 0.96 | 0.4 |
| fall_still | 30fps-far-dim-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.80 | 99 | 2.13 | 0.90 | 0.4 |
| fall_still | 15fps-near-good-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.34 | 92 | 1.67 | 1.00 | 0.3 |
| fall_still | 15fps-near-good-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.74 | 91 | 1.67 | 0.98 | 0.4 |
| fall_still | 15fps-near-good-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 2.84 | 90 | 1.67 | 0.93 | 0.5 |
| fall_still | 15fps-near-good-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.37 | 92 | 1.69 | 1.00 | 0.4 |
| fall_still | 15fps-near-good-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.71 | 92 | 1.69 | 0.98 | 0.5 |
| fall_still | 15fps-near-good-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 2.91 | 92 | 1.68 | 0.93 | 0.5 |
| fall_still | 15fps-near-good-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.38 | 91 | 1.68 | 1.00 | 0.3 |
| fall_still | 15fps-near-good-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.73 | 91 | 1.68 | 0.98 | 0.4 |
| fall_still | 15fps-near-good-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 2.81 | 91 | 1.68 | 0.93 | 0.5 |
| fall_still | 15fps-near-dim-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.31 | 94 | 2.02 | 1.00 | 0.3 |
| fall_still | 15fps-near-dim-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.77 | 93 | 2.02 | 0.99 | 0.4 |
| fall_still | 15fps-near-dim-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 2.83 | 91 | 1.99 | 0.93 | 0.5 |
| fall_still | 15fps-near-dim-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.40 | 94 | 1.78 | 1.00 | 0.4 |
| fall_still | 15fps-near-dim-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.71 | 94 | 1.78 | 0.98 | 0.5 |
| fall_still | 15fps-near-dim-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 3.00 | 94 | 1.77 | 0.94 | 0.5 |
| fall_still | 15fps-near-dim-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.98 | 93 | 1.96 | 1.00 | 0.3 |
| fall_still | 15fps-near-dim-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 4.00 | 93 | 1.96 | 1.00 | 0.4 |
| fall_still | 15fps-near-dim-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.73 | 93 | 1.96 | 0.92 | 0.5 |
| fall_still | 15fps-far-good-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.33 | 92 | 1.69 | 1.00 | 0.3 |
| fall_still | 15fps-far-good-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.75 | 91 | 1.69 | 0.98 | 0.4 |
| fall_still | 15fps-far-good-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 2.84 | 91 | 1.69 | 0.93 | 0.5 |
| fall_still | 15fps-far-good-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.38 | 93 | 1.72 | 1.00 | 0.4 |
| fall_still | 15fps-far-good-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.71 | 93 | 1.72 | 0.98 | 0.5 |
| fall_still | 15fps-far-good-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 2.94 | 92 | 1.71 | 0.93 | 0.5 |
| fall_still | 15fps-far-good-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.39 | 92 | 1.70 | 1.00 | 0.3 |
| fall_still | 15fps-far-good-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.73 | 92 | 1.70 | 0.98 | 0.4 |
| fall_still | 15fps-far-good-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.78 | 92 | 1.70 | 0.92 | 0.4 |
| fall_still | 15fps-far-dim-s1-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.29 | 96 | 2.23 | 0.98 | 0.3 |
| fall_still | 15fps-far-dim-s1-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.80 | 94 | 2.23 | 0.96 | 0.4 |
| fall_still | 15fps-far-dim-s1-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 2.83 | 93 | 2.19 | 0.90 | 0.5 |
| fall_still | 15fps-far-dim-s2-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 5.42 | 96 | 1.86 | 0.98 | 0.4 |
| fall_still | 15fps-far-dim-s2-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 3.71 | 96 | 1.85 | 0.96 | 0.4 |
| fall_still | 15fps-far-dim-s2-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.1 s | 2 | 3.08 | 96 | 1.85 | 0.92 | 0.5 |
| fall_still | 15fps-far-dim-s3-fall0.6s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.7 s | 1 | 6.31 | 95 | 2.13 | 0.98 | 0.3 |
| fall_still | 15fps-far-dim-s3-fall0.9s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 13.9 s | 2 | 4.25 | 95 | 2.13 | 0.98 | 0.4 |
| fall_still | 15fps-far-dim-s3-fall1.2s | PASS | NORMAL > POSSIBLE_FALL > RECOVERY_WINDOW > ALERT | FALL/HIGH at 14.0 s | 2 | 2.91 | 95 | 2.13 | 0.91 | 0.5 |
