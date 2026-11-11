-- Moeen event history - schema version 1.
-- Applied automatically by moeen.database.db.Database on first run (PRAGMA user_version = 1).
-- All timestamps are UTC ISO-8601 strings with milliseconds, e.g. 2026-10-04T06:58:12.345Z.

CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type       TEXT    NOT NULL CHECK (event_type IN ('FALL', 'LYING', 'IMMOBILITY')),
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    resolved_at      TEXT,              -- first time the event left an open status
    severity         TEXT    NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    score            REAL    NOT NULL CHECK (score >= 0.0 AND score <= 1.0),  -- system score, not a medical probability
    duration_seconds REAL    CHECK (duration_seconds IS NULL OR duration_seconds >= 0.0),
    status           TEXT    NOT NULL CHECK (status IN ('MONITORING', 'NEW', 'ASSISTANCE_RECORDED', 'RESOLVED')),
    resolution       TEXT,              -- how it ended, e.g. RECOVERED, ASSISTANCE_RECORDED
    session_id       TEXT,              -- one run of the application
    incident_id      INTEGER,           -- detector incident number within that run
    details_json     TEXT    NOT NULL DEFAULT '{}',
    UNIQUE (session_id, incident_id)
);

CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at);
CREATE INDEX IF NOT EXISTS idx_events_status     ON events (status);

-- Every status change, for the audit trail shown with an event.
CREATE TABLE IF NOT EXISTS event_status_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    changed_at  TEXT    NOT NULL,
    from_status TEXT,                   -- NULL for the creation entry
    to_status   TEXT    NOT NULL,
    note        TEXT
);

CREATE INDEX IF NOT EXISTS idx_status_log_event ON event_status_log (event_id);
