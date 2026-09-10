"""DB-backed user state: watchlist, manual catalysts, per-ticker notes, app meta.

The YAML files under ``config/`` are *seeds*. On first run each table is populated
from its YAML file; after that the database is authoritative. This is what lets the
Streamlit Cloud dashboard persist edits (its filesystem is ephemeral, and the
GitHub Actions ingest runner is a separate checkout).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from .config import load_settings
from .db import pf_portfolios, pf_trades  # noqa: F401  (used below)
from .db import (app_meta, bulk_upsert, get_engine, manual_catalysts, notes,
                 read_sql, watchlist)

log = logging.getLogger("bioterm.store")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mk_cat_id(ticker: str, ctype: str, d: str, title: str) -> str:
    return hashlib.sha1(f"{ticker}|{ctype}|{d}|{title[:60]}".encode()).hexdigest()[:48]


# ------------------------------------------------------------------ watchlist
def get_watchlist() -> list[dict[str, Any]]:
    """Return the watchlist as a list of dicts (DB first, YAML fallback)."""
    try:
        df = read_sql("SELECT * FROM watchlist ORDER BY conviction DESC, ticker")
    except Exception:  # table missing / DB down
        df = pd.DataFrame()
    if df.empty:
        return [dict(w) for w in load_settings().watchlist]
    out = []
    for _, r in df.iterrows():
        mols = r.get("molecules")
        try:
            mols = json.loads(mols) if mols else []
        except (TypeError, ValueError):
            mols = []
        out.append({
            "ticker": r["ticker"],
            "conviction": int(r["conviction"]) if pd.notna(r["conviction"]) else 3,
            "thesis": r.get("thesis") or "",
            "molecules": mols,
        })
    return out


def save_watchlist(entries: list[dict[str, Any]]) -> int:
    """Replace the whole watchlist. ``entries`` = [{ticker, conviction, thesis, molecules}]."""
    engine = get_engine()
    now = _now()
    rows = []
    for e in entries:
        tk = str(e.get("ticker", "")).strip().upper()
        if not tk:
            continue
        mols = e.get("molecules") or []
        if isinstance(mols, str):
            mols = [m.strip() for m in mols.split(",") if m.strip()]
        rows.append({
            "ticker": tk,
            "conviction": int(e.get("conviction", 3) or 3),
            "thesis": (e.get("thesis") or "").strip() or None,
            "molecules": json.dumps(mols) if mols else None,
            "added_at": now,
            "updated_at": now,
        })
    keep = {r["ticker"] for r in rows}
    with engine.begin() as conn:
        existing = read_sql("SELECT ticker FROM watchlist")
        drop = [t for t in existing["ticker"].tolist() if t not in keep] if not existing.empty else []
        if drop:
            conn.execute(watchlist.delete().where(watchlist.c.ticker.in_(drop)))
    bulk_upsert(watchlist, rows, update_only=["conviction", "thesis", "molecules", "updated_at"])
    return len(rows)


def add_to_watchlist(ticker: str, conviction: int = 3, thesis: str = "") -> None:
    wl = {w["ticker"].upper(): w for w in get_watchlist()}
    ticker = ticker.upper()
    if ticker in wl:
        wl[ticker]["conviction"] = conviction
        if thesis:
            wl[ticker]["thesis"] = thesis
    else:
        wl[ticker] = {"ticker": ticker, "conviction": conviction,
                      "thesis": thesis, "molecules": []}
    save_watchlist(list(wl.values()))


def remove_from_watchlist(ticker: str) -> None:
    wl = [w for w in get_watchlist() if w["ticker"].upper() != ticker.upper()]
    save_watchlist(wl)


def watchlist_conviction(ticker: str) -> int | None:
    for w in get_watchlist():
        if w["ticker"].upper() == ticker.upper():
            return int(w.get("conviction", 3))
    return None


# ------------------------------------------------------------------ manual catalysts
def get_manual_catalysts() -> list[dict[str, Any]]:
    try:
        df = read_sql("SELECT * FROM manual_catalysts ORDER BY date")
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        return [dict(c) for c in load_settings().manual_catalysts]
    return df.to_dict("records")


def add_manual_catalyst(ticker: str, ctype: str, d: date | str, title: str,
                        confidence: str = "medium", url: str = "") -> str:
    d = str(d)
    cid = _mk_cat_id(ticker.upper(), ctype, d, title)
    bulk_upsert(manual_catalysts, [{
        "id": cid, "ticker": ticker.upper(), "type": ctype,
        "date": pd.to_datetime(d, errors="coerce").date(),
        "title": title.strip(), "confidence": confidence,
        "url": url.strip(), "created_at": _now(),
    }])
    return cid


def delete_manual_catalyst(cid: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(manual_catalysts.delete().where(manual_catalysts.c.id == cid))


# ------------------------------------------------------------------ notes
def get_note(ticker: str) -> str:
    try:
        df = read_sql("SELECT body FROM notes WHERE ticker = :t", {"t": ticker.upper()})
    except Exception:
        return ""
    return "" if df.empty else (df.iloc[0]["body"] or "")


def set_note(ticker: str, body: str) -> None:
    bulk_upsert(notes, [{"ticker": ticker.upper(), "body": body,
                         "updated_at": _now()}])


def all_notes() -> dict[str, str]:
    try:
        df = read_sql("SELECT ticker, body FROM notes")
    except Exception:
        return {}
    return dict(zip(df["ticker"], df["body"])) if not df.empty else {}


# ------------------------------------------------------------------ app meta
def get_meta(key: str, default: Any = None) -> Any:
    try:
        df = read_sql("SELECT value FROM app_meta WHERE key = :k", {"k": key})
    except Exception:
        return default
    if df.empty:
        return default
    try:
        return json.loads(df.iloc[0]["value"])
    except (TypeError, ValueError):
        return default


def set_meta(key: str, value: Any) -> None:
    bulk_upsert(app_meta, [{"key": key, "value": json.dumps(value, default=str),
                            "updated_at": _now()}])


# ------------------------------------------------------------------ paper trading
def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:28]
    return s or "portfolio"


def pf_list() -> list[dict[str, Any]]:
    try:
        df = read_sql("SELECT * FROM pf_portfolios ORDER BY created_at")
    except Exception:  # noqa: BLE001
        df = pd.DataFrame()
    return df.to_dict("records") if not df.empty else []


def pf_ensure_default() -> str:
    if not pf_list():
        return pf_create("Strategy A", 100_000.0)
    return pf_list()[0]["id"]


def pf_create(name: str, cash_start: float = 100_000.0) -> str:
    pid = _slug(name)
    existing = {p["id"] for p in pf_list()}
    n, base = pid, pid
    i = 2
    while n in existing:
        n = f"{base}-{i}"
        i += 1
    bulk_upsert(pf_portfolios, [{"id": n, "name": name.strip() or n,
                                 "cash_start": float(cash_start),
                                 "created_at": _now()}])
    return n


def pf_delete(pid: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(pf_trades.delete().where(pf_trades.c.portfolio_id == pid))
        conn.execute(pf_portfolios.delete().where(pf_portfolios.c.id == pid))


def pf_reset(pid: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(pf_trades.delete().where(pf_trades.c.portfolio_id == pid))


def pf_get_trades(pid: str) -> pd.DataFrame:
    try:
        return read_sql("SELECT * FROM pf_trades WHERE portfolio_id = :p ORDER BY ts, id",
                        {"p": pid})
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def pf_add_trade(pid: str, ticker: str, side: str, qty: float, price: float,
                 fees: float = 0.0, note: str = "", ts: datetime | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(pf_trades.insert(), [{
            "portfolio_id": pid, "ts": ts or _now(),
            "ticker": ticker.strip().upper(), "side": side.upper(),
            "qty": float(qty), "price": float(price), "fees": float(fees or 0.0),
            "note": (note or "").strip(),
        }])


def pf_delete_trade(trade_id: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(pf_trades.delete().where(pf_trades.c.id == int(trade_id)))


# ------------------------------------------------------------------ seeding
def seed_from_yaml(force: bool = False) -> dict:
    """Populate the user-state tables from config/*.yml if they are empty."""
    cfg = load_settings()
    out = {}

    wl_existing = read_sql("SELECT COUNT(*) c FROM watchlist").iloc[0]["c"]
    if force or wl_existing == 0:
        entries = [{"ticker": w["ticker"], "conviction": w.get("conviction", 3),
                    "thesis": w.get("thesis", ""), "molecules": w.get("molecules", [])}
                   for w in cfg.watchlist]
        out["watchlist_seeded"] = save_watchlist(entries) if entries else 0

    mc_existing = read_sql("SELECT COUNT(*) c FROM manual_catalysts").iloc[0]["c"]
    if (force or mc_existing == 0) and cfg.manual_catalysts:
        n = 0
        for c in cfg.manual_catalysts:
            if c.get("ticker") and c.get("date"):
                add_manual_catalyst(c["ticker"], c.get("type", "other"), c["date"],
                                    c.get("title", ""), c.get("confidence", "medium"),
                                    c.get("url", ""))
                n += 1
        out["manual_catalysts_seeded"] = n

    return out
