"""Point-in-time snapshots: fundamentals (cap, cash, runway, short interest,
ownership), the catalyst calendar and universe membership as they stood each day.

The live tables are overwritten in place, so without these a backtest of a
non-price signal (a runway screen, a catalyst setup, a short-interest build) would
use today's numbers for every past date. Membership keeps the names that later leave
XBI - delisted, acquired, shrunk out - against survivorship bias.

Storage stays small (Neon's free plan is 512 MB): fundamentals are kept daily for
core names only; catalysts and membership are stored as *changes* - a catalyst row
when it first appears or changes (a ``removed`` tombstone when it drops off), a
membership snapshot when the set changes or a week has passed. ``catalysts_known_on``
and ``members_on`` rebuild the state on any past day.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from ..db import (bulk_upsert, catalyst_snapshots, fundamental_snapshots, read_sql,
                  universe_snapshots)

log = logging.getLogger("bioterm.process.snapshots")

FUND_COLS = ["market_cap", "cash", "runway_quarters", "short_percent_float", "short_ratio",
             "held_pct_institutions"]
CAT_KEYS = ("ticker", "type", "date", "confidence", "source")


def _day(v) -> date | None:
    d = pd.to_datetime(v, errors="coerce")
    return d.date() if pd.notna(d) else None


def catalysts_known_on(day: date) -> pd.DataFrame:
    """The catalyst calendar as BioTerm knew it at the end of ``day``."""
    df = read_sql("SELECT asof, id, ticker, type, date, confidence, source FROM "
                  "catalyst_snapshots WHERE asof <= :d", {"d": day.isoformat()})
    if df.empty:
        return df
    df["asof"] = pd.to_datetime(df["asof"])
    last = df.sort_values("asof").groupby("id").tail(1)
    return last[last["confidence"] != "removed"].drop(columns="asof").reset_index(drop=True)


def catalyst_changes(current: list[dict], known: pd.DataFrame, asof: date) -> list[dict]:
    """Pure: rows to write so the snapshot table reflects ``current`` - new or changed
    catalysts, plus a ``removed`` tombstone for each one that disappeared."""
    prev = {r["id"]: r for r in known.to_dict("records")} if not known.empty else {}
    out = []
    now_ids = set()
    for r in current:
        now_ids.add(r["id"])
        row = {"asof": asof, "id": r["id"], **{k: r.get(k) for k in CAT_KEYS}}
        row["date"] = _day(row["date"])
        p = prev.get(r["id"])
        if p is None or any(str(_day(p.get(k)) if k == "date" else p.get(k))
                            != str(row[k]) for k in CAT_KEYS):
            out.append(row)
    for cid, p in prev.items():
        if cid not in now_ids:
            out.append({"asof": asof, "id": cid, "ticker": p.get("ticker"),
                        "type": p.get("type"), "date": _day(p.get("date")),
                        "confidence": "removed", "source": p.get("source")})
    return out


def members_on(day: date) -> set[str]:
    """Universe members (core + extended) as of ``day`` - the latest snapshot on or
    before it."""
    df = read_sql("SELECT ticker FROM universe_snapshots WHERE asof = (SELECT MAX(asof) "
                  "FROM universe_snapshots WHERE asof <= :d)", {"d": day.isoformat()})
    return set(df["ticker"]) if not df.empty else set()


def run(asof: date | None = None) -> dict:
    asof = asof or date.today()
    # fundamentals - core names, daily
    f = read_sql("SELECT f.ticker, " + ", ".join(f"f.{c}" for c in FUND_COLS)
                 + " FROM fundamentals f JOIN securities s ON s.ticker = f.ticker "
                 "WHERE s.tier IS NULL OR s.tier = 'core'")
    n_f = bulk_upsert(fundamental_snapshots,
                      [{"asof": asof, **r} for r in f.to_dict("records")]) if not f.empty else 0
    # catalysts - changes only
    cur = read_sql("SELECT id, ticker, type, date, confidence, source FROM catalysts")
    known = catalysts_known_on(asof)
    changes = catalyst_changes(cur.to_dict("records") if not cur.empty else [], known, asof)
    n_c = bulk_upsert(catalyst_snapshots, changes)
    # membership - when it changes, or weekly
    u = read_sql("SELECT ticker, in_xbi, in_ibb, tier FROM securities "
                 "WHERE tier IS NULL OR tier IN ('core', 'extended')")
    rows = [{"asof": asof, "ticker": r["ticker"], "in_xbi": int(r["in_xbi"] or 0),
             "in_ibb": int(r["in_ibb"] or 0), "tier": r["tier"] or "core"}
            for r in (u.to_dict("records") if not u.empty else [])]
    last = read_sql("SELECT asof, ticker, in_xbi, tier FROM universe_snapshots WHERE asof = "
                    "(SELECT MAX(asof) FROM universe_snapshots)")
    same = False
    if not last.empty:
        prev = {(t, int(x or 0), str(tr)) for t, x, tr in
                zip(last["ticker"], last["in_xbi"], last["tier"])}
        now = {(r["ticker"], r["in_xbi"], r["tier"]) for r in rows}
        age = (asof - _day(last["asof"].iloc[0])).days if _day(last["asof"].iloc[0]) else 99
        same = prev == now and age < 7
    n_u = 0 if same or not rows else bulk_upsert(universe_snapshots, rows)
    log.info("snapshots %s: %d fundamentals, %d catalyst changes, %d members", asof, n_f,
             n_c, n_u)
    return {"rows": n_f + n_c + n_u, "fundamentals": n_f, "catalyst_changes": n_c,
            "universe": n_u}


def history(ticker: str, days: int = 400) -> pd.DataFrame:
    """One name's daily fundamentals snapshots (short interest, cap, cash...)."""
    df = read_sql("SELECT asof, " + ", ".join(FUND_COLS) + " FROM fundamental_snapshots "
                  "WHERE ticker = :t AND asof >= :a ORDER BY asof",
                  {"t": ticker.upper(), "a": (date.today() - timedelta(days=days)).isoformat()})
    if not df.empty:
        df["asof"] = pd.to_datetime(df["asof"])
    return df
