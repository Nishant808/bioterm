"""Options-market read per name (yfinance chains) -> ``options_snapshots``.

Three things the options market says before the stock does:
  * implied move - the at-the-money straddle priced as a % of spot: how big a
    move traders are paying for into the front expiry (a binary readout inflates it)
  * put/call volume and open interest - which way the new money leans
  * volume / open interest - fresh positioning rather than old inventory

Bounded to the names that matter (watchlist, top focus, near catalysts) and a
wall-clock budget: each name costs ~3 requests.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from ..config import load_settings
from ..db import bulk_upsert, options_snapshots, read_sql

log = logging.getLogger("bioterm.ingest.options")


def _mid(row: pd.Series) -> float | None:
    bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    if pd.notna(bid) and pd.notna(ask) and bid > 0 and ask > 0:
        return float(bid + ask) / 2
    return float(last) if pd.notna(last) and last > 0 else None


def _atm(chain: pd.DataFrame, spot: float) -> pd.Series | None:
    if chain is None or chain.empty or "strike" not in chain:
        return None
    return chain.iloc[(chain["strike"] - spot).abs().argsort().iloc[0]]


def chain_metrics(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> dict:
    """ATM IV, straddle-implied move and flow ratios for one expiry. Pure."""
    out: dict = {}
    c, p = _atm(calls, spot), _atm(puts, spot)
    ivs = [float(x["impliedVolatility"]) for x in (c, p)
           if x is not None and pd.notna(x.get("impliedVolatility"))
           and float(x["impliedVolatility"]) > 0.01]
    out["atm_iv"] = float(np.mean(ivs)) if ivs else None
    mc, mp = (_mid(c) if c is not None else None), (_mid(p) if p is not None else None)
    out["implied_move"] = (mc + mp) / spot if mc and mp and spot else None

    def tot(df, col):
        return float(pd.to_numeric(df.get(col), errors="coerce").fillna(0).sum()) \
            if df is not None and not df.empty and col in df else 0.0
    out["call_volume"], out["put_volume"] = tot(calls, "volume"), tot(puts, "volume")
    out["call_oi"], out["put_oi"] = tot(calls, "openInterest"), tot(puts, "openInterest")
    return out


def combine(front: dict, back: dict | None) -> dict:
    """Front-expiry snapshot + flow summed over both expiries."""
    back = back or {}
    cv = front["call_volume"] + back.get("call_volume", 0.0)
    pv = front["put_volume"] + back.get("put_volume", 0.0)
    co = front["call_oi"] + back.get("call_oi", 0.0)
    po = front["put_oi"] + back.get("put_oi", 0.0)
    return {
        "atm_iv": front.get("atm_iv"), "iv_back": back.get("atm_iv"),
        "implied_move": front.get("implied_move"),
        "call_volume": cv, "put_volume": pv, "call_oi": co, "put_oi": po,
        "pc_volume_ratio": pv / cv if cv > 0 else None,
        "pc_oi_ratio": po / co if co > 0 else None,
        "vol_oi_ratio": (cv + pv) / (co + po) if (co + po) > 0 else None,
    }


def pick_expiries(expiries: list[str], today: date, min_days: int = 5) -> tuple[str | None, str | None]:
    ds = sorted((pd.to_datetime(e).date(), e) for e in expiries or [])
    front = next(((d, e) for d, e in ds if (d - today).days >= min_days), None)
    if not front:
        return None, None
    back = next((e for d, e in ds if (d - front[0]).days >= 20), None)
    return front[1], back


def target_tickers(max_n: int) -> list[str]:
    from ..store import get_watchlist

    wl = [w["ticker"] for w in get_watchlist()]
    top = read_sql("SELECT ticker FROM scores WHERE asof = (SELECT MAX(asof) FROM scores) "
                   "ORDER BY rank LIMIT 60")
    cats = read_sql("SELECT DISTINCT ticker FROM catalysts WHERE months_away BETWEEN -0.2 AND 3 "
                    "AND type IN ('phase3_readout','pdufa','adcom','fda_action','phase2_readout')")
    ordered = wl + (top["ticker"].tolist() if not top.empty else []) \
        + (cats["ticker"].tolist() if not cats.empty else [])
    return list(dict.fromkeys(ordered))[:max_n]


def run(tickers: list[str] | None = None) -> dict:
    import yfinance as yf

    cfg = load_settings()
    max_n = int(cfg.get("alt_data", "options_max_tickers", default=90))
    budget = float(cfg.get("alt_data", "options_time_budget_s", default=300))
    tickers = tickers or target_tickers(max_n)
    closes = read_sql("SELECT p.ticker, p.close FROM prices p JOIN (SELECT ticker, MAX(date) d "
                      "FROM prices GROUP BY ticker) m ON p.ticker = m.ticker AND p.date = m.d")
    spot_of = dict(zip(closes["ticker"], closes["close"])) if not closes.empty else {}

    today = date.today()
    now = datetime.now(timezone.utc)
    deadline = time.monotonic() + budget
    rows = []
    for tk in tickers:
        if time.monotonic() > deadline:
            log.warning("options: time budget hit after %d names", len(rows))
            break
        spot = spot_of.get(tk)
        if not spot:
            continue
        try:
            t = yf.Ticker(tk)
            front, back = pick_expiries(list(t.options or []), today)
            if not front:
                continue
            fc = t.option_chain(front)
            fm = chain_metrics(fc.calls, fc.puts, float(spot))
            bm = None
            if back:
                bc = t.option_chain(back)
                bm = chain_metrics(bc.calls, bc.puts, float(spot))
        except Exception as exc:  # noqa: BLE001 - one bad chain never stops the run
            log.debug("options failed for %s: %s", tk, exc)
            continue
        fd = pd.to_datetime(front).date()
        rows.append({"ticker": tk, "date": today, "spot": float(spot), "expiry": fd,
                     "days_to_expiry": (fd - today).days, "fetched_at": now,
                     **combine(fm, bm)})
    n = bulk_upsert(options_snapshots, rows)
    log.info("options: %d snapshots (%d targeted)", n, len(tickers))
    return {"rows": n, "targeted": len(tickers)}
