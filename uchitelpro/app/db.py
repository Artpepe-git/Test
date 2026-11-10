"""SQLite: подключение, схема, простые миграции."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups_ (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    course INTEGER NOT NULL DEFAULT 1,
    teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_demo INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student','teacher','methodist','admin')),
    group_id INTEGER REFERENCES groups_(id) ON DELETE SET NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    must_change INTEGER NOT NULL DEFAULT 0,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    difficulty INTEGER NOT NULL DEFAULT 1,
    duration_min INTEGER NOT NULL DEFAULT 10,
    description TEXT NOT NULL DEFAULT '',
    author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','published','archived')),
    current_version_id INTEGER,
    draft_graph TEXT,
    draft_review TEXT,
    source_note_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    graph TEXT NOT NULL,
    review TEXT NOT NULL,
    stats TEXT NOT NULL,
    published_at TEXT NOT NULL,
    UNIQUE (case_id, version)
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    group_id INTEGER REFERENCES groups_(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    assigned_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    due_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    version_id INTEGER NOT NULL REFERENCES case_versions(id),
    practice INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','finished')),
    current_node TEXT NOT NULL,
    final_node TEXT,
    outcome TEXT,
    score_pct REAL,
    earned INTEGER,
    best_total INTEGER,
    stars INTEGER,
    xp_awarded INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS attempt_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    choice_id TEXT NOT NULL,
    to_node TEXT NOT NULL,
    scores TEXT NOT NULL,
    spent_sec INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempt_scores (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    comp_code TEXT NOT NULL,
    earned INTEGER NOT NULL,
    max_score INTEGER NOT NULL,
    PRIMARY KEY (attempt_id, comp_code)
);

CREATE TABLE IF NOT EXISTS xp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id INTEGER,
    xp INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS badges (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '★'
);

CREATE TABLE IF NOT EXISTS user_badges (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_code TEXT NOT NULL REFERENCES badges(code) ON DELETE CASCADE,
    awarded_at TEXT NOT NULL,
    PRIMARY KEY (user_id, badge_code)
);

CREATE TABLE IF NOT EXISTS volunteer_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shift_date TEXT NOT NULL,
    place TEXT NOT NULL,
    form TEXT NOT NULL,
    hours REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    confirmed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    confirm_comment TEXT NOT NULL DEFAULT '',
    xp_awarded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shift_id INTEGER REFERENCES volunteer_shifts(id) ON DELETE SET NULL,
    situation TEXT NOT NULL,
    action TEXT NOT NULL,
    result TEXT NOT NULL,
    lesson TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('draft','submitted','accepted','rejected','converted')),
    reviewer_comment TEXT NOT NULL DEFAULT '',
    case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    entity TEXT NOT NULL DEFAULT '',
    entity_id INTEGER,
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_steps_attempt ON attempt_steps(attempt_id, seq);
CREATE INDEX IF NOT EXISTS idx_xp_user ON xp_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_shifts_user ON volunteer_shifts(user_id, status);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
    if row is None:
        conn.execute("INSERT INTO settings(key, value) VALUES ('schema_version', ?)",
                     (json.dumps(SCHEMA_VERSION),))
    # Здесь добавляются миграции: if current < 2: ALTER TABLE ...


def rows(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, tuple(args)).fetchall()


def one(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, tuple(args)).fetchone()


def scalar(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = (), default: Any = None) -> Any:
    row = conn.execute(sql, tuple(args)).fetchone()
    return default if row is None or row[0] is None else row[0]


def insert(conn: sqlite3.Connection, table: str, **values: Any) -> int:
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
    return int(cur.lastrowid)


def audit(conn: sqlite3.Connection, actor_id: int | None, action: str,
          entity: str = "", entity_id: int | None = None, details: str = "") -> None:
    insert(conn, "audit_log", actor_id=actor_id, action=action, entity=entity,
           entity_id=entity_id, details=details, created_at=now())
