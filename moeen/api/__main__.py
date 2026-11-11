"""Run the dashboard and API on their own, without the camera (for testing and reviewing events).

    python -m moeen.api                     # uses database.path from config/default.yaml
    python -m moeen.api --db data/moeen.db --port 5050

The status panel shows "camera processing is not running"; event history and the
"Assistance recorded" / "Resolve" actions work directly on the database.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading

from moeen.api.server import DashboardError, DashboardServer, create_app
from moeen.config import ConfigError, load_config
from moeen.database import Database, DatabaseError, EventRepository
from moeen.runtime import StatusStore
from moeen.runtime.shutdown import sigterm_as_keyboard_interrupt


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m moeen.api", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config")
    p.add_argument("--db", help="database file (default: database.path from config)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    try:
        cfg = load_config(args.config).with_overrides(
            {"dashboard": {"host": args.host, "port": args.port}, "database": {"path": args.db}})
        repo = EventRepository(Database(cfg.database.path_resolved()))
        server = DashboardServer(create_app(cfg, StatusStore(), repo), cfg.dashboard.host,
                                 cfg.dashboard.port).start()
    except (ConfigError, DatabaseError, DashboardError) as exc:
        logging.error("%s", exc)
        return 2
    print(f"Dashboard (no camera): {server.url}   - press Ctrl+C to stop", flush=True)
    try:
        with sigterm_as_keyboard_interrupt():
            threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("Dashboard stopped.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
