"""Database layer: SQLAlchemy Core schema + portable bulk upsert.

Default backend is SQLite (``data/bioterm.db``). Set ``DATABASE_URL`` to a
``postgresql+psycopg://`` URL to move the exact same schema to Postgres for a
cloud deployment - no code changes needed.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.engine import Engine

from .config import load_settings

metadata = MetaData()

securities = Table(
    "securities", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("name", String(256)),
    Column("exchange", String(32)),
    Column("cik", String(16)),
    Column("is_watchlist", Integer, default=0),
    Column("in_xbi", Integer, default=0),
    Column("in_ibb", Integer, default=0),
    Column("in_seed", Integer, default=0),
    Column("etf_weight", Float),
    Column("updated_at", DateTime),
)

prices = Table(
    "prices", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("open", Float),
    Column("high", Float),
    Column("low", Float),
    Column("close", Float),
    Column("adj_close", Float),
    Column("volume", Float),
)

technicals = Table(
    "technicals", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("close", Float),
    Column("sma20", Float),
    Column("sma50", Float),
    Column("sma200", Float),
    Column("rsi14", Float),
    Column("macd", Float),
    Column("macd_signal", Float),
    Column("macd_hist", Float),
    Column("atr14", Float),
    Column("bb_upper", Float),
    Column("bb_lower", Float),
    Column("vol_z20", Float),
    Column("pct_52w_range", Float),   # 0 = at 52w low, 1 = at 52w high
    Column("ret_1m", Float),
    Column("ret_3m", Float),
    Column("ret_6m", Float),
)

fundamentals = Table(
    "fundamentals", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("market_cap", Float),
    Column("shares_out", Float),
    Column("float_shares", Float),
    Column("short_percent_float", Float),
    Column("cash", Float),                 # cash + short-term investments (most recent)
    Column("rd_expense_ttm", Float),
    Column("net_income_ttm", Float),
    Column("op_cash_flow_ttm", Float),
    Column("burn_ttm", Float),             # positive number = annual cash burn
    Column("runway_quarters", Float),
    Column("next_earnings_date", Date),
    Column("sources", String(128)),
    Column("updated_at", DateTime),
)

clinical_trials = Table(
    "clinical_trials", metadata,
    Column("nct_id", String(24), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("sponsor", String(256)),
    Column("title", Text),
    Column("phase", String(32)),
    Column("status", String(48)),
    Column("study_type", String(32)),
    Column("start_date", Date),
    Column("primary_completion_date", Date),
    Column("completion_date", Date),
    Column("conditions", Text),
    Column("interventions", Text),
    Column("enrollment", Float),
    Column("last_update_post_date", Date),
    Column("url", String(256)),
    Column("fetched_at", DateTime),
)

fda_events = Table(
    "fda_events", metadata,
    Column("id", String(40), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("kind", String(24)),
    Column("application_number", String(32)),
    Column("brand_name", String(256)),
    Column("generic_name", String(256)),
    Column("sponsor_name", String(256)),
    Column("event_date", Date),
    Column("description", Text),
    Column("url", String(256)),
    Column("fetched_at", DateTime),
)

filings = Table(
    "filings", metadata,
    Column("id", String(64), primary_key=True),   # accession no (dashed)
    Column("ticker", String(16), index=True),
    Column("cik", String(16)),
    Column("form", String(16)),
    Column("filed_date", Date),
    Column("title", Text),
    Column("items", String(256)),
    Column("url", String(256)),
    Column("fetched_at", DateTime),
)

news = Table(
    "news", metadata,
    Column("id", String(40), primary_key=True),   # sha1 of url
    Column("ticker", String(16), index=True),     # primary ticker (may be null)
    Column("tickers_csv", String(256)),           # all matched tickers
    Column("title", Text),
    Column("summary", Text),
    Column("url", String(512)),
    Column("source", String(64)),
    Column("published", DateTime, index=True),
    Column("sentiment", Float),                   # VADER compound [-1, 1]
    Column("event_tags", String(256)),
    Column("event_score", Float),                 # signed sum of matched event weights
    Column("fetched_at", DateTime),
)

catalysts = Table(
    "catalysts", metadata,
    Column("id", String(48), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("type", String(32)),
    Column("title", Text),
    Column("date", Date, index=True),
    Column("months_away", Float),
    Column("confidence", String(16)),
    Column("source", String(48)),
    Column("url", String(256)),
    Column("created_at", DateTime),
)

scores = Table(
    "scores", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("asof", Date, primary_key=True),
    Column("focus_score", Float, index=True),
    Column("momentum", Float),
    Column("catalyst", Float),
    Column("newsflow", Float),
    Column("risk", Float),
    Column("conviction_mult", Float),
    Column("rank", Integer),
    Column("rationale", Text),   # JSON
)

ingest_runs = Table(
    "ingest_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job", String(48)),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
    Column("status", String(16)),
    Column("rows", Integer),
    Column("detail", Text),
)


_ENGINE: Engine | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        url = load_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _ENGINE = create_engine(url, future=True, connect_args=connect_args)
    return _ENGINE


def init_db() -> list[str]:
    engine = get_engine()
    metadata.create_all(engine)
    return sorted(inspect(engine).get_table_names())


def _clean_rows(table: Table, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    cols = set(table.c.keys())
    cleaned_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for r in rows:
        cleaned = {k: v for k, v in r.items() if k in cols}
        for k, v in list(cleaned.items()):
            if isinstance(v, float) and pd.isna(v):
                cleaned[k] = None
        cleaned_rows.append(cleaned)
        seen_keys.update(cleaned.keys())
    # SQLAlchemy multi-VALUES insert needs a consistent key set across all rows
    out = [{k: r.get(k) for k in seen_keys} for r in cleaned_rows]
    return out


def bulk_upsert(
    table: Table,
    rows: Sequence[dict[str, Any]],
    update_only: Sequence[str] | None = None,
) -> int:
    """Insert-or-update ``rows`` keyed on ``table``'s primary key. SQLite + Postgres.

    ``update_only`` restricts which columns are overwritten on conflict - use it
    for partial updates (e.g. backfilling sentiment on existing news rows) so the
    other columns are not clobbered with NULL.
    """
    rows = _clean_rows(table, rows)
    if not rows:
        return 0
    engine = get_engine()
    pk_cols = [c.name for c in table.primary_key.columns]
    dialect = engine.dialect.name

    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as _insert
    elif dialect in ("postgresql", "postgres"):
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:  # pragma: no cover - fallback: naive delete+insert
        return _fallback_upsert(engine, table, rows, pk_cols)

    allowed = set(update_only) if update_only else None
    with engine.begin() as conn:
        stmt = _insert(table).values(rows)
        # NB: subscript, not getattr - a column named 'items'/'keys'/'values'
        # would otherwise resolve to the collection's method.
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in table.c
            if c.name not in pk_cols and (allowed is None or c.name in allowed)
        }
        stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)
        conn.execute(stmt)
    return len(rows)


def _fallback_upsert(engine, table, rows, pk_cols) -> int:
    with engine.begin() as conn:
        for r in rows:
            cond = [table.c[k] == r[k] for k in pk_cols]
            conn.execute(table.delete().where(*cond))
        conn.execute(table.insert(), rows)
    return len(rows)


def read_sql(query, params: dict | None = None) -> pd.DataFrame:
    """Run a SQLAlchemy selectable or raw SQL string -> DataFrame."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params=params)


def table_count(table: Table) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())
