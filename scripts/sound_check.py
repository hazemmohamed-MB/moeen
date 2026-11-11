"""Play the alert chime once, so you know what an alert sounds like on this computer.

Usage (from the project root):
    python scripts/sound_check.py                  # uses sound.backend from the config (auto)
    python scripts/sound_check.py --backend bell   # try a specific player
    python scripts/sound_check.py --save chime.wav # also write the chime to a file

Exit code 0 = a player reported success (you should have heard it), 1 = no player worked
(Moeen will still run; alerts stay visual), 4 = invalid configuration.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moeen.alerts.sound_alert import SoundPlayer, choose_backends, write_chime_wav  # noqa: E402
from moeen.config import SOUND_BACKENDS, ConfigError, load_config  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config")
    p.add_argument("--backend", choices=SOUND_BACKENDS)
    p.add_argument("--save", metavar="PATH", help="also save the chime as a .wav file")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    try:
        cfg = load_config(args.config).with_overrides({"sound": {"backend": args.backend,
                                                                 "enabled": True}})
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 4
    if args.save:
        print(f"Saved the chime to {write_chime_wav(Path(args.save), cfg.sound.tone_hz, cfg.sound.volume)}")
    backends = choose_backends(cfg.sound.backend)
    print("Players to try, in order:", ", ".join(b.name for b in backends) or "none")
    player = SoundPlayer(cfg.sound, backends=backends).start()
    try:
        if not player.play("sound check"):
            print("No audio player is available. Moeen will run with visual alerts only.")
            return 1
        player.wait_idle(cfg.sound.play_timeout_seconds * max(1, len(backends)) + 2)
        st = player.status()
    finally:
        player.close()
    if st.plays:
        print(f"Played with: {st.backend}" + (" (terminal bell: a short beep or a flash, depending "
                                               "on your terminal)" if st.backend == "bell" else ""))
        return 0
    print(f"No player worked ({st.last_error}). Moeen will run with visual alerts only.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
