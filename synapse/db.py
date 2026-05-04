import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    from_id     TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 5,
    status      TEXT NOT NULL DEFAULT 'pending',
    content     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_status (
    agent_id        TEXT PRIMARY KEY,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    state           TEXT NOT NULL DEFAULT 'offline',
    current_task    TEXT,
    workflow        TEXT,
    context_turns   INTEGER DEFAULT 0,
    last_heartbeat  DATETIME
);

CREATE TABLE IF NOT EXISTS tool_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    agent_id    TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    duration_ms INTEGER,
    status      TEXT NOT NULL,
    error_msg   TEXT
);

CREATE TABLE IF NOT EXISTS shared_state (
    key         TEXT PRIMARY KEY,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    value       TEXT NOT NULL
);
"""


def init_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
