"""Housekeeping: retention (prune what grows without bound), database size, backups
(every table to a zip of JSON-lines files + a manifest) and restore, and backfills.

Neon's free plan holds 512 MB, so ``retention`` runs with every full refresh; the
windows live in settings.yml (``retention:``) and default to the table below.
Backups leave out the encrypted API keys (``app_secrets``) and the owner passcode
hash unless asked - an artifact should not carry credentials.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger("bioterm.maintenance")

# table -> (time column, days kept)
RETENTION: dict[str, tuple[str, int]] = {
    "news": ("published", 180),
    "news_nlp": ("scored_at", 180),
    "news_llm": ("scored_at", 365),
    "alerts_fired": ("ts", 180),
    "ingest_runs": ("started_at", 60),
    "score_snapshots": ("ts", 180),
    "dq_checks": ("run_at", 45),
    "halts": ("halt_at", 365),
    "options_snapshots": ("date", 400),
    "short_volume": ("date", 400),
    "llm_usage": ("day", 400),
    "trial_changes": ("detected_at", 730),
    "fundamental_snapshots": ("asof", 1100),
    # every run rewrites the last 400 sessions; older rows are never read (the backtest
    # works from prices)
    "technicals": ("date", 600),
}
SECRET_TABLES = {"app_secrets"}
SECRET_META = {"admin_auth", "worker_lease"}


def _cutoff(table, col: str, days: int):
    from sqlalchemy import DateTime

    now = datetime.now(timezone.utc) - timedelta(days=days)
    return now.replace(tzinfo=None) if isinstance(table.c[col].type, DateTime) else now.date()


def retention(dry_run: bool = False, windows: dict[str, int] | None = None) -> dict[str, Any]:
    """Delete rows older than each table's window. Core ``delete().where(col < cut)``
    so the column type binds the cut on SQLite and Postgres alike."""
    from sqlalchemy import func, select

    from .config import load_settings
    from .db import get_engine, metadata

    cfg = dict(load_settings().get("retention", default={}) or {})
    cfg.update(windows or {})
    out: dict[str, Any] = {}
    total = 0
    eng = get_engine()
    for name, (col, days) in RETENTION.items():
        days = int(cfg.get(name, days))
        t = metadata.tables.get(name)
        if t is None or col not in t.c or days <= 0:
            continue
        cut = _cutoff(t, col, days)
        cond = t.c[col] < cut
        try:
            with eng.begin() as conn:
                if dry_run:
                    n = conn.execute(select(func.count()).select_from(t).where(cond)).scalar()
                else:
                    n = conn.execute(t.delete().where(cond)).rowcount
        except Exception as exc:  # noqa: BLE001
            out[name] = f"error: {exc}"
            continue
        n = int(n or 0)
        total += n
        if n:
            out[name] = n
    log.info("retention%s: %d rows %s", " (dry run)" if dry_run else "", total,
             "would go" if dry_run else "deleted")
    return {"rows": total, "dry_run": dry_run, "tables": out}


def db_size() -> dict[str, Any]:
    """Total size and the biggest tables (Postgres) or the file size (SQLite)."""
    from sqlalchemy import text

    from .db import get_engine, read_sql

    eng = get_engine()
    if eng.dialect.name.startswith("postgres"):
        tables = read_sql(
            "SELECT c.relname AS name, c.reltuples::bigint AS approx_rows, "
            "pg_total_relation_size(c.oid) AS bytes FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE c.relkind = 'r' AND n.nspname = 'public' "
            "ORDER BY bytes DESC")
        with eng.connect() as conn:
            total = int(conn.execute(text("SELECT pg_database_size(current_database())"))
                        .scalar() or 0)
        return {"dialect": "postgresql", "bytes": total,
                "tables": tables.head(25).to_dict("records")}
    db = eng.url.database
    size = Path(db).stat().st_size if db and Path(db).exists() else 0
    return {"dialect": eng.dialect.name, "bytes": size, "tables": []}


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, bool)):
        return v
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "item"):                      # numpy scalars
        return _jsonable(v.item())
    return str(v)


def backup(out: str | Path, include_secrets: bool = False) -> dict[str, Any]:
    """Every table -> ``<table>.jsonl`` (one JSON object per row) inside one zip,
    plus ``manifest.json``. Rows stream from the database, so memory stays flat."""
    from sqlalchemy import select

    from .db import get_engine, init_db, metadata

    init_db()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    eng = get_engine()
    manifest: dict[str, Any] = {"format": 1,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                                "dialect": eng.dialect.name, "tables": {}}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, t in metadata.tables.items():
            if name in SECRET_TABLES and not include_secrets:
                continue
            n = 0
            cols = [c.name for c in t.c]
            with eng.connect() as conn, z.open(f"{name}.jsonl", "w") as fh:
                res = conn.execution_options(stream_results=True, yield_per=5000) \
                    .execute(select(t))
                for row in res:
                    rec = dict(zip(cols, row))
                    if name == "app_meta" and not include_secrets \
                            and rec.get("key") in SECRET_META:
                        continue
                    fh.write((json.dumps({k: _jsonable(v) for k, v in rec.items()},
                                         separators=(",", ":")) + "\n").encode())
                    n += 1
            manifest["tables"][name] = n
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    rows = sum(manifest["tables"].values())
    log.info("backup: %d tables, %d rows -> %s (%.1f MB)", len(manifest["tables"]), rows,
             out, out.stat().st_size / 1e6)
    return {"rows": rows, "tables": len(manifest["tables"]), "path": str(out),
            "bytes": out.stat().st_size}


def _typed(t, rec: dict[str, Any]) -> dict[str, Any]:
    """JSON values back to what the column wants (ISO strings -> date / datetime)."""
    from sqlalchemy import Date, DateTime

    out = {}
    for k, v in rec.items():
        if k not in t.c:
            continue
        typ = t.c[k].type
        if v is not None and isinstance(typ, (Date, DateTime)) and isinstance(v, str):
            ts = pd.to_datetime(v, errors="coerce", utc=isinstance(typ, DateTime))
            if pd.isna(ts):
                v = None
            elif isinstance(typ, DateTime):
                v = ts.tz_localize(None).to_pydatetime()
            else:
                v = ts.date()
        out[k] = v
    return out


def _bump_sequence(eng, t) -> None:
    """Postgres: rows restored with explicit serial ids leave the sequence behind -
    move it past the highest id or the next insert collides."""
    if not eng.dialect.name.startswith("postgres"):
        return
    from sqlalchemy import Integer, text

    for c in t.primary_key.columns:
        if isinstance(c.type, Integer) and c.autoincrement in (True, "auto"):
            with eng.begin() as conn:
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{t.name}', '{c.name}'), "
                    f"COALESCE((SELECT MAX({c.name}) FROM {t.name}), 0) + 1, false)"))


def restore(path: str | Path, tables: list[str] | None = None,
            replace: bool = False, chunk: int = 5000) -> dict[str, Any]:
    """Load a backup zip. Upserts by primary key; ``replace`` empties each table
    first (a clean copy of the backup)."""
    from .db import bulk_upsert, get_engine, init_db, metadata

    init_db()
    done: dict[str, int] = {}
    eng = get_engine()
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        for name in manifest.get("tables", {}):
            if tables and name not in tables:
                continue
            t = metadata.tables.get(name)
            if t is None or f"{name}.jsonl" not in z.namelist():
                continue
            if replace:
                with eng.begin() as conn:
                    conn.execute(t.delete())
            n, buf = 0, []
            with z.open(f"{name}.jsonl") as fh:
                for line in io.TextIOWrapper(fh, encoding="utf-8"):
                    if not line.strip():
                        continue
                    buf.append(_typed(t, json.loads(line)))
                    if len(buf) >= chunk:
                        n += bulk_upsert(t, buf)
                        buf = []
            if buf:
                n += bulk_upsert(t, buf)
            done[name] = n
            _bump_sequence(eng, t)
    log.info("restore: %d tables, %d rows", len(done), sum(done.values()))
    return {"rows": sum(done.values()), "tables": done}


def backfill(what: str, *, period: str = "10y", tickers: list[str] | None = None) -> dict:
    """Re-pull history a normal run only tops up: ``prices`` (full ``period`` for the
    given or all core names), ``outcomes`` (the catalyst outcome DB with its EDGAR
    topline search), ``institutions`` (8 quarters of specialist-fund 13Fs)."""
    from .store import get_meta, set_meta

    if what == "prices":
        from .ingest import prices
        from .universe import universe_tickers

        tks = tickers or universe_tickers()
        key = f"prices_backfilled_{period}"
        have = set(get_meta(key, []) or [])
        set_meta(key, sorted(have - set(tks)))
        return prices.run(tks, period=period)
    if what == "outcomes":
        from .process import outcomes

        return outcomes.run(backfill=True)
    if what == "institutions":
        from .ingest import institutions

        return institutions.run(time_budget_s=900, keep_periods=8)
    raise ValueError(f"unknown backfill {what!r} - prices, outcomes or institutions")

