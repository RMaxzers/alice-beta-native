"""§10.2 tabular queries: correct results on a synthetic CSV; everything but a bounded read of allowed tables is refused."""
from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from packages.schemas.models import Privacy

from services.structured_data import sql as S
from services.structured_data.sql import Filter, QueryPlan, SqlError, build_sql, execute, import_table, read_table

CSV = ("id;tipo;estado;criticidad;costo\n"
       "1;servidor;activo;alta;1200,50\n"
       "2;servidor;retirado;baja;800\n"
       "3;laptop;activo;alta;950\n"
       "4;laptop;activo;media;700\n"
       "5;switch;activo;alta;300\n"
       "6;servidor;activo;alta;1500\n").encode("utf-8-sig")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "tables.db"
    header, body = read_table("csv", CSV)
    import_table(path, "t_activos", header, body)
    import_table(path, "t_ajena", ["secreto"], [["no-deberias-verme"]])
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE big (n INTEGER)")
    con.executemany("INSERT INTO big VALUES (?)", [(i,) for i in range(1000)])
    con.commit()
    con.close()
    return path, header


def run(db, plan: QueryPlan, allowed=("t_activos",)):
    path, header = db
    sql, params = build_sql(plan, header)
    return execute(path, sql, params, set(allowed))


def test_import_types_and_header(db):
    _, header = db
    assert header == ["id", "tipo", "estado", "criticidad", "costo"]


def test_count_with_filters(db):
    plan = QueryPlan(table="t_activos", operation="count",
                     filters=[Filter(column="estado", op="=", value="ACTIVO"), Filter(column="criticidad", op="=", value="alta")])
    assert run(db, plan) == [{"n": 4}]


def test_group_count_and_sum(db):
    rows = run(db, QueryPlan(table="t_activos", operation="group_count", column="tipo"))
    assert {r["grp"]: r["n"] for r in rows} == {"servidor": 3, "laptop": 2, "switch": 1}
    total = run(db, QueryPlan(table="t_activos", operation="sum", column="costo",
                              filters=[Filter(column="tipo", op="=", value="servidor")]))
    assert total[0]["value"] == pytest.approx(3500.5)  # "1200,50" coerced as decimal comma


def test_filter_value_is_bound_not_interpolated(db):
    plan = QueryPlan(table="t_activos", operation="count",
                     filters=[Filter(column="tipo", op="=", value="x' OR '1'='1")])
    assert run(db, plan) == [{"n": 0}]
    plan = QueryPlan(table="t_activos", operation="count", filters=[Filter(column="tipo", op="contains", value="%")])
    assert run(db, plan) == [{"n": 0}]  # LIKE wildcards escaped


def test_plan_rejects_unknown_columns_fields_and_huge_limits(db):
    with pytest.raises(SqlError):
        run(db, QueryPlan(table="t_activos", operation="sum", column="costo) FROM t_ajena --"))
    with pytest.raises(ValidationError):
        QueryPlan(table="t_activos", operation="list", limit=S.MAX_ROWS + 1)
    with pytest.raises(ValidationError):
        QueryPlan(table="t_activos", operation="count", sql="DELETE FROM t_activos")
    with pytest.raises(ValidationError):
        QueryPlan(table="t_activos", operation="drop")


def test_foreign_table_blocked_even_through_plan(db):
    with pytest.raises(SqlError):
        run(db, QueryPlan(table="t_ajena", operation="list"), allowed=("t_activos",))


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t_ajena",
    "SELECT * FROM t_activos JOIN t_ajena",
    "SELECT * FROM t_activos WHERE id IN (SELECT rowid FROM t_ajena)",
    "SELECT name, sql FROM sqlite_master",
    "SELECT * FROM sqlite_schema",
    "INSERT INTO t_activos(id) VALUES (99)",
    "UPDATE t_activos SET estado='x'",
    "DELETE FROM t_activos",
    "DROP TABLE t_activos",
    "CREATE TABLE x(a)",
    "ATTACH DATABASE 'C:/Users/cuent/alice/storage/sqlite/alice.db' AS ops",
    "PRAGMA table_info(t_activos)",
    "PRAGMA writable_schema=ON",
    "SELECT load_extension('evil')",
    "SELECT readfile('C:/Windows/win.ini')",
    "SELECT * FROM t_activos; DELETE FROM t_activos",
    "SELECT 1; SELECT 2",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) SELECT count(*) FROM r",
    "SELECT sqlite_version()",
    "SELECT randomblob(1000000000)",
])
def test_raw_sql_attacks_rejected(db, sql):
    path, _ = db
    with pytest.raises(SqlError):
        execute(path, sql, [], {"t_activos"})
    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM t_activos").fetchone()[0] == 6  # nothing was modified
    con.close()


def test_row_limit_200(db):
    path, _ = db
    rows = execute(path, "SELECT * FROM big", [], {"big"})
    assert len(rows) == S.MAX_ROWS == 200


def test_expensive_query_times_out(db, monkeypatch):
    path, _ = db
    monkeypatch.setattr(S, "TIMEOUT_S", 0.3)
    with pytest.raises(SqlError, match="interrupt"):
        execute(path, "SELECT COUNT(*) FROM big a, big b, big c", [], {"big"})


def test_limits_are_the_spec_values():
    assert S.MAX_ROWS == 200 and S.TIMEOUT_S == 5.0


def test_structured_route_rejects_plan_for_foreign_table(api, state, net):
    """End to end: a (malicious/confused) model plan targeting another table is refused by code, not by the model."""
    import asyncio
    row, _ = state.ingestor.register("activos.csv", CSV, Privacy.PRIVATE, "admin")
    asyncio.run(state.ingestor.process(row["document_id"]))
    other, _ = state.ingestor.register("ajena.csv", b"secreto\nno-deberias-verme\n", Privacy.PRIVATE, "otro-usuario")
    asyncio.run(state.ingestor.process(other["document_id"]))
    foreign = state.con.execute("SELECT table_name FROM datasets WHERE owner='otro-usuario'").fetchone()[0]
    net.ollama.json_reply = f'{{"table":"{foreign}","operation":"list"}}'
    ev = api.chat(message="cuántos activos hay en la tabla", privacy="PRIVATE", document_ids=[row["document_id"]])
    text = "".join(e.get("text", "") for e in ev if e["type"] == "token")
    assert "no-deberias-verme" not in str(ev) and "No pude construir una consulta segura" in text
    own = state.con.execute("SELECT table_name FROM datasets WHERE owner='admin'").fetchone()[0]
    net.ollama.json_reply = (f'{{"table":"{own}","operation":"count","filters":[{{"column":"estado","op":"=","value":"activo"}},'
                             f'{{"column":"criticidad","op":"=","value":"alta"}}]}}')
    ev = api.chat(message="cuántos activos cumplen estado activo y criticidad alta", privacy="PRIVATE", document_ids=[row["document_id"]])
    assert "**4** filas" in "".join(e.get("text", "") for e in ev if e["type"] == "token")
    assert net.external == []


def test_single_column_csv_imports():
    header, body = read_table("csv", b"nombre\nalfa\nbeta\n")
    assert header == ["nombre"] and body == [["alfa"], ["beta"]]
