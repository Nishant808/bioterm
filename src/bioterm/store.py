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
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from .config import load_settings
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
