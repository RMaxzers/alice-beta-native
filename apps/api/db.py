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
    # 3 — task inbox, executed actions (idempotent, reconcilable) and per-change task events (undo). Additive only.
    """
    CREATE TABLE tasks (
      task_id TEXT PRIMARY KEY,
      owner TEXT NOT NULL,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL CHECK (status IN ('draft','open','in_progress','done','cancelled')),
      priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 4),
      kind TEXT NOT NULL DEFAULT 'personal' CHECK (kind IN ('personal','work')),
      due_date TEXT,                      -- local date YYYY-MM-DD in `timezone`
      due_time TEXT,                      -- HH:MM, optional
      timezone TEXT NOT NULL,
      origin TEXT NOT NULL CHECK (origin IN ('user','chat','evidence')),
      privacy TEXT NOT NULL,
      project TEXT,
      parent_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
      position REAL NOT NULL,
      sources_json TEXT NOT NULL DEFAULT '[]',
      action_id TEXT,                     -- action that created it (reconciliation after a crash)
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      completed_at TEXT,
      version INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX ix_tasks_owner ON tasks(owner, status, due_date);
    CREATE INDEX ix_tasks_action ON tasks(action_id);

    CREATE TABLE actions (
      action_id TEXT PRIMARY KEY,
      owner TEXT NOT NULL,
      idem_key TEXT,
      kind TEXT NOT NULL,
      level TEXT NOT NULL CHECK (level IN ('C0','C1','C2','C3')),
      status TEXT NOT NULL CHECK (status IN ('proposed','awaiting_authorization','running','done','failed','needs_review','cancelled')),
      origin TEXT NOT NULL,
      summary TEXT NOT NULL,
      input_json TEXT NOT NULL,
      task_id TEXT,
      error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX ux_actions_idem ON actions(owner, idem_key) WHERE idem_key IS NOT NULL;
    CREATE INDEX ix_actions_owner ON actions(owner, created_at);

    CREATE TABLE task_events (
      event_id INTEGER PRIMARY KEY,
      task_id TEXT NOT NULL,
      owner TEXT NOT NULL,
      action_id TEXT,
      at TEXT NOT NULL,
      actor TEXT NOT NULL,
      origin TEXT NOT NULL,
      op TEXT NOT NULL,                   -- create|update|reorder|undo
      before_json TEXT,
      after_json TEXT,
      undone_at TEXT
    );
    CREATE INDEX ix_task_events_task ON task_events(task_id, event_id);
    """,
    # 4 — per-user on/off toggle for local long-term memory (Hindsight sidecar). Additive only.
    """
    CREATE TABLE memory_prefs (
      owner TEXT PRIMARY KEY,
      enabled INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL
    );
    """,
]

MIGRATIONS.append("""
CREATE TABLE backend_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE conversations (
 conversation_id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
 privacy TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX ix_conversations_owner ON conversations(owner, updated_at);
CREATE TABLE chat_turns (
 turn_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
 owner TEXT NOT NULL, client_request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
 status TEXT NOT NULL, events_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
 UNIQUE(owner, client_request_id));
CREATE UNIQUE INDEX ux_chat_running ON chat_turns(conversation_id) WHERE status='running';
CREATE TABLE messages (
 message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
 turn_id TEXT NOT NULL REFERENCES chat_turns(turn_id), role TEXT NOT NULL,
 content TEXT NOT NULL, privacy TEXT NOT NULL, created_at TEXT NOT NULL, ordinal INTEGER NOT NULL);
CREATE INDEX ix_messages_conversation ON messages(conversation_id, ordinal);
CREATE TABLE file_operations (
 operation_id TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation_id TEXT NOT NULL,
 client_request_id TEXT NOT NULL, payload_hash TEXT NOT NULL, filename TEXT NOT NULL,
 destination TEXT NOT NULL, executor_name TEXT NOT NULL, privacy TEXT NOT NULL,
 content_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, file_identity TEXT,
 status TEXT NOT NULL, verification_json TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(owner, client_request_id));
""")

MIGRATIONS.append("""
ALTER TABLE messages ADD COLUMN sources_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE messages ADD COLUMN operation_ids_json TEXT NOT NULL DEFAULT '[]';
""")

_lock = threading.RLock()  # compatibility for callers supplying a raw test connection


class Result:
    """Detached cursor: SQLite rows are consumed while its connection is locked."""
    def __init__(self, cursor):
        self.rowcount, self.lastrowid = cursor.rowcount, cursor.lastrowid
        self._rows = iter(cursor.fetchall() if cursor.description else ())
        cursor.close()

    def fetchone(self):
        return next(self._rows, None)

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return self._rows


class Database:
    """Serialized SQLite access, including reads and cursor consumption.

    tx() holds this reentrant lock for the entire synchronous transaction. No
    other thread can join it or see its uncommitted changes. Never await in tx().
    SQLite BEGIN IMMEDIATE provides the corresponding inter-process writer lock.
    """
    def __init__(self, con):
        self._con = con
        self.lock = threading.RLock()

    def execute(self, sql, parameters=()):
        with self.lock:
            return Result(self._con.execute(sql, parameters))

    def executemany(self, sql, parameters):
        with self.lock:
            return Result(self._con.executemany(sql, parameters))

    def executescript(self, sql):
        with self.lock:
            return Result(self._con.executescript(sql))

    @property
    def in_transaction(self):
        with self.lock:
            return self._con.in_transaction

    def close(self):
        with self.lock:
            self._con.close()


def connect(path: Path | None = None) -> Database:
    path = path or settings().ops_db
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: autocommit; transactions are explicit via tx().
    con = sqlite3.connect(path, timeout=10, check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return Database(con)


@contextmanager
def tx(con: sqlite3.Connection):
    with getattr(con, "lock", _lock):
        if con.in_transaction:
            raise RuntimeError("Nested transactions are not supported")
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise


def migrate(con: sqlite3.Connection) -> int:
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[ver:], start=ver + 1):
        con.executescript(f"BEGIN; {sql}; PRAGMA user_version={i}; COMMIT;")
    return con.execute("PRAGMA user_version").fetchone()[0]
