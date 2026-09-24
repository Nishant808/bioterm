"""read_sql runs reads in autocommit (half the round trips to Neon). That must never
leak into a write: the pool has to hand the next caller a transactional connection."""
import pytest

from bioterm.db import app_meta, get_engine, init_db, read_sql


def test_reads_leave_the_pooled_connection_transactional():
    init_db()
    assert read_sql("SELECT 1 AS x")["x"].tolist() == [1]
    # the same pooled connection now serves a write that fails half-way
    with pytest.raises(RuntimeError), get_engine().begin() as conn:
        conn.execute(app_meta.insert(), {"key": "probe", "value": "1"})
        raise RuntimeError("roll back")
    assert read_sql("SELECT key FROM app_meta WHERE key = 'probe'").empty


def test_read_sql_binds_params_and_accepts_selectables():
    from sqlalchemy import select

    init_db()
    with get_engine().begin() as conn:
        conn.execute(app_meta.insert(), [{"key": "a", "value": "1"}, {"key": "b", "value": "2"}])
    assert read_sql("SELECT value FROM app_meta WHERE key = :k", {"k": "b"})["value"].tolist() == ["2"]
    assert read_sql(select(app_meta.c.key).order_by(app_meta.c.key))["key"].tolist() == ["a", "b"]


def test_migrate_adds_new_columns_to_an_existing_table():
    """A database created by an older schema (fundamentals without the session-9
    columns) gains them on the next init_db, keeping its rows."""
    from sqlalchemy import inspect, text

    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE fundamentals (ticker VARCHAR(16) PRIMARY KEY, "
                          "market_cap FLOAT)"))
        conn.execute(text("INSERT INTO fundamentals VALUES ('OLD', 1.0)"))
    init_db()
    cols = {c["name"] for c in inspect(eng).get_columns("fundamentals")}
    assert {"short_ratio", "held_pct_institutions", "runway_quarters"} <= cols
    assert read_sql("SELECT ticker, market_cap FROM fundamentals")["ticker"].tolist() == ["OLD"]
    from bioterm.db import migrate

    assert migrate() == []  # idempotent
