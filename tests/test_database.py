"""SQLite event persistence: initialization, create/list/update/resolve, reopen, safety."""

import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from moeen.database import (SCHEMA_VERSION, Database, DatabaseError, EventNotFound, EventRepository,
                            EventStatus, EventType, InvalidStatusTransition, Severity)
from moeen.database.timestamps import format_ts, parse_ts, to_local_display

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
T0 = datetime(2026, 10, 4, 6, 0, 0, tzinfo=timezone.utc)


class StepClock:
    """Deterministic clock: each call returns one second later."""

    def __init__(self, start=T0):
        self.t = start - timedelta(seconds=1)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "dir" / "moeen.db"


@pytest.fixture
def repo(db_path):
    return EventRepository(Database(db_path), clock=StepClock())


def make(repo, **kw):
    args = dict(event_type="FALL", severity="HIGH", score=0.9)
    args.update(kw)
    return repo.create_event(**args)


# ---------------------------------------------------------------- initialization
def test_database_initializes_automatically_on_first_run(db_path):
    assert not db_path.exists()
    db = Database(db_path)                              # creates folders, file and tables
    assert db_path.exists() and db.schema_version() == SCHEMA_VERSION
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    assert {"events", "event_status_log"} <= tables
    assert {"id", "event_type", "created_at", "severity", "score", "duration_seconds", "status",
            "details_json"} <= cols


def test_initialization_is_idempotent_and_keeps_data(db_path):
    repo = EventRepository(Database(db_path))
    make(repo)
    Database(db_path)
    Database(db_path)
    assert EventRepository(Database(db_path)).count_events() == 1


def test_newer_schema_version_is_refused(db_path):
    Database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(DatabaseError, match="newer Moeen"):
        Database(db_path)


def test_non_moeen_or_corrupt_file_is_reported(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(DatabaseError):
        Database(bad)
    with pytest.raises(DatabaseError, match="on-disk path"):
        Database(":memory:")


# ---------------------------------------------------------------- create
def test_create_event(repo):
    e = repo.create_event(EventType.FALL, Severity.HIGH, 0.91, status=EventStatus.MONITORING,
                          duration_seconds=3.5, details={"peak": 3.4, "nested": {"a": [1, 2]}},
                          session_id="s1", incident_id=7, note="fall confirmed")
    assert e.id == 1 and e.event_type is EventType.FALL and e.severity is Severity.HIGH
    assert e.score == pytest.approx(0.91) and e.duration_seconds == pytest.approx(3.5)
    assert e.status is EventStatus.MONITORING and e.is_open and e.resolved_at is None
    assert e.details == {"peak": 3.4, "nested": {"a": [1, 2]}}
    assert e.created_at == e.updated_at == "2026-10-04T06:00:00.000Z"
    hist = repo.status_history(e.id)
    assert len(hist) == 1 and hist[0].from_status is None and hist[0].note == "fall confirmed"
    assert repo.get_event(e.id) == e
    assert repo.find_by_incident("s1", 7) == e


@pytest.mark.parametrize("kw, msg", [
    ({"event_type": "SEIZURE"}, "invalid event_type"),
    ({"severity": "CRITICAL"}, "invalid severity"),
    ({"score": 1.2}, "score must be"),
    ({"score": float("nan")}, "score must be"),
    ({"score": True}, "score must be"),
    ({"duration_seconds": -1}, "duration_seconds"),
    ({"details": {"x": object()}}, "JSON-serializable"),
    ({"details": {"x": float("inf")}}, "JSON-serializable"),
    ({"details": ["not", "a", "dict"]}, "mapping"),
    ({"status": "RESOLVED"}, "must start as"),
])
def test_invalid_events_are_rejected_and_nothing_is_written(repo, kw, msg):
    with pytest.raises(ValueError, match=msg):
        make(repo, **kw)
    assert repo.count_events() == 0


def test_duplicate_incident_in_same_session_is_rejected(repo):
    make(repo, session_id="s", incident_id=1)
    with pytest.raises(sqlite3.IntegrityError):
        make(repo, session_id="s", incident_id=1)
    make(repo, session_id="other", incident_id=1)          # same number, another run: fine


# ---------------------------------------------------------------- list
def test_list_events_newest_first_with_filters_and_paging(repo):
    a = make(repo, event_type="FALL", status="MONITORING")
    b = make(repo, event_type="LYING", severity="MEDIUM", score=0.5)
    c = make(repo, event_type="IMMOBILITY", severity="MEDIUM", score=0.6)
    repo.resolve_event(c.id, resolution="RECOVERED")
    assert [e.id for e in repo.list_events()] == [c.id, b.id, a.id]
    assert [e.id for e in repo.list_events(limit=2)] == [c.id, b.id]
    assert [e.id for e in repo.list_events(limit=2, offset=2)] == [a.id]
    assert [e.id for e in repo.list_events(open_only=True)] == [b.id, a.id]
    assert [e.id for e in repo.list_events(status="NEW")] == [b.id]
    assert [e.id for e in repo.list_events(status=["NEW", "RESOLVED"])] == [c.id, b.id]
    assert [e.id for e in repo.list_events(event_type=EventType.LYING)] == [b.id]
    assert repo.list_events(status="RESOLVED", open_only=True) == []
    assert repo.count_events() == 3 and repo.count_events(open_only=True) == 2


@pytest.mark.parametrize("kw", [{"limit": 0}, {"limit": 5000}, {"offset": -1}, {"status": "DONE"},
                                {"event_type": "X"}])
def test_list_rejects_bad_arguments(repo, kw):
    with pytest.raises(ValueError):
        repo.list_events(**kw)


# ---------------------------------------------------------------- update status
def test_update_status_follows_lifecycle_and_logs_each_change(repo):
    e = make(repo, status="MONITORING")
    e2 = repo.update_status(e.id, EventStatus.NEW, note="alert raised")
    assert e2.status is EventStatus.NEW and e2.resolved_at is None
    assert e2.updated_at > e.updated_at                          # text order == time order
    e3 = repo.record_assistance(e.id, note="helped up")
    assert e3.status is EventStatus.ASSISTANCE_RECORDED and e3.resolved_at == e3.updated_at
    assert e3.resolution == "ASSISTANCE_RECORDED" and not e3.is_open
    hist = repo.status_history(e.id)
    assert [(h.from_status, h.to_status) for h in hist] == [
        (None, EventStatus.MONITORING), (EventStatus.MONITORING, EventStatus.NEW),
        (EventStatus.NEW, EventStatus.ASSISTANCE_RECORDED)]
    assert [h.note for h in hist][1:] == ["alert raised", "helped up"]


@pytest.mark.parametrize("start, target", [("NEW", "MONITORING"), ("NEW", "NEW")])
def test_disallowed_status_changes_raise_and_change_nothing(repo, start, target):
    e = make(repo, status=start)
    with pytest.raises(InvalidStatusTransition):
        repo.update_status(e.id, target)
    assert repo.get_event(e.id) == e and len(repo.status_history(e.id)) == 1


def test_update_unknown_event_raises(repo):
    with pytest.raises(EventNotFound):
        repo.update_status(999, "RESOLVED")
    with pytest.raises(EventNotFound):
        repo.get_event(999)


def test_update_event_fields_and_merge_details(repo):
    e = make(repo, event_type="LYING", severity="LOW", score=0.3, details={"a": 1, "b": 2})
    e2 = repo.update_event(e.id, event_type="IMMOBILITY", severity="MEDIUM", score=0.7,
                           duration_seconds=61.0, details_update={"b": 3, "c": [4]})
    assert (e2.event_type, e2.severity, e2.score, e2.duration_seconds) == \
        (EventType.IMMOBILITY, Severity.MEDIUM, 0.7, 61.0)
    assert e2.details == {"a": 1, "b": 3, "c": [4]} and e2.status is e.status
    with pytest.raises(ValueError):
        repo.update_event(e.id, score=2.0)
    assert repo.get_event(e.id) == e2


# ---------------------------------------------------------------- resolve
def test_resolve_event(repo):
    e = make(repo, status="NEW")
    r = repo.resolve_event(e.id, resolution="RECOVERED_AFTER_ALERT", note="stood up",
                           duration_seconds=42.0)
    assert r.status is EventStatus.RESOLVED and r.resolution == "RECOVERED_AFTER_ALERT"
    assert r.resolved_at is not None and TS_RE.match(r.resolved_at) and r.duration_seconds == 42.0
    with pytest.raises(InvalidStatusTransition):           # RESOLVED is final
        repo.resolve_event(e.id)
    with pytest.raises(ValueError):
        repo.resolve_event(make(repo).id, resolution="  ")


def test_resolving_after_assistance_keeps_first_close_time(repo):
    e = make(repo)
    a = repo.record_assistance(e.id)
    r = repo.resolve_event(e.id, resolution="CLOSED")
    assert r.resolved_at == a.resolved_at and r.updated_at > a.updated_at


# ---------------------------------------------------------------- persistence
def test_events_persist_after_reopen(db_path):
    repo1 = EventRepository(Database(db_path), clock=StepClock())
    e = repo1.create_event("FALL", "HIGH", 0.95, status="MONITORING", details={"k": "v"})
    repo1.update_status(e.id, "NEW", note="alert")
    repo1.record_assistance(e.id, note="nurse")
    other = repo1.create_event("LYING", "LOW", 0.2, status="MONITORING")
    del repo1                                               # nothing kept in memory

    repo2 = EventRepository(Database(db_path))
    events = repo2.list_events()
    assert [x.id for x in events] == [other.id, e.id]
    reopened = repo2.get_event(e.id)
    assert reopened.status is EventStatus.ASSISTANCE_RECORDED and reopened.details == {"k": "v"}
    assert [h.to_status.value for h in repo2.status_history(e.id)] == \
        ["MONITORING", "NEW", "ASSISTANCE_RECORDED"]
    assert repo2.create_event("IMMOBILITY", "MEDIUM", 0.6).id == other.id + 1   # ids continue


# ---------------------------------------------------------------- safety
def test_sql_injection_attempts_are_inert(repo, db_path):
    payload = "'); DROP TABLE events; --"
    with pytest.raises(ValueError):
        make(repo, event_type=payload)
    e = make(repo, session_id=payload, details={payload: payload})
    repo.update_status(e.id, "RESOLVED", note=payload, resolution=payload)
    stored = repo.get_event(e.id)
    assert stored.session_id == payload and stored.details == {payload: payload}
    assert stored.resolution == payload and repo.status_history(e.id)[-1].note == payload
    assert repo.count_events() == 1                         # table still there


def test_repository_sql_uses_placeholders_only():
    """Static check: no f-string/format/% interpolation of values into execute() calls,
    except the fixed column lists built inside the repository."""
    import inspect

    import moeen.database.repository as r
    src = inspect.getsource(r)
    assert "%s" not in src and ".format(" not in src
    for line in src.splitlines():
        if "execute(f" in line:
            assert any(k in line for k in ("{where}", "{', '.join(sets)}")), line


def test_concurrent_writers_do_not_lose_updates(db_path):
    Database(db_path)

    def worker(n):
        repo = EventRepository(Database(db_path))
        for _ in range(15):
            e = repo.create_event("FALL", "HIGH", 0.5, status="MONITORING", session_id=f"w{n}")
            repo.update_status(e.id, "NEW")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    repo = EventRepository(Database(db_path))
    assert repo.count_events() == 60 and repo.count_events(status="NEW") == 60


# ---------------------------------------------------------------- timestamps
def test_timestamps_are_utc_fixed_width_and_sortable():
    local = datetime(2026, 10, 4, 9, 58, 12, 345678, tzinfo=timezone(timedelta(hours=3)))
    s = format_ts(local)
    assert s == "2026-10-04T06:58:12.345Z" and TS_RE.match(s)
    assert parse_ts(s) == local.replace(microsecond=345000)
    assert format_ts(T0) < format_ts(T0 + timedelta(milliseconds=1)) < format_ts(T0 + timedelta(days=1))
    with pytest.raises(ValueError):
        format_ts(datetime(2026, 1, 1))                       # naive datetime refused
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", to_local_display(s))
    assert to_local_display(None) == ""


def test_real_clock_timestamps_match_format(tmp_path):
    e = make(EventRepository(Database(tmp_path / "x.db")))
    assert TS_RE.match(e.created_at) and TS_RE.match(e.updated_at)
    d = e.to_dict()
    assert d["created_at_local"] and d["event_type"] == "FALL" and d["status"] == "NEW"
