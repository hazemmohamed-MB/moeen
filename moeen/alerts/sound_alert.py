"""Local alert sound - generated chime, platform audio players, never blocks or crashes.

The detection loop only ever calls :meth:`SoundPlayer.play`, which puts a request on a
one-slot queue and returns immediately. A background worker thread plays the chime with the
first player that works on this computer:

    Windows   winsound (standard library)
    macOS     afplay (built in)
    Linux     paplay (PulseAudio/PipeWire), pw-play (PipeWire), aplay (ALSA)
    fallback  terminal bell (``\\a``) - audible on most terminals, harmless otherwise

Every failure (no audio device, missing player, a player that hangs) is caught in the
worker, logged once, and the next player is tried. A player that fails ``max_failures``
times in a row is dropped. No third-party audio package is needed.
"""

from __future__ import annotations

import array
import logging
import math
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from moeen.config import SoundConfig

log = logging.getLogger(__name__)

SAMPLE_RATE = 22050


class SoundError(RuntimeError):
    """A player could not play the sound."""


# ---------------------------------------------------------------------- the chime
def chime_samples(tone_hz: float, volume: float, sample_rate: int = SAMPLE_RATE) -> array.array:
    """A clear, not harsh, alert chime: three two-note pulses (~1.2 s), 16-bit mono.

    Each note has a short attack and an exponential decay, so there are no clicks.
    """
    notes = [(tone_hz, 0.16), (tone_hz * 0.75, 0.22), (None, 0.12)] * 3
    peak = int(32767 * max(0.0, min(1.0, volume)))
    out = array.array("h")
    for freq, seconds in notes:
        n = int(seconds * sample_rate)
        if freq is None:
            out.extend([0] * n)
            continue
        attack = max(1, int(0.008 * sample_rate))
        for i in range(n):
            env = min(1.0, i / attack) * math.exp(-4.0 * i / n)
            # a little second harmonic makes small laptop speakers sound less thin
            s = math.sin(2 * math.pi * freq * i / sample_rate)
            s += 0.25 * math.sin(4 * math.pi * freq * i / sample_rate)
            out.append(int(peak * env * s / 1.25))
    return out


def write_chime_wav(path: Path, tone_hz: float, volume: float) -> Path:
    samples = chime_samples(tone_hz, volume)
    if sys.byteorder == "big":
        samples.byteswap()          # WAV is little-endian
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
    return path


# ---------------------------------------------------------------------- players
class SoundBackend(Protocol):
    name: str

    def play(self, wav_path: Path, timeout: float) -> None:
        """Play the file to the end; raise on failure."""


class CommandBackend:
    """An external player program (afplay, paplay, pw-play, aplay)."""

    def __init__(self, name: str, executable: str, args: tuple[str, ...] = ()) -> None:
        self.name = name
        self.executable = executable
        self.args = args

    def play(self, wav_path: Path, timeout: float) -> None:
        try:
            proc = subprocess.run([self.executable, *self.args, str(wav_path)],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise SoundError(f"{self.name} did not finish within {timeout:.0f} s") from exc
        except OSError as exc:
            raise SoundError(f"{self.name} could not be started: {exc}") from exc
        if proc.returncode != 0:
            msg = proc.stderr.decode(errors="replace").strip().splitlines()
            raise SoundError(f"{self.name} exited with code {proc.returncode}"
                             + (f": {msg[-1]}" if msg else ""))


class WinsoundBackend:
    name = "winsound"

    def play(self, wav_path: Path, timeout: float) -> None:  # noqa: ARG002 - plays synchronously
        import winsound  # Windows only
        try:
            winsound.PlaySound(str(wav_path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except RuntimeError as exc:      # e.g. no audio output device
            raise SoundError(f"winsound: {exc}") from exc


class BellBackend:
    """Terminal bell: the last resort when no audio player works."""

    name = "bell"

    def __init__(self, stream=None) -> None:
        self._stream = stream

    def play(self, wav_path: Path, timeout: float) -> None:  # noqa: ARG002
        stream = self._stream or sys.stderr
        if stream is None:
            raise SoundError("no terminal for the bell")
        try:
            stream.write("\a")
            stream.flush()
        except (OSError, ValueError) as exc:
            raise SoundError(f"terminal bell failed: {exc}") from exc


def choose_backends(preference: str, platform: str = sys.platform,
                    which: Callable[[str], str | None] = shutil.which) -> list[SoundBackend]:
    """Players to try, best first. ``preference`` is ``sound.backend`` from the config."""
    if preference == "none":
        return []
    if preference == "bell":
        return [BellBackend()]
    if preference == "winsound":
        return [WinsoundBackend()]
    commands = {"afplay": (), "paplay": (), "pw-play": (), "aplay": ("-q",)}
    if preference in commands:
        exe = which(preference)
        return [CommandBackend(preference, exe, commands[preference])] if exe else []
    # auto
    found: list[SoundBackend] = []
    if platform.startswith("win"):
        found.append(WinsoundBackend())
    elif platform == "darwin":
        candidates = ["afplay"]
    else:
        candidates = ["paplay", "pw-play", "aplay"]
    if not platform.startswith("win"):
        for name in candidates:
            exe = which(name)
            if exe:
                found.append(CommandBackend(name, exe, commands[name]))
    found.append(BellBackend())
    return found


# ---------------------------------------------------------------------- the player
@dataclass
class SoundStatus:
    enabled: bool
    available: bool
    muted: bool
    backend: str | None
    plays: int
    last_error: str | None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class SoundPlayer:
    """Plays the alert chime on a background thread. All methods are safe to call from the
    detection loop; none of them raise and none of them block for long."""

    def __init__(self, config: SoundConfig, backends: list[SoundBackend] | None = None) -> None:
        self.config = config
        self._backends: list[SoundBackend] = (list(backends) if backends is not None
                                              else choose_backends(config.backend))
        self._failures: dict[str, int] = {}
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self._wav: Path | None = None
        self.muted = False
        self.plays = 0
        self.dropped = 0
        self.last_backend: str | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> "SoundPlayer":
        if not self.config.enabled or not self._backends:
            log.info("Alert sound: off (%s)", "disabled in config" if not self.config.enabled
                     else "no audio player available")
            return self
        try:
            self._tmpdir = tempfile.TemporaryDirectory(prefix="moeen-sound-")
            self._wav = write_chime_wav(Path(self._tmpdir.name) / "alert.wav",
                                        self.config.tone_hz, self.config.volume)
        except Exception as exc:  # noqa: BLE001 - sound is optional
            self._set_error(f"could not create the alert sound: {exc}")
            log.warning("Alert sound: off (%s)", self.last_error)
            self._backends = []
            return self
        self._thread = threading.Thread(target=self._run, name="moeen-sound", daemon=True)
        self._thread.start()
        log.info("Alert sound: ready (player: %s)",
                 " -> ".join(b.name for b in self._backends))
        return self

    def close(self, timeout: float = 2.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._drain()
            try:
                self._queue.put(None, timeout=timeout)
            except queue.Full:
                pass
            self._thread.join(timeout)
        if self._tmpdir is not None:
            try:
                self._tmpdir.cleanup()
            except OSError:
                pass
            self._tmpdir = None

    # ------------------------------------------------------------------ loop-side API
    @property
    def available(self) -> bool:
        with self._lock:
            return bool(self._backends) and self._thread is not None and self._thread.is_alive()

    def play(self, reason: str = "") -> bool:
        """Request one chime. Returns True if queued (False if off, muted or already playing)."""
        try:
            if self.muted or not self.available:
                return False
            self._queue.put_nowait(reason)
            return True
        except queue.Full:
            self.dropped += 1          # one chime is already queued/playing: that is enough
            return False
        except Exception as exc:  # noqa: BLE001 - never disturb the detection loop
            log.warning("Alert sound request failed: %s", exc)
            return False

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        log.info("Alert sound %s", "muted" if self.muted else "unmuted")
        return self.muted

    def status(self) -> SoundStatus:
        with self._lock:
            backend = self.last_backend or (self._backends[0].name if self._backends else None)
            return SoundStatus(enabled=self.config.enabled, available=bool(self._backends),
                               muted=self.muted, backend=backend, plays=self.plays,
                               last_error=self.last_error)

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Block until queued sounds have been played (for tests and scripts)."""
        done = threading.Event()

        def check():
            self._queue.join()
            done.set()
        threading.Thread(target=check, daemon=True).start()
        return done.wait(timeout)

    # ------------------------------------------------------------------ worker
    def _run(self) -> None:
        while True:
            reason = self._queue.get()
            try:
                if reason is None:
                    return
                self._play_once()
            except Exception as exc:  # noqa: BLE001 - the worker must survive anything
                self._set_error(f"unexpected sound error: {exc}")
                log.warning("Alert sound: %s", self.last_error)
            finally:
                self._queue.task_done()

    def _play_once(self) -> None:
        for backend in list(self._backends):
            try:
                backend.play(self._wav, self.config.play_timeout_seconds)
            except Exception as exc:  # noqa: BLE001 - try the next player
                self._record_failure(backend, exc)
                continue
            with self._lock:
                self._failures[backend.name] = 0
                self.plays += 1
                self.last_backend = backend.name
            return
        if not self._backends:
            log.warning("Alert sound: no working audio output - alerts stay visual only")

    def _record_failure(self, backend: SoundBackend, exc: Exception) -> None:
        with self._lock:
            n = self._failures.get(backend.name, 0) + 1
            self._failures[backend.name] = n
            self.last_error = f"{backend.name}: {exc}"
            give_up = n >= self.config.max_failures
            if give_up and backend in self._backends:
                self._backends.remove(backend)
            remaining = [b.name for b in self._backends]
        if n == 1 or give_up:
            log.warning("Alert sound: %s failed (%s)%s", backend.name, exc,
                        ("; no longer using it" + (f", using {remaining[0]}" if remaining else ""))
                        if give_up else "")

    def _set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                return
