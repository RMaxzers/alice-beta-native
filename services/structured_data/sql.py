"""Tabular data: import CSV/XLSX into a separate SQLite and answer with typed query plans.

The LLM never writes SQL. It may only fill a QueryPlan (validated against the real schema);
SQL is built here with quoted identifiers + bound parameters, and executed on a read-only
connection guarded by sqlite3.set_authorizer (SELECT/READ on allowed tables only).
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_ROWS = 200
TIMEOUT_S = 5.0


class SqlError(Exception):
    pass


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    op: Literal["=", "!=", ">", ">=", "<", "<=", "contains", "is_empty", "not_empty"]
    value: str | float | None = None


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    operation: Literal["count", "sum", "avg", "min", "max", "group_count", "list"]
    column: str | None = None           # for sum/avg/min/max/group_count
    filters: list[Filter] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=20, ge=1, le=MAX_ROWS)


def safe_ident(name: str) -> str:
    n = re.sub(r"[^0-9a-zA-Z_]", "_", name.strip().lower())
    n = re.sub(r"_+", "_", n).strip("_") or "col"
    return ("c_" + n) if n[0].isdigit() else n


def q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _coerce(v: str):
    s = v.strip()
    if s == "":
        return None
    t = s.replace(",", ".") if re.fullmatch(r"-?\d+,\d+", s) else s
    try:
        return int(t) if re.fullmatch(r"-?\d+", t) else float(t) if re.fullmatch(r"-?\d+\.\d+", t) else s
    except ValueError:
        return s


def read_table(kind: str, data: bytes) -> tuple[list[str], list[list]]:
    if kind == "csv":
        text = data.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        rows = list(csv.reader(io.StringIO(text), dialect))
    elif kind == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)  # data_only: never evaluate formulas
        ws = wb.worksheets[0]
        rows = [["" if c is None else str(c) for c in r] for r in ws.iter_rows(values_only=True)]
    else:
        raise SqlError(f"Tipo tabular no soportado: {kind}")
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        raise SqlError("La tabla no tiene encabezado y datos")
    header, seen = [], set()
    for h in rows[0]:
        n = safe_ident(str(h))
        while n in seen:
            n += "_2"
        seen.add(n)
        header.append(n)
    body = [[_coerce(str(c)) for c in (r + [""] * len(header))[: len(header)]] for r in rows[1:]]
    return header, body


def import_table(db: Path, table: str, header: list[str], body: list[list]) -> None:
    con = sqlite3.connect(db, isolation_level=None)
    try:
        con.execute("BEGIN")
        con.execute(f"DROP TABLE IF EXISTS {q(table)}")
        con.execute(f"CREATE TABLE {q(table)} ({', '.join(q(h) for h in header)})")
        con.executemany(f"INSERT INTO {q(table)} VALUES ({', '.join('?' * len(header))})", body)
        con.execute("COMMIT")
    finally:
        con.close()


def build_sql(plan: QueryPlan, columns: list[str]) -> tuple[str, list]:
    cols = set(columns)
    for c in [plan.column] + [f.column for f in plan.filters]:
        if c is not None and c not in cols:
            raise SqlError(f"Columna desconocida: {c}")
    where, params = [], []
    for f in plan.filters:
        col = q(f.column)
        if f.op == "contains":
            where.append(f"LOWER(CAST({col} AS TEXT)) LIKE ? ESCAPE '\\'")
            params.append("%" + str(f.value).lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        elif f.op == "is_empty":
            where.append(f"({col} IS NULL OR TRIM(CAST({col} AS TEXT)) = '')")
        elif f.op == "not_empty":
            where.append(f"({col} IS NOT NULL AND TRIM(CAST({col} AS TEXT)) != '')")
        elif f.op in ("=", "!=") and isinstance(f.value, str):
            where.append(f"LOWER(CAST({col} AS TEXT)) {f.op} LOWER(?)")
            params.append(f.value)
        else:
            where.append(f"{col} {f.op} ?")
            params.append(f.value)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    t = q(plan.table)
    if plan.operation == "count":
        return f"SELECT COUNT(*) AS n FROM {t}{w}", params
    if plan.operation in ("sum", "avg", "min", "max"):
        if not plan.column:
            raise SqlError("La operación requiere columna")
        return f"SELECT {plan.operation.upper()}({q(plan.column)}) AS value FROM {t}{w}", params
    if plan.operation == "group_count":
        if not plan.column:
            raise SqlError("group_count requiere columna")
        return f"SELECT {q(plan.column)} AS grp, COUNT(*) AS n FROM {t}{w} GROUP BY 1 ORDER BY 2 DESC LIMIT {plan.limit}", params
    return f"SELECT * FROM {t}{w} LIMIT {plan.limit}", params


def execute(db: Path, sql: str, params: list, allowed_tables: set[str]) -> list[dict]:
    """Read-only, single statement, authorizer-restricted, bounded time and rows."""
    if ";" in sql.strip().rstrip(";"):
        raise SqlError("Solo se permite una sentencia")
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    def authorizer(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK if arg1 in allowed_tables else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if (arg2 or "").lower() in {"count", "sum", "avg", "min", "max", "lower", "trim", "cast", "like"} else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY  # ATTACH, PRAGMA, INSERT, UPDATE, DELETE, CREATE, ...

    con.set_authorizer(authorizer)
    deadline = time.monotonic() + TIMEOUT_S
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = con.execute(sql, params)
        return [dict(r) for r in cur.fetchmany(MAX_ROWS)]
    except sqlite3.DatabaseError as e:
        raise SqlError(f"Consulta rechazada: {e}") from e
    finally:
        con.close()
