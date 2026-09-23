"""Operational SQLite (catalog, ledger, tickets, facts, requests). Analytic tables live in a separate DB."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from apps.api.config import settings

MIGRATIONS: list[str] = [
    # 1 — base schema
    """
    CREATE TABLE documents (
      document_id TEXT PRIMARY KEY,
      original_name TEXT NOT NULL,
      stored_path TEXT NOT NULL,
      checksum TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      mime TEXT NOT NULL,
      kind TEXT NOT NULL,                 -- pdf|markdown|text|log|csv|xlsx
      source TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      supersedes TEXT,
      ingested_at TEXT NOT NULL,
      language TEXT,
      privacy TEXT NOT NULL,
      verification TEXT NOT NULL,
      extractor TEXT,
      embedding_model TEXT,
      embedding_dim INTEGER,
      owner TEXT NOT NULL,
      status TEXT NOT NULL,               -- pending|processing|ready|failed
      status_detail TEXT,
      chunks INTEGER DEFAULT 0
    );
    CREATE UNIQUE INDEX ux_documents_checksum ON documents(checksum);

    CREATE TABLE chunks (
      chunk_id TEXT PRIMARY KEY,
      document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
      ordinal INTEGER NOT NULL,
      location TEXT NOT NULL,             -- "página 3" / "sección: X"
      text TEXT NOT NULL
    );

    CREATE TABLE datasets (
      table_name TEXT PRIMARY KEY,
      document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
      owner TEXT NOT NULL,
      privacy TEXT NOT NULL,
      columns_json TEXT NOT NULL,
      row_count INTEGER NOT NULL
    );

    CREATE TABLE log_events (
      id INTEGER PRIMARY KEY,
      document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
      line_no INTEGER NOT NULL,
      ts TEXT,                            -- ISO; NULL when undetectable
      ts_has_tz INTEGER NOT NULL DEFAULT 0,
      severity TEXT,
      template TEXT NOT NULL,
      message TEXT NOT NULL
    );
    CREATE INDEX ix_log_events_doc ON log_events(document_id, severity);

    CREATE TABLE facts (
      fact_id TEXT PRIMARY KEY,
      subject_key TEXT NOT NULL,
      statement TEXT NOT NULL,
      privacy TEXT NOT NULL,
      verification TEXT NOT NULL,
      source_id TEXT NOT NULL,
      source_location TEXT,
      verified_by TEXT,
      verified_at TEXT,
      valid_until TEXT,
      notes TEXT,
      created_at TEXT NOT NULL
    );
    CREATE INDEX ix_facts_subject ON facts(subject_key);

    CREATE TABLE requests (
      request_id TEXT PRIMARY KEY,        -- opaque id
      started_at TEXT NOT NULL,
      finished_at TEXT,
      route TEXT,
      decided_by TEXT,
      provider TEXT,
      model TEXT,
      privacy TEXT,
      status TEXT,
      duration_s REAL,
      queue_s REAL,
      retrieval_s REAL,
      provider_s REAL,
      tokens_in INTEGER,
      tokens_out INTEGER,
      error TEXT
    );
    CREATE INDEX ix_requests_started ON requests(started_at);

    CREATE TABLE ledger (
      attempt_id TEXT PRIMARY KEY,
      request_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      route TEXT,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      reserved_usd REAL NOT NULL,
      estimated_usd REAL,
      reported_usd REAL,
      tokens_in INTEGER,
      tokens_out INTEGER,
      state TEXT NOT NULL                 -- reserved|reconciled|released|unknown_cost
    );
    CREATE INDEX ix_ledger_created ON ledger(created_at);

    CREATE TABLE egress_tickets (
      ticket_id TEXT PRIMARY KEY,
      username TEXT NOT NULL,
      payload_hash TEXT NOT NULL,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      max_cost_usd REAL NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      approved_at TEXT,
      used_at TEXT
    );

    CREATE TABLE audit (
      id INTEGER PRIMARY KEY,
      at TEXT NOT NULL,
      actor TEXT NOT NULL,
      action TEXT NOT NULL,
      target TEXT,
      outcome TEXT NOT NULL,
      duration_ms INTEGER
    );
    """,
    # 2 — per-owner isolation (facts, dedupe), server-side sessions (revocable logout), resumable egress tickets
    """
    ALTER TABLE facts ADD COLUMN owner TEXT;
    CREATE INDEX ix_facts_owner ON facts(owner, subject_key);
    DROP INDEX ux_documents_checksum;
    CREATE UNIQUE INDEX ux_documents_owner_checksum ON documents(owner, checksum);
    CREATE TABLE sessions (
      sid TEXT PRIMARY KEY,
      username TEXT NOT NULL,
      created_at TEXT NOT NULL,
      expires_at INTEGER NOT NULL
    );
    ALTER TABLE egress_tickets ADD COLUMN route TEXT;
    ALTER TABLE egress_tickets ADD COLUMN model_alias TEXT;
    """,
]

_lock = threading.Lock()  # ponytail: single-writer lock for one process; fine for a single-user beta


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or settings().ops_db
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: autocommit; transactions are explicit via tx().
    con = sqlite3.connect(path, timeout=10, check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


@contextmanager
def tx(con: sqlite3.Connection):
    with _lock:
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise


def migrate(con: sqlite3.Connection) -> int:
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[ver:], start=ver + 1):
        con.executescript(f"BEGIN; {sql}; PRAGMA user_version={i}; COMMIT;")
    return con.execute("PRAGMA user_version").fetchone()[0]
