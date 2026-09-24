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
