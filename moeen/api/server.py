"""Flask app factory and a background server with clean start/stop."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from flask import Flask
from werkzeug.serving import make_server

from moeen.config import AppConfig
from moeen.database import EventRepository
from moeen.runtime import StatusStore

log = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


def create_app(config: AppConfig, store: StatusStore, repo: EventRepository | None) -> Flask:
    """Build the Flask app. ``repo`` may be None when the database is disabled."""
    from moeen.api.routes import bp

    app = Flask("moeen", template_folder=str(DASHBOARD_DIR / "templates"),
                static_folder=str(DASHBOARD_DIR / "static"), static_url_path="/static")
    app.config["MOEEN"] = {"config": config, "store": store, "repo": repo}
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False
    app.register_blueprint(bp)
    return app


class DashboardError(RuntimeError):
    """The web server could not start (e.g. the port is already in use)."""


class DashboardServer:
    """Runs a Flask app in a daemon thread; ``stop()`` shuts it down and joins the thread."""

    def __init__(self, app: Flask, host: str, port: int) -> None:
        try:
            self._server = make_server(host, port, app, threaded=True)
        except (OSError, SystemExit) as exc:
            # Werkzeug calls sys.exit(1) when the port is in use; never let that end the app.
            raise DashboardError(
                f"cannot start the dashboard on {host}:{port}: the port is in use or not "
                "available. Try another one, e.g. --port 5050.") from exc
        self._server.daemon_threads = True
        # The dashboard polls every second; per-request access lines would bury the app's own log.
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        self.host = host
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, name="moeen-dashboard",
                                        daemon=True)

    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return f"http://{host}:{self.port}"

    def start(self) -> "DashboardServer":
        self._thread.start()
        log.debug("Dashboard running at %s", self.url)
        if self.host not in ("127.0.0.1", "localhost", "::1"):
            log.warning("The dashboard is reachable from other devices on this network (host %s) "
                        "and has no login. Use 127.0.0.1 unless you need this for a demo.",
                        self.host)
        return self

    def stop(self, timeout: float = 3.0) -> None:
        if self._thread.is_alive():
            self._server.shutdown()
            self._thread.join(timeout)
        self._server.server_close()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()
