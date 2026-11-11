"""Alert sound: when it plays (policy), and that a broken audio setup never hurts detection.

Players are fakes or small Python child processes - the tests never make a real sound.
"""

import dataclasses
import io
import sys
import time
import wave

import pytest

from feature_builders import HORIZONTAL, Timeline
from moeen.alerts import AlertManager, AlertSoundPolicy, SoundPlayer
from moeen.alerts.sound_alert import (BellBackend, CommandBackend, SoundError, choose_backends,
                                      write_chime_wav)
from moeen.config import load_config
from moeen.detection import AssistanceDetector, DetectionState

CFG = load_config()
SOUND = CFG.sound


def sound_cfg(**kw):
    return dataclasses.replace(SOUND, **kw)


def run(frames, policy, det=None):
    """Feed frames through a real detector; returns (detector, [(t_ms, request)])."""
    det = det or AssistanceDetector(CFG.fall_detection, CFG.immobility)
    fired = []
    for f in frames:
        req = policy.update(det.update(f))
        if req is not None:
            fired.append((f.timestamp_ms, req))
    return det, fired


def fall_then_down(seconds):
    return Timeline().hold(2.0).fall().hold(seconds, HORIZONTAL, motion=0.01)


# ---------------------------------------------------------------- policy
def test_high_severity_alert_plays_once_not_every_frame():
    policy = AlertSoundPolicy(sound_cfg(repeat_seconds=0))
    det, fired = run(fall_then_down(40.0), policy)
    assert det.state is DetectionState.ALERT and det.incident.severity.value == "HIGH"
    assert len(fired) == 1                                   # ~hundreds of ALERT frames, one sound
    alert_ms = det.incident.alert_ms
    assert fired[0][0] == alert_ms                           # on the first ALERT frame
    assert "FALL alert (HIGH)" in fired[0][1].reason


def test_no_sound_before_the_alert_is_confirmed():
    policy = AlertSoundPolicy(SOUND)
    det, fired = run(fall_then_down(5.0), policy)             # still in RECOVERY_WINDOW
    assert det.state is DetectionState.RECOVERY_WINDOW and fired == []


def test_medium_severity_alert_is_silent_by_default_but_configurable():
    # lying down slowly (no fall candidate) and staying still -> LYING/IMMOBILITY alert, MEDIUM
    tl = Timeline().hold(2.0).hold(400.0, HORIZONTAL, motion=0.005)
    det, fired = run(tl, AlertSoundPolicy(SOUND))
    assert det.state is DetectionState.ALERT and det.incident.severity.value == "MEDIUM"
    assert fired == []
    _, fired = run(tl, AlertSoundPolicy(sound_cfg(min_severity="MEDIUM", repeat_seconds=0)))
    assert len(fired) == 1


def test_repeats_while_unanswered_up_to_the_limit():
    policy = AlertSoundPolicy(sound_cfg(repeat_seconds=20, max_plays_per_alert=3,
                                        cooldown_seconds=5))
    det, fired = run(fall_then_down(120.0), policy)
    times = [t for t, _ in fired]
    assert len(fired) == 3
    assert all(b - a >= 20_000 for a, b in zip(times, times[1:]))
    assert [r.play_number for _, r in fired] == [1, 2, 3]
    assert "still unanswered" in fired[1][1].reason


def test_answering_the_alert_stops_the_sound():
    policy = AlertSoundPolicy(sound_cfg(repeat_seconds=10, max_plays_per_alert=10))
    det, fired = run(fall_then_down(30.0), policy)
    n = len(fired)
    acked = det.acknowledge()
    assert policy.update(acked) is None and acked.state is DetectionState.RESOLVED
    tl = Timeline(acked.timestamp_ms + 33).hold(60.0, HORIZONTAL, motion=0.01)
    _, more = run(tl, policy, det)
    assert more == [] and n >= 1


def test_cooldown_delays_a_second_incident_instead_of_dropping_it():
    cfg = sound_cfg(repeat_seconds=0, cooldown_seconds=1000)   # huge cooldown
    policy = AlertSoundPolicy(cfg)
    det, fired = run(fall_then_down(30.0), policy)
    assert len(fired) == 1
    # recover, then a second fall within the cooldown
    up = Timeline(det.last_output.timestamp_ms + 33).hold(5.0)
    tl2 = Timeline(up.t).hold(2.0).fall().hold(30.0, HORIZONTAL, motion=0.01)
    _, more = run(list(up) + list(tl2), policy, det)
    assert det.state is DetectionState.ALERT and det.incident.incident_id == 2
    assert more == [] and policy.suppressed > 0               # due, held back by the cooldown

    policy2 = AlertSoundPolicy(sound_cfg(repeat_seconds=0, cooldown_seconds=10))
    det2, f1 = run(fall_then_down(30.0), policy2)
    _, f2 = run(list(Timeline(det2.last_output.timestamp_ms + 33).hold(5.0))
                + list(Timeline(det2.last_output.timestamp_ms + 5033).hold(2.0).fall()
                       .hold(30.0, HORIZONTAL, motion=0.01)), policy2, det2)
    assert len(f1) == 1 and len(f2) == 1 and f2[0][1].incident_id == 2


# ---------------------------------------------------------------- manager
class FakePlayer:
    def __init__(self, ok=True, muted=False, available=True):
        self.ok, self.muted, self.available = ok, muted, available
        self.calls = []
        self.plays = 0

    def play(self, reason):
        self.calls.append(reason)
        return self.ok

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted


def test_manager_logs_alert_and_respects_mute(caplog):
    caplog.set_level("INFO")
    player = FakePlayer(muted=True)
    mgr = AlertManager(sound_cfg(repeat_seconds=0), player)
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    for f in fall_then_down(30.0):
        mgr.update(det.update(f))
    assert player.calls == [] and len(mgr.requests) == 1
    assert "ALERT raised: FALL, severity HIGH (sound on)" in caplog.text
    assert "muted" in caplog.text
    assert mgr.toggle_mute() is False


def test_manager_survives_a_broken_player(caplog):
    class Exploding(FakePlayer):
        def play(self, reason):
            raise RuntimeError("audio driver crashed")
    mgr = AlertManager(sound_cfg(repeat_seconds=0), Exploding())
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    outs = [mgr.update(det.update(f)) for f in fall_then_down(30.0)]   # must not raise
    assert det.state is DetectionState.ALERT
    assert "continuing without sound" in caplog.text and outs[-1] is None


def test_sound_disabled_never_requests():
    mgr = AlertManager(sound_cfg(enabled=False), FakePlayer())
    det = AssistanceDetector(CFG.fall_detection, CFG.immobility)
    for f in fall_then_down(30.0):
        mgr.update(det.update(f))
    assert mgr.requests == [] and mgr.player.calls == []


# ---------------------------------------------------------------- player
class FakeBackend:
    def __init__(self, name="fake", fail=None, delay=0.0):
        self.name, self.fail, self.delay = name, fail, delay
        self.played = 0

    def play(self, wav_path, timeout):
        time.sleep(self.delay)
        assert wav_path.exists()
        if self.fail:
            raise SoundError(self.fail)
        self.played += 1


def test_chime_is_a_valid_short_wav(tmp_path):
    path = write_chime_wav(tmp_path / "a.wav", 880.0, 0.6)
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth()) == (1, 2)
        assert 0.5 < w.getnframes() / w.getframerate() < 2.0


def test_player_plays_in_the_background_and_cleans_up():
    be = FakeBackend(delay=0.05)
    p = SoundPlayer(SOUND, backends=[be]).start()
    t0 = time.monotonic()
    assert p.play("test") is True
    assert time.monotonic() - t0 < 0.03                     # play() does not wait for the sound
    assert p.play("again") in (True, False)                  # one-slot queue: may be dropped
    assert p.wait_idle(2) and be.played >= 1 and p.plays == be.played
    tmp = p._tmpdir.name
    p.close()
    assert not p._thread.is_alive()
    import os
    assert not os.path.exists(tmp)


def test_no_audio_device_falls_back_then_gives_up_gracefully(caplog):
    caplog.set_level("INFO")
    broken = FakeBackend("aplay", fail="aplay: main:831: audio open error: no soundcards found")
    bell_out = io.StringIO()
    bell = BellBackend(stream=bell_out)
    p = SoundPlayer(sound_cfg(max_failures=2), backends=[broken, bell]).start()
    for _ in range(3):
        assert p.play("x")
        assert p.wait_idle(2)
    assert bell_out.getvalue() == "\a" * 3                   # still audible via the terminal bell
    assert p.status().backend == "bell" and "no soundcards" in p.status().last_error
    assert "aplay failed" in caplog.text and "no longer using it" in caplog.text
    p.close()


def test_player_with_nothing_working_reports_unavailable_and_never_raises(caplog):
    p = SoundPlayer(sound_cfg(max_failures=1), backends=[FakeBackend("x", fail="boom")]).start()
    assert p.play("a") and p.wait_idle(2)
    assert not p.available and p.play("b") is False
    assert "visual only" in caplog.text
    st = p.status()
    assert st.available is False and st.enabled is True
    p.close()


def test_player_with_no_backends_or_disabled_is_a_no_op():
    for p in (SoundPlayer(SOUND, backends=[]), SoundPlayer(sound_cfg(enabled=False),
                                                           backends=[FakeBackend()])):
        p.start()
        assert p.play("x") is False and p.status().available in (False, True)
        p.close()


def test_mute_blocks_playing():
    be = FakeBackend()
    p = SoundPlayer(SOUND, backends=[be]).start()
    p.toggle_mute()
    assert p.play("x") is False
    p.toggle_mute()
    assert p.play("x") and p.wait_idle(2) and be.played == 1
    p.close()


def test_command_backend_errors_become_sound_errors(tmp_path):
    wav = write_chime_wav(tmp_path / "a.wav", 880.0, 0.5)
    no_device = CommandBackend("aplay", sys.executable, (
        "-c", "import sys; sys.stderr.write('aplay: no soundcards found\\n'); sys.exit(1)"))
    with pytest.raises(SoundError, match="code 1: aplay: no soundcards found"):
        no_device.play(wav, 5)
    hangs = CommandBackend("hang", sys.executable, ("-c", "import time; time.sleep(10)"))
    t0 = time.monotonic()
    with pytest.raises(SoundError, match="did not finish"):
        hangs.play(wav, 0.5)
    assert time.monotonic() - t0 < 5
    with pytest.raises(SoundError, match="could not be started"):
        CommandBackend("missing", str(tmp_path / "no-such-player")).play(wav, 1)
    CommandBackend("ok", sys.executable, ("-c", "pass")).play(wav, 5)   # success: no error


def test_backend_choice_per_platform():
    choose = choose_backends   # imported at collection time: the real function, not the
                               # silent stand-in conftest installs for every test
    which = {"afplay": "/usr/bin/afplay", "aplay": "/usr/bin/aplay"}.get
    assert [b.name for b in choose("auto", "darwin", which)] == ["afplay", "bell"]
    assert [b.name for b in choose("auto", "linux", which)] == ["aplay", "bell"]
    assert [b.name for b in choose("auto", "linux", lambda n: None)] == ["bell"]
    assert [b.name for b in choose("auto", "win32", which)] == ["winsound", "bell"]
    assert choose("none", "linux", which) == []
    assert choose("paplay", "linux", which) == []                     # requested but missing


def test_player_thread_survives_unexpected_errors(caplog):
    class Weird:
        name = "weird"

        def play(self, wav, timeout):
            raise KeyError("unexpected")         # not a SoundError
    good = FakeBackend()
    p = SoundPlayer(sound_cfg(max_failures=5), backends=[Weird(), good]).start()
    assert p.play("x") and p.wait_idle(2)
    assert good.played == 1 and p._thread.is_alive()
    p.close()
