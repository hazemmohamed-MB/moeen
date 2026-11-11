"""Shared test safeguards."""

from pathlib import Path

import pytest

PROJECT_DB = Path(__file__).resolve().parent.parent / "data" / "moeen.db"


@pytest.fixture(autouse=True)
def never_touch_project_database():
    """Fail any test that creates or modifies the real project database (data/moeen.db).
    Tests must use temporary databases."""
    before = PROJECT_DB.stat().st_mtime_ns if PROJECT_DB.exists() else None
    yield
    after = PROJECT_DB.stat().st_mtime_ns if PROJECT_DB.exists() else None
    assert after == before, f"a test wrote to the project database {PROJECT_DB}"


@pytest.fixture(autouse=True)
def never_bind_the_real_dashboard_port(monkeypatch):
    """Tests must start dashboards on port 0 (any free port) or not at all, so they never
    clash with a running Moeen on the configured port (5000)."""
    import moeen.api.server as server
    from moeen.config import load_config

    real_init = server.DashboardServer.__init__
    real_port = load_config().dashboard.port

    def guarded(self, app, host, port):
        assert port != real_port, f"a test tried to start the dashboard on port {port}; use --port 0"
        real_init(self, app, host, port)
    monkeypatch.setattr(server.DashboardServer, "__init__", guarded)


@pytest.fixture(autouse=True)
def never_play_real_sounds(monkeypatch):
    """Running the tests must not beep on the developer's laptop: the automatic player choice
    finds nothing. Tests that need a player pass fake backends explicitly."""
    import moeen.alerts.sound_alert as sound_alert
    monkeypatch.setattr(sound_alert, "choose_backends", lambda *a, **k: [])
