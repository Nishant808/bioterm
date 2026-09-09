"""Fundamentals ingestion: yfinance key stats + SEC XBRL facts -> ``fundamentals``.

The number that matters most for pre-revenue biotech is **cash runway**:
how many quarters of cash are left at the current burn rate. Short runway = the
company must raise (dilution) before its next catalyst, which caps upside.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from ..config import load_settings
from ..db import bulk_upsert, fundamentals
from ..universe import universe_tickers
from . import edgar

log = logging.getLogger("bioterm.ingest.fundamentals")


def _yf_stats(ticker: str) -> dict:
    out: dict = {}
    tk = yf.Ticker(ticker)
    try:
        fi = tk.fast_info
        out["market_cap"] = _num(getattr(fi, "market_cap", None))
        out["shares_out"] = _num(getattr(fi, "shares", None))
    except Exception:  # noqa: BLE001
        pass
    try:
        info = tk.info or {}
        out["market_cap"] = out.get("market_cap") or _num(info.get("marketCap"))
        out["shares_out"] = out.get("shares_out") or _num(info.get("sharesOutstanding"))
        out["float_shares"] = _num(info.get("floatShares"))
        out["short_percent_float"] = _num(info.get("shortPercentOfFloat"))
        # yfinance sometimes carries these directly
        out["cash_yf"] = _num(info.get("totalCash"))
    except Exception:  # noqa: BLE001
        pass
    try:
        cal = tk.calendar
        ed = None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, (list, tuple)) and ed:
                ed = ed[0]
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            ed = cal.loc["Earnings Date"].iloc[0]
        out["next_earnings_date"] = pd.to_datetime(ed, errors="coerce").date() if ed is not None else None
    except Exception:  # noqa: BLE001
        out["next_earnings_date"] = None
    return out


def _runway(cash: float | None, burn_ttm: float | None) -> float | None:
    if not cash or not burn_ttm or burn_ttm <= 0:
        return None
    return round(cash / (burn_ttm / 4.0), 1)


def run(tickers: list[str] | None = None) -> dict:
    cfg = load_settings()
    tickers = tickers or universe_tickers()
    cmap = edgar.ticker_cik_map()
    now = datetime.now(timezone.utc)
    rows: list[dict] = []

    for tk in tickers:
        stats = _yf_stats(tk)
        facts = {}
        cik = cmap.get(tk.upper())
        if cik:
            facts = edgar.company_facts(cik)

        cash = facts.get("cash") or stats.get("cash_yf")
        # Conservative annual burn = the most-negative of (operating cash flow, net income), as a positive number.
        ocf = facts.get("op_cash_flow_ttm")
        ni = facts.get("net_income_ttm")
        burn_candidates = [x for x in (ocf, ni) if x is not None and x < 0]
        burn_ttm = -min(burn_candidates) if burn_candidates else None

        rows.append(
            {
                "ticker": tk,
                "market_cap": stats.get("market_cap"),
                "shares_out": stats.get("shares_out"),
                "float_shares": stats.get("float_shares"),
                "short_percent_float": stats.get("short_percent_float"),
                "cash": cash,
                "rd_expense_ttm": facts.get("rd_expense_ttm"),
                "net_income_ttm": ni,
                "op_cash_flow_ttm": ocf,
                "burn_ttm": burn_ttm,
                "runway_quarters": _runway(cash, burn_ttm),
                "next_earnings_date": stats.get("next_earnings_date"),
                "sources": "yfinance+edgar" if cik else "yfinance",
                "updated_at": now,
            }
        )

    n = bulk_upsert(fundamentals, rows)
    with_runway = sum(1 for r in rows if r["runway_quarters"] is not None)
    log.info("fundamentals: %d rows (%d with cash runway)", n, with_runway)
    return {"rows": n, "with_runway": with_runway}


def _num(v) -> float | None:
    try:
        v = float(v)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None
