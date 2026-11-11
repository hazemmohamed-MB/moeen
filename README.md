# Moeen - live webcam assistance detection with dashboard and sound alert (Phases 1-8)

Opens the laptop webcam, runs MediaPipe Pose (Tasks `PoseLandmarker`, VIDEO mode), measures
pose features (posture, torso angle, hip drop, vertical velocity, motion) and runs one
detection state machine for three conditions: **fall + failure to recover**, **sustained
lying / low posture**, and **sustained immobility**. The state is shown in the preview
window and on a local web dashboard, incidents are stored as events in a local SQLite
database, and a confirmed high-severity alert plays a local chime.

> Moeen is an academic prototype. It is not a medical device and makes no diagnosis.

## Requirements
- Python 3.11, 3.12 or 3.13 (64-bit)
- Windows 10/11 x64, Apple-Silicon macOS, or Linux x64
- Intel Macs: `mediapipe==1.0.1` has no Intel-Mac wheel. Use `mediapipe==0.10.21` there
  (it has the same Tasks API, but this project was not tested with it).

## Install (run from this folder)
Windows (PowerShell):
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python scripts/download_model.py
```
macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python scripts/download_model.py
```
If PowerShell blocks `Activate.ps1`, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Test without a camera
```bash
pytest -q                          # unit + smoke tests (no camera, no model needed)
python scripts/selftest.py         # real model load + inference on a blank frame
python scripts/selftest.py --image some_photo_of_a_person.jpg   # optional real-photo check
python scripts/sound_check.py      # play the alert chime once (checks your audio output)
```

## Run
```bash
python scripts/check_camera.py     # camera only: actual resolution + measured FPS
python -m moeen.app                # live pose preview
```
Then open **http://127.0.0.1:5000** in a browser on the same computer for the dashboard.
Quit with `q` or `Esc`, by closing the window, or with Ctrl+C in the terminal.
In the preview window: `a` = assistance recorded, `m` = mute / unmute the alert sound,
`d` = show / hide the calibration evidence overlay.

Useful flags: `--camera-index 1`, `--width 1280 --height 720`, `--model-variant lite`,
`--camera-backend any`, `--no-mirror`, `--max-seconds 30`, `--no-window`, `--port 5050`,
`--no-dashboard`, `--no-sound`, `--debug-overlay`, `--calibration PATH`, `--no-calibration`.
Defaults live in `config/default.yaml`; the camera-dependent detection thresholds live in
`config/calibration.yaml`.

## Features (Phase 2)
The preview shows, per frame:

| Shown | Meaning |
|---|---|
| `Posture` | UPRIGHT / TILTED (bending) / LOW (e.g. sitting on the floor) / HORIZONTAL (lying) / UNKNOWN |
| `torso` | angle of the shoulder-to-hip line from vertical (0 = upright, 90 = horizontal) |
| `hip drop` | how far the hips are below your standing height, in torso lengths (chair ~0.9, floor ~1.6) |
| `hip v` | vertical hip velocity in torso lengths per second (+ = downward) |
| `motion` | how much the body moved in the last second (RMS keypoint displacement, torso lengths) |
| `scale` | `reference` once Moeen has seen you standing upright; before that `current`/`default` |

Stand upright in view for ~1 second first so the standing-height reference is learned.

### Record real movements and inspect the features
```bash
python -m moeen.app --record data/recordings/sit_01.jsonl --label "sit on chair"
python scripts/replay_features.py data/recordings/sit_01.jsonl
python scripts/replay_features.py data/recordings/sit_01.jsonl --csv data/sit_01.csv
```
Recordings contain only landmark coordinates (no video). Suggested takes: stand still,
walk, sit on a chair, bend to pick something up, lie down on a mat and get up, and - only
with a mattress and someone present - a controlled fall onto the mattress.

## Fall state machine (Phase 3)
Fall path:

| State | Entered when | Leaves when |
|---|---|---|
| NORMAL | start / incident closed | fast downward motion (>= 2.0 torso lengths/s for >= 0.1 s) **and** a posture change (torso rise >= 35 deg or low posture) |
| POSSIBLE_FALL | candidate found | all evidence within 2 s (velocity + torso rise >= 35 deg + low/horizontal held 0.3 s) -> RECOVERY_WINDOW; otherwise -> NORMAL |
| RECOVERY_WINDOW | fall confirmed | UPRIGHT held 1.5 s -> NORMAL (cancelled). After 10 s: low/horizontal >= 70% of last 3 s and low motion -> ALERT. Still down but moving: ALERT after 20 s more |
| ALERT | no recovery | UPRIGHT held 3 s, or `a` key (later: dashboard button) -> RESOLVED |
| RESOLVED | incident closed | after 3 s -> NORMAL |

All values are in `config/default.yaml` (`fall_detection`). The window shows the state,
the system score (rule-based, **not** a medical probability) and the active timer; the
border turns amber/orange while monitoring and red on ALERT. Press `a` to acknowledge.

Check the state machine on your own recordings and tune it there:
```bash
python scripts/replay_detection.py data/recordings/*.jsonl
python scripts/replay_detection.py data/recordings/fall_01.jsonl --csv data/fall_01_states.csv
```
## Lying, low posture and immobility (Phase 4)
Same state machine, with a `MONITORING` state: `NORMAL -> MONITORING -> ALERT -> RESOLVED`.

| Situation | Result (defaults, `immobility` section) |
|---|---|
| Sitting on a chair, bending | never treated as lying (posture UPRIGHT / TILTED) |
| Upright and not moving for 300 s | MONITORING, condition IMMOBILITY, risk LOW - **never** an alert |
| Low/horizontal for 5 s (e.g. sitting on the floor, lying down) | MONITORING, condition LYING, risk LOW |
| Lying (horizontal) **and** not moving for 60 s | ALERT, IMMOBILITY, MEDIUM |
| Low posture **and** not moving for 120 s | ALERT, IMMOBILITY, MEDIUM |
| Lying for 300 s even while moving | ALERT, LYING, MEDIUM |
| Any of the above starting within 60 s of a fall candidate | durations x 0.5 and severity HIGH |
| Stands up (1.5 s) / not low for 5 s / movement resumes | back to NORMAL |

Brief lying, brief stillness and single-frame glitches never alert: every duration is a
*sustained* timer that tolerates only short blips (`posture_tolerance_seconds`,
`still_tolerance_seconds`). After an alert is resolved (e.g. `a` = assistance recorded) the
lying/immobility checks pause until the person has been seen upright, so a person who is
being helped on the floor does not trigger repeated alerts.

## Event history (Phase 5)
Incidents are stored in `data/moeen.db` (created automatically on first run; change with
`database.path` or `--db-path`, disable with `--no-db`).

| Detector | Stored event |
|---|---|
| fall confirmed (RECOVERY_WINDOW) or MONITORING starts | new event, status `MONITORING` |
| ALERT | status `NEW`; type/severity/score updated (e.g. LYING -> IMMOBILITY) |
| recovered before an alert | `RESOLVED`, resolution `RECOVERED` |
| `a` key / dashboard button | `ASSISTANCE_RECORDED` |
| recovered after the alert | `RESOLVED`, resolution `RECOVERED_AFTER_ALERT` |
| app stops | monitoring-only events -> `RESOLVED` (`MONITORING_STOPPED`); unanswered alerts stay `NEW` |
| possible fall not confirmed | nothing stored |

Fields: `id, event_type (FALL/LYING/IMMOBILITY), created_at, updated_at, resolved_at,
severity, score, duration_seconds, status, resolution, session_id, incident_id,
details_json`, plus a `event_status_log` table with every status change. Timestamps are
UTC ISO-8601 with milliseconds (e.g. `2026-10-04T06:58:12.345Z`); tools show local time.

```bash
python scripts/events.py                 # latest events
python scripts/events.py --open          # open events only
python scripts/events.py show 3          # details + status history
python scripts/events.py assist 3 --note "helped up"
python scripts/events.py resolve 3 --note "demo"
```

## Dashboard (Phase 6)
```bash
python -m moeen.app                       # camera + detection + dashboard at http://127.0.0.1:5000
python -m moeen.app --port 5050           # if port 5000 is taken (macOS AirPlay often uses it)
python -m moeen.app --no-dashboard        # window only
python -m moeen.api                       # dashboard only, no camera: browse/act on stored events
python -m moeen.api --db data/moeen.db --port 5050
```
How it fits together:

```
webcam -> Python loop (pose -> features -> detector -> event recorder) -> StatusStore
                 ^  applies queued actions                                 |  latest status
                 |  (the only thread that changes the detector)           v  + JPEG preview
                 +---------------- Flask (background thread) <---- browser polls the API
```
- The Python process owns the webcam. The browser never opens the camera; the picture on the
  dashboard is the annotated frame Python already processed (`/video_feed`, ~8 fps, JPEG).
- The page polls `/api/status` every second and `/api/events` every 3 s
  (`dashboard.status_poll_ms`, `dashboard.events_poll_ms`).
- **Assistance recorded** / **Resolve** on the live incident are queued for the processing
  loop, which acknowledges the detector (ALERT -> RESOLVED) and stores the result; on an older
  event they update the database directly. Resolve asks for a second click.
- If the loop stops updating for 3 s the dashboard says "No recent update"; when only
  `moeen.api` runs it says "Camera processing is not running".
- The server listens on `127.0.0.1` (this computer only). It has no login, so don't use
  `--host 0.0.0.0` except for a supervised demo on a trusted network.

API (JSON):

| Method + path | Returns / does |
|---|---|
| `GET /api/health` | `{ok, version, pipeline_running, database}` |
| `GET /api/status` | `{pipeline_running, stale, age_s, snapshot, last_event}`; snapshot = state, condition, risk_level, score, score_components, timers, incident (duration, started_at, severity), live event, posture, fps |
| `GET /api/events?limit=20&offset=0&status=NEW&type=FALL&open=1` | `{events, total, open}` |
| `GET /api/events/<id>` | `{event, history}` (status changes) |
| `POST /api/events/<id>/assistance` | body `{"note": "..."}` (optional, max 500 chars); `{event, applied_to_live_incident}` |
| `POST /api/events/<id>/resolve` | same; resolution `RESOLVED_BY_USER` |
| `GET /api/config` | detection thresholds + dashboard settings (read-only) |
| `GET /video_feed`, `GET /api/preview.jpg` | live annotated picture (MJPEG) / latest frame |

POST requests need `Content-Type: application/json` (415 otherwise). Errors are JSON
`{"error": "..."}`: 400 bad input, 404 unknown event, 409 not allowed in the current status
(e.g. resolving twice), 503 database disabled or the camera loop did not answer in time.

Shutdown: `q`/`Esc`/window close, Ctrl+C or `kill <pid>` (SIGTERM) all take the same path:
pending dashboard actions are answered with an error, open video streams end, the web server
thread is stopped and joined, monitoring-only events are closed, then the camera and model
are released.

## Live alerting and sound (Phase 7)
One process runs the whole chain; everything after pose estimation is one camera-independent
`ProcessingPipeline` (`moeen/runtime/pipeline.py`), which is what the integration test drives:

```
webcam -> MediaPipe pose -> features -> ProcessingPipeline:
            detector -> EventRecorder (SQLite) -> dashboard actions -> AlertManager (sound)
            -> status for the dashboard; the preview window draws the same result
```

**On screen** (preview window and the dashboard picture): coloured border per state, a red
strip at the top for ALERT (never covering a person on the floor), the state/score/timer
lines, and an event + sound line, e.g.
`Event #3 NEW (unanswered) | sound: on (afplay), played 1x | a = assistance, m = mute`.

**When the sound plays** (`sound` in `config/default.yaml`):
- only for a confirmed alert (state ALERT) with severity >= `min_severity` (HIGH: a fall
  without recovery, or lying/stillness right after a fall candidate). MEDIUM alerts (e.g.
  lying down slowly and staying) are visual only unless you set `min_severity: MEDIUM`;
- once on the first frame of the alert - not every frame - then every `repeat_seconds` (30)
  while the alert stays unanswered, at most `max_plays_per_alert` (5) times;
- never two sounds within `cooldown_seconds` (10), also across incidents; a sound that is
  due during the cooldown waits, it is not lost;
- it stops as soon as the alert is answered (dashboard button or `a`) or the person recovers.

**Players:** Windows `winsound`, macOS `afplay`, Linux `paplay` / `pw-play` / `aplay`, then the
terminal bell. No extra package is needed; the chime is generated as a WAV at startup.
Playback runs on its own thread. If there is no audio device, the player fails, or it hangs
(`play_timeout_seconds`), the error is logged once, the next player is tried, and detection
carries on at full speed. With nothing working, alerts stay visual (window + dashboard).

**Event lifecycle** (unchanged from Phase 5, now with the sound tied to it):

| Status | Meaning | Sound |
|---|---|---|
| `MONITORING` | a possible problem is being watched (recovery window, lying/stillness timer) | no |
| `NEW` | confirmed alert, nobody has answered yet | yes, if severity >= `min_severity` |
| `ASSISTANCE_RECORDED` | someone pressed "Assistance recorded" (or `a`) | stops |
| `RESOLVED` | the person recovered, or "Resolve" was pressed | stops |

`MONITORING` comes before `NEW` on purpose: `NEW` always means "an alert is waiting for a
person", which is exactly when the chime plays. Events that clear on their own go
`MONITORING -> RESOLVED` and never alarm. All four statuses are the PRD's.

**Log lines** to expect during a demo:
```
detector: NORMAL -> POSSIBLE_FALL at 2.37 s: fast downward motion ...
detector: POSSIBLE_FALL -> RECOVERY_WINDOW at 2.70 s: fall confirmed ...
event_recorder: Event #1 FALL: status MONITORING
detector: RECOVERY_WINDOW -> ALERT at 12.70 s: no recovery after 10.0 s ...
event_recorder: Event #1 FALL: status NEW
alert_manager: ALERT raised: FALL, severity HIGH (sound on)
alert_manager: Alert sound: FALL alert (HIGH)
bridge: Dashboard: assistance recorded for event 1 (live incident)
event_recorder: Event #1 FALL: status ASSISTANCE_RECORDED
alert_manager: Alert ended: assistance recorded by a person
```

## Calibration (Phase 8)
The thresholds that depend on the camera setup are in **`config/calibration.yaml`**, under
plain names: `decision_history_seconds`, `fall_velocity_threshold`, `torso_angle_change_deg`,
`torso_horizontal_deg`, `low_posture_hip_drop`, `recovery_window_seconds`,
`immobility_alert_seconds`, `fall_still_motion_threshold`, `immobility_motion_threshold` and
`alert_score_threshold`. Each value exists only there; `config/default.yaml` points to it,
and loading fails if both files set the same value.

```bash
python scripts/calibrate.py --synthetic                          # 216 simulated runs, ~1 min
python scripts/calibrate.py --synthetic --set fall_velocity_threshold=2.3   # what-if, file unchanged
python scripts/calibrate.py data/recordings/*.jsonl              # your real recordings
python -m moeen.app --debug-overlay                              # or press d
```
`calibrate.py` judges each run against the scenario rules and writes a Markdown report to
`data/calibration/`. The rules: no event for standing, walking, sitting and bending; no fall
alert for slow lying; a quick fall that recovers is cancelled; fall + remain still gives a
HIGH alert with sound.

The **evidence overlay** (`d`) shows five lines under the status box, each measured value /
threshold, with `>` when that evidence currently points toward an alert: fall speed, torso
turn, posture (tilt and hip drop), stillness, and score with the history-window share.

The record of what was run, observed and changed is in
[`docs/calibration/CALIBRATION.md`](docs/calibration/CALIBRATION.md). In short, under
simulated laptop-webcam conditions every scenario rule held with the starting values. One
value changed: `fall_still_motion_threshold` went from 0.08 to 0.10, because a still person's
jitter in dim light from far away measured right at 0.08. The same document has the
protocol for recording the seven scenarios safely (falls only onto a mattress) and the
decision rules for tuning on real recordings. Simulated runs are not evidence about real
people; the real recordings are.

## Exit codes
| Code | Meaning |
|---|---|
| 0 | normal exit (q / Esc / window closed / Ctrl+C / SIGTERM / limit reached) |
| 2 | camera could not be opened or stopped delivering frames |
| 3 | pose model missing/invalid, or MediaPipe API mismatch |
| 4 | invalid configuration |
| 5 | OpenCV cannot open a window (headless OpenCV installed) |
| 6 | event database cannot be opened (corrupt file, newer schema, no permission) |
| 7 | dashboard cannot start (port in use) - try `--port 5050` or `--no-dashboard` |

## Troubleshooting
- **Camera won't open** - close Zoom/Teams/browser tabs using it; try `--camera-index 1`;
  try `--camera-backend any` (Windows: also `msmf`). `python scripts/check_camera.py --probe`
  lists working indices.
- **macOS: camera opens but frames are black / permission error** - System Settings >
  Privacy & Security > Camera > enable your terminal app (Terminal, iTerm, VS Code), then restart it.
- **Windows: camera blocked** - Settings > Privacy & security > Camera > allow desktop apps.
- **`AttributeError: module 'mediapipe' has no attribute 'solutions'`** - expected: MediaPipe
  0.10.30+ removed that legacy API. Moeen uses the Tasks API; don't copy old tutorials.
- **Window does not open / "headless"** - several OpenCV packages are installed. Fix:
  `pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python` then
  `pip install -r requirements.txt`.
- **Low FPS** - use `--model-variant lite` and keep 640x480.
- **Dashboard: "port is in use"** - another program (on macOS often AirPlay Receiver) uses
  port 5000. Run with `--port 5050` and open http://127.0.0.1:5050.
- **Dashboard shows "No recent update"** - the camera loop is stalled or stopped; check the
  terminal running `python -m moeen.app`.
- **No alert sound** - run `python scripts/sound_check.py`; it lists the players it tries
  and says which worked. Check the system volume and output device. Linux: install
  `pulseaudio-utils` (paplay) or `alsa-utils` (aplay). Force one with `--backend`, or set
  `sound.backend` in the config. Moeen keeps working without sound.
- **Too many / too few beeps** - tune `sound.repeat_seconds`, `max_plays_per_alert`,
  `cooldown_seconds`, `min_severity`; mute live with `m`; disable with `--no-sound`.
- **Model download fails** - download the URL printed by the script in a browser and save it
  into `models/` with the printed file name.
