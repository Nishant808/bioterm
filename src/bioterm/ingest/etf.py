"""Sector flows: XBI creations/redemptions and its quarterly rebalance.

SPDR publishes each ETF's NAV history with shares outstanding:
    https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-xbi.xlsx
    (header: Date, NAV, Shares Outstanding, Total Net Assets)
Daily flow = change in shares outstanding x NAV -> ``etf_flows``.

XBI tracks the S&P Biotechnology Select Industry Index - modified equal weight,
rebalanced quarterly (effective after the close of the third Friday of March,
June, September and December). ``rebalance_pressure`` estimates, from today's
holdings weights, which names sit furthest above or below the equal weight and
how much the fund would trade to reset them, in days of each name's volume - an
approximation (the index also applies liquidity caps), not the index's own
rebalance file.
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

log = logging.getLogger("bioterm.ingest.etf")

NAVHIST = ("https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/"
           "etfs/us/navhist-us-en-{t}.xlsx")


def parse_navhist(raw: bytes) -> pd.DataFrame:
    xls = pd.read_excel(io.BytesIO(raw), header=None)
    hdr = next(i for i in range(min(20, len(xls)))
               if "shares outstanding" in " ".join(str(x).lower() for x in xls.iloc[i]))
    df = pd.read_excel(io.BytesIO(raw), header=hdr)
    df.columns = [str(c).strip().lower() for c in df.columns]
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"], errors="coerce", format="mixed"),
        "nav": pd.to_numeric(df["nav"], errors="coerce"),
        "shares_out": pd.to_numeric(df["shares outstanding"], errors="coerce"),
        "aum": pd.to_numeric(df[next(c for c in df.columns if "net assets" in c)],
                             errors="coerce")}).dropna(subset=["date", "nav", "shares_out"])
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    out["flow_est"] = out["shares_out"].diff() * out["nav"]
    return out.reset_index(drop=True)


def run(tickers: tuple[str, ...] = ("xbi",), days: int = 400) -> dict[str, Any]:
    from ..db import bulk_upsert, etf_flows
    from ..httpx_util import get_bytes

    now = datetime.now(timezone.utc)
    n = 0
    for t in tickers:
        raw = get_bytes(NAVHIST.format(t=t.lower()), min_interval=1.0, retries=2, timeout=60)
        df = parse_navhist(raw)
        df = df[df["date"] >= pd.Timestamp(date.today() - timedelta(days=days))]
        n += bulk_upsert(etf_flows, [{"etf": t.upper(), "date": r.date.date(), "nav": r.nav,
                                      "shares_out": r.shares_out, "aum": r.aum,
                                      "flow_est": None if pd.isna(r.flow_est) else r.flow_est,
                                      "fetched_at": now} for r in df.itertuples()])
    return {"rows": n}


def next_rebalance(today: date | None = None) -> date:
    """Third Friday of the next March / June / September / December."""
    today = today or date.today()
    for y in (today.year, today.year + 1):
        for m in (3, 6, 9, 12):
            d = date(y, m, 15)
            d += timedelta(days=(4 - d.weekday()) % 7)
            if d >= today:
                return d
    raise AssertionError("unreachable")


def rebalance_pressure(limit: int = 15) -> pd.DataFrame:
    """Names furthest from XBI's equal weight, with the implied trade in days of
    volume (positive = the fund buys)."""
    from ..db import read_sql

    w = read_sql("SELECT ticker, etf_weight FROM securities WHERE in_xbi = 1 "
                 "AND etf_weight IS NOT NULL")
    if w.empty:
        return pd.DataFrame()
    aum = read_sql("SELECT aum FROM etf_flows WHERE etf = 'XBI' ORDER BY date DESC LIMIT 1")
    if aum.empty or pd.isna(aum.iloc[0]["aum"]):
        return pd.DataFrame()
    total = float(aum.iloc[0]["aum"])
    wt = pd.to_numeric(w["etf_weight"], errors="coerce")
    wt = wt / (100.0 if wt.sum() > 1.5 else 1.0)            # SSGA publishes percent
    target = 1.0 / len(w)
    px = read_sql("SELECT ticker, close, volume FROM prices WHERE date >= :c",
                  {"c": (date.today() - timedelta(days=40)).isoformat()})
    adv = (px.assign(dv=pd.to_numeric(px["close"], errors="coerce")
                     * pd.to_numeric(px["volume"], errors="coerce"))
           .groupby("ticker")["dv"].mean()) if not px.empty else pd.Series(dtype=float)
    df = w.assign(weight=wt.values, target=target)
    df["trade_usd"] = (df["target"] - df["weight"]) * total
    df["days_of_volume"] = df["trade_usd"] / df["ticker"].map(adv)
    df["drift"] = df["weight"] / target - 1
    return df.reindex(df["days_of_volume"].abs().sort_values(ascending=False).index).head(limit)
