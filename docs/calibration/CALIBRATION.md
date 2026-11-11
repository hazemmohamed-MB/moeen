# Moeen calibration record - laptop webcam demo (Phase 8)

> Academic prototype. Nothing here measures medical accuracy or guarantees real-world
> safety. Every number below was measured **in simulation** unless it says otherwise.

## 1. What was run, and what it can and cannot tell us

The seven scenarios were run through the real feature extractor, detector and alert-sound
policy (`python scripts/calibrate.py --synthetic`). The person is a **simulated stick figure**
(`tests/webcam_scenarios.py`) that performs each scenario with random variation (speed,
depth, sway). It is "filmed" under typical laptop-webcam conditions:

| Condition | Values |
|---|---|
| Frame rate | 30 fps, 15 fps (heavy model or a slow laptop) |
| Distance | near: torso 0.22 frame heights (about 2.5 m); far: torso 0.14 (about 4 m) |
| Light | good: landmark jitter 0.003 frame heights; dim: jitter 0.008, plus about 5% lost frames on the floor and tracking glitches (whole skeleton jumps 0.03-0.08 for 1-2 frames, in about 0.5% of frames) |
| Runs | 3 seeds per scenario and condition; "fall + remain still" uses 3 fall speeds (0.6 / 0.9 / 1.2 s to the floor) |

That gives 216 runs. A stress run at 10 fps with jitter 0.012 was added to find where the
system breaks.

**What this shows:** whether the decision logic meets each scenario's rule, and how much
margin each threshold has against camera noise, frame rate and distance.

**What it cannot show:** how real bodies, clothes, furniture, lighting and MediaPipe's own
errors behave. That needs recordings from the real webcam (section 6). Until those exist,
treat every margin below as optimistic.

## 2. Calibration values (`config/calibration.yaml`)

| Name | Value | Controls |
|---|---|---|
| `decision_history_seconds` | 3.0 | history window judged at the end of the recovery window |
| `fall_velocity_threshold` | 2.0 tl/s | downward speed that starts a possible fall |
| `torso_angle_change_deg` | 35 | torso rotation that must come with the drop |
| `torso_horizontal_deg` | 60 | tilt beyond which the body counts as horizontal |
| `low_posture_hip_drop` | 1.2 tl | hips this far below standing height = low posture |
| `recovery_window_seconds` | 10 | time to get up after a confirmed fall |
| `immobility_alert_seconds` | 60 | lying still this long = alert |
| `fall_still_motion_threshold` | **0.10** (was 0.08) | "not getting up" at the end of the recovery window |
| `immobility_motion_threshold` | 0.06 | "not moving" for the immobility timer |
| `alert_score_threshold` | 0.6 | minimum system score for the fall escalation |

tl = torso lengths, the shoulder-to-hip distance. Using this unit keeps the values the
same whether the person is near or far.

## 3. Observations per scenario (after the adjustment, 216 simulated runs)

| # | Scenario | Rule | Result | What the evidence did |
|---|---|---|---|---|
| 1 | Standing | no event, no alert | 24/24 pass | Torso turn 13-19 deg, hips within 0.41 tl of standing. Tracking glitches produced speed spikes up to 2.44 tl/s, above the 2.0 threshold, but the other two signals never joined in, so no candidate. |
| 2 | Walking | no event, no alert | 24/24 pass | Peak speed 0.35-1.15, torso turn 3-13 deg, hip drop at most 0.20 tl (also while walking toward the camera and away). |
| 3 | Sitting | no event, no alert | 24/24 pass | Hip drop 0.94-0.98 tl in good light (threshold 1.2). Fast "plop" sits reached 2.53 tl/s with a 37 deg lean, but never a low/horizontal posture, so no candidate. Dim-light glitches briefly pushed hip drop to 1.42, too short to count. |
| 4 | Bending | no event, no alert | 16 pass, **8 warn**, 0 fail | Waist bends: torso turn up to 93 deg but slow and hips high, so nothing happened. A fast squat-and-lean pick-up (one seed, in all 8 conditions): 2.25 tl/s plus a 40-55 deg lean started a **possible-fall check shown for 1.9 s**. It was cancelled automatically, nothing was stored and there was no sound. |
| 5 | Slow lying down | no fall incident, no HIGH alert, no sound | 24/24 pass | Never a fall candidate (peak 0.94-2.03 tl/s, but the fall needs all three signals together). Watching started after 5 s. Good light: MEDIUM alert after about 60 s of stillness, no sound. **Dim light: watching only, no alert**, because jitter and glitches kept resetting the stillness timer (section 5). |
| 6 | Quick fall + immediate recovery | no alert, possible-fall may appear | 24/24 pass | Every run: possible fall, then recovery window, then normal once upright for 1.5 s. Nothing stayed open, no sound. |
| 7 | Fall + remain still | FALL alert, HIGH, sound, within recovery window + 5 s | 72/72 pass | Peak speed 2.73-6.31 tl/s (2.73 = slowest, a 1.2 s staged fall); torso turn 90-99 deg. Alert 9.8-10.6 s after landing, sound on the first alert frame, then every 30 s while unanswered. |

Stress run (10 fps, jitter 0.012): scenarios 1-6 still passed (some warnings). Scenario 7
failed in the far condition: alerts came 30 s after landing (section 4).

## 4. Adjustment made (one parameter)

### `fall_still_motion_threshold`: 0.08 -> 0.10 torso lengths

**Problem observed.** At the end of the recovery window the detector asks whether the
person is still down and still. "Still" means mean movement at or below this threshold.
But a perfectly still person is not zero-motion to a webcam: landmark jitter shows up as
movement, and more so when the person is far away (smaller in the image) or the light is
poor. Measured motion of a lying, perfectly still figure:

| Jitter | Near (torso 0.22) | Far (torso 0.14) |
|---|---|---|
| good light, 0.003 | 0.019 | 0.029 |
| dim light, 0.008 | 0.051 | **0.079** |
| very dim, 0.012 | 0.077 | 0.122 |
| *moving on the floor (struggling), any light* | *0.13 or more (10th percentile)* | *0.14 or more* |

In dim light, far from the camera, a still person measured 0.079-0.082: right on the 0.08
threshold. The escalation became a coin flip. Alerts came 10-14.7 s after landing instead
of about 10 s, and with slightly worse jitter they waited for the forced escalation at 30 s.

**Change.** 0.10 sits above the dim-light floor (0.08) and below the movement of a person
trying to get up (0.13 or more).

**Effect (simulated, same runs).**

| | Before (0.08) | After (0.10) |
|---|---|---|
| Fall + remain still, alert after landing | 9.8-13.2 s (3 seeds); up to 14.7 s (10 seeds, far + dim) | 9.8-10.6 s (3 seeds); up to 12.3 s (10 seeds, far + dim) |
| Other scenarios | all pass | unchanged, all pass |
| Unit/integration tests (389) | pass | pass, including "fall then struggle": a person moving on the floor still gets the extra time |

**Cost.** A person on the floor who moves only very little (0.08-0.10) now gets the alert
at the end of the recovery window instead of up to 20 s later. Getting up is still judged by
posture (upright for 1.5 s), not by this value.

**Not fixed by this.** Very dim light far from the camera (jitter 0.012, floor 0.12) still
gives 30 s alerts. Raising the value further would eat into the "trying to get up" margin.
The right fix there is more light or a closer camera, not a threshold.

## 5. Considered and deliberately not changed

| Value | Why it stays |
|---|---|
| `fall_velocity_threshold` 2.0 | Raising it to 2.3 removes the 8 bending warnings (2.25 tl/s) in simulation. But it cuts the margin to the slowest staged fall from 0.73 to 0.43 tl/s, and leaves only 0.05 above the squat, so a slightly faster squat would bring the warning back. A 1.9 s on-screen "checking" with no event and no sound is within the PRD rule ("no final alert"). A missed fall is not. |
| `torso_angle_change_deg` 35 | Torso turn alone overlaps (sitting up to 37 deg, bending up to 93), so it only works together with speed and posture. Every scenario passes. No evidence for a change. |
| `low_posture_hip_drop` 1.2 | Chairs 0.94-0.98 tl in good light; lying or falls 1.66 or more. Margin of 0.22 on the chair side. **Watch on real recordings:** a low sofa may come close to 1.2. |
| `torso_horizontal_deg` 60 | Lying is about 90 deg (falls turned the torso 90-99 deg). Bending passes through 60 but with the hips high, so it is not lying. No evidence for a change. |
| `recovery_window_seconds` 10 | A good length for a demo. Alerts come about 10 s after landing. Shorter makes slow get-ups alert. |
| `immobility_alert_seconds` 60 | Matches the PRD (lying intentionally may raise a lower-severity condition). Good light gives a MEDIUM alert at about 60 s. |
| `immobility_motion_threshold` 0.06 | **Observed limitation:** in dim light the stillness timer for lying never completes (floor 0.05-0.08 plus glitches), so slow lying only ever shows "watching". No scenario rule fails because of this. Raising it would make a resting person who still moves a little count as "not moving". Decide on real recordings (section 6). |
| `alert_score_threshold` 0.6 | Falls reached 0.90-1.00. Quick recoveries peaked at 0.67-0.74, but the threshold is only checked at the end of the recovery window, after they had already recovered. Bending at most 0.46. No evidence for a change. |
| `decision_history_seconds` 3.0 | Long enough to ride out lost frames and glitches; every escalation fired as expected. |

## 6. Real webcam recordings (needed before trusting any of this)

**Safety first.** Do falls only onto a thick mattress or gym mat, with a second person
present. Never fall onto a hard floor. Bend the knees and go down in a controlled way. The
system is meant to be judged on staged movements, not on real falls.

Setup: the laptop on a desk, with the person 2.5-4 m away and the whole body (feet included)
in the picture, including when lying on the mat.

```bash
python -m moeen.app --record data/recordings/standing_01.jsonl     --label standing       # 20 s
python -m moeen.app --record data/recordings/walking_01.jsonl      --label walking        # across + toward camera
python -m moeen.app --record data/recordings/sitting_01.jsonl      --label sitting        # sit 15 s, stand
python -m moeen.app --record data/recordings/bending_01.jsonl      --label bending        # pick up a pen, twice
python -m moeen.app --record data/recordings/slow_lying_01.jsonl   --label slow_lying     # lie down, stay 75 s
python -m moeen.app --record data/recordings/fall_recover_01.jsonl --label fall_recover   # onto the mat, up within 3 s
python -m moeen.app --record data/recordings/fall_still_01.jsonl   --label fall_still     # onto the mat, still 30 s
python scripts/calibrate.py data/recordings/*.jsonl
```
Press `d` while recording to watch the evidence lines. Recordings store landmarks only, no
video.

**Decision rules for real data.** These were set before seeing any results, so the tuning
stays minimal.

1. `fall_still` fails with "no fall alert" and its peak speed is below the threshold: set
   `fall_velocity_threshold` to 0.8 x the lowest real fall peak. This is allowed only if it
   stays above the highest real peak from standing, walking and sitting; otherwise report
   the overlap instead of tuning.
2. Sitting or bending fails because the posture turned LOW: set `low_posture_hip_drop`
   halfway between the highest real sitting hip drop and the lowest real lying hip drop.
3. While lying perfectly still, the overlay "stillness" value is above
   `immobility_motion_threshold` (or near `fall_still_motion_threshold`): set that threshold
   to the observed still value + 0.02, as long as it stays below the value seen while moving
   on the floor.
4. Change one value at a time, re-run `calibrate.py` on all recordings, and keep the change
   only if nothing that passed now fails.

## 7. Known limitations (not tunable)

- Falls toward or away from the camera foreshorten the torso in a 2-D picture: the torso
  turn may look small, so the fall path may not trigger. The lying/immobility path is then
  the fallback (alert after 60 s still, or 30 s right after a fall candidate). For the demo,
  fall sideways across the camera's view.
- One person only. Furniture hiding the hips or legs weakens posture evidence.
- The simulated jitter is independent per frame. MediaPipe's real jitter is smoother but
  drifts. This is another reason the real recordings decide.

Generated reports: `simulated-before.md` (fall_still_motion_threshold 0.08),
`simulated-after.md` (0.10).
