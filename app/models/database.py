"""
Database model and initialisation.

We use SQLite — a lightweight database stored as a single file. No server needed.
Think of it like a very powerful spreadsheet that Python can query with SQL.

Tables:
  experiments  — one row per experiment run (the overall configuration)
  handshake_results — one row per individual TLS handshake attempt
"""

import sqlite3
import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ── SQL schema ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    mode            TEXT    NOT NULL,   -- 'classical', 'pqc', 'hybrid'
    repetitions     INTEGER NOT NULL,
    concurrency     INTEGER NOT NULL,
    warmup_runs     INTEGER NOT NULL DEFAULT 0,
    timeout_s       REAL    NOT NULL,
    target_host     TEXT    NOT NULL,
    target_port     INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    -- Aggregated metrics (filled when status='completed')
    mean_latency_ms     REAL,
    median_latency_ms   REAL,
    min_latency_ms      REAL,
    max_latency_ms      REAL,
    std_latency_ms      REAL,
    mean_bytes          REAL,
    median_bytes        REAL,
    success_count       INTEGER,
    failure_count       INTEGER,
    success_rate_pct    REAL,
    negotiated_tls_ver  TEXT,
    negotiated_group    TEXT,
    error_summary       TEXT,
    openssl_version     TEXT,
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS handshake_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   INTEGER NOT NULL REFERENCES experiments(id),
    run_index       INTEGER NOT NULL,   -- which repetition (0-based)
    is_warmup       INTEGER NOT NULL DEFAULT 0,  -- 1 if warmup run
    started_at      TEXT    NOT NULL,
    latency_ms      REAL,               -- NULL if handshake failed
    bytes_sent      INTEGER,            -- application-level bytes (see methodology doc)
    bytes_received  INTEGER,
    tls_version     TEXT,
    tls_group       TEXT,
    cipher_suite    TEXT,
    success         INTEGER NOT NULL,   -- 1=success, 0=failure
    error_type      TEXT,               -- e.g. 'timeout', 'ssl_error', 'connection_refused'
    error_detail    TEXT
);

CREATE INDEX IF NOT EXISTS idx_handshake_experiment
    ON handshake_results(experiment_id);
"""


_db_path: str = None


def init_db(db_path: str) -> None:
    """Create database tables if they don't exist."""
    global _db_path
    # Ensure the results directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _db_path = db_path
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info("Database initialised at %s", db_path)


@contextmanager
def get_connection():
    """
    Context manager that opens a database connection and automatically
    closes it when the 'with' block ends.

    Usage:
        with get_connection() as conn:
            conn.execute("SELECT ...")
    """
    if _db_path is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # better concurrent read performance
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain Python dictionary."""
    return dict(row) if row else None


def rows_to_list(rows) -> list:
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]
