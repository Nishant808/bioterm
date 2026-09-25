"""Live quotes with failover: Yahoo Finance -> Nasdaq -> Finnhub -> stored close.

Used by the dashboard (through ``dashboard/_live.py``, which adds Streamlit
caching), the pulse job (movers, "why it moved") and the Copilot. A quote is

    {price, prev_close, change, change_pct, asof, source, provider}

``source`` is "live" when a market-data provider answered and "stored" when it is
the last daily close from the ``prices`` table; ``provider`` names who answered
(yahoo / nasdaq / finnhub / db). ``asof`` is a naive New York timestamp.

Yahoo is asked first for the whole batch (one request). Names it doesn't return
go to Nasdaq's public quote API one by one, then to Finnhub when a key is stored
(Settings -> Data providers), and finally to the database. Every provider is
fail-soft and each host has its own circuit breaker, so a dead provider costs a
few seconds once, not on every page load.
"""
from __future__ import annotations

import logging
import math
import os
import re
import time
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

log = logging.getLogger("bioterm.quotes")

NY = ZoneInfo("America/New_York")
TTL = 60.0
_CACHE: dict[str, tuple[float, dict]] = {}
MAX_PER_TICKER_FALLBACK = 40      # per-name providers are slow - cap a batch
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def enabled() -> bool:
    return os.environ.get("BIOTERM_LIVE_PRICES", "1") != "0"


def _q(price, prev, asof, provider: str, source: str = "live") -> dict | None:
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    try:
        prev = float(prev)
    except (TypeError, ValueError):
        prev = float("nan")
    ok_prev = math.isfinite(prev) and prev > 0
    return {"price": price, "prev_close": prev if ok_prev else np.nan,
            "change": price - prev if ok_prev else np.nan,
            "change_pct": price / prev - 1 if ok_prev else np.nan,
            "asof": asof, "source": source, "provider": provider}


# ---------------------------------------------------------------- parsers (pure)
def parse_yahoo_download(raw: pd.DataFrame, tickers: list[str]) -> dict[str, dict]:
    """``yf.download(period="5d", interval="1d", group_by="ticker")`` -> quotes.
    Today's daily bar is live during the session, so its close is the last trade."""
    out: dict[str, dict] = {}
    if raw is None or raw.empty:
        return out
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        if multi:
            if t not in raw.columns.get_level_values(0):
                continue
            sub = raw[t]
        elif len(tickers) == 1:
            sub = raw
        else:
            continue
        sub = sub.rename(columns=str.lower)
        if "close" not in sub:
            continue
        c = pd.to_numeric(sub["close"], errors="coerce").dropna()
        if c.empty:
            continue
        ts = pd.Timestamp(c.index[-1])
        asof = ts.tz_convert(NY).tz_localize(None) if ts.tzinfo else ts
        q = _q(c.iloc[-1], c.iloc[-2] if len(c) > 1 else None, asof, "yahoo")
        if q:
            out[t] = q
    return out


_NUM = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _money(s) -> float | None:
    m = _NUM.search(str(s or "").replace("$", ""))
    return float(m.group(0).replace(",", "")) if m else None


def parse_nasdaq_quote(payload: dict) -> dict | None:
    """api.nasdaq.com/api/quote/{SYM}/info -> quote. ``primaryData`` is the
    latest trade (pre-/after-market included) with its change vs the previous
    close."""
    data = (payload or {}).get("data") or {}
    pd_ = data.get("primaryData") or {}
    price = _money(pd_.get("lastSalePrice"))
    chg = _money(pd_.get("netChange"))
    if price is None:
        return None
    prev = price - chg if chg is not None else None
    asof = None
    ts = str(pd_.get("lastTradeTimestamp") or "")
    m = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M)", ts)
    if m:
        try:
            asof = datetime.strptime(m.group(1), "%b %d, %Y %I:%M %p")
        except ValueError:
            asof = None
    return _q(price, prev, pd.Timestamp(asof) if asof else pd.Timestamp.now(NY)
              .tz_localize(None), "nasdaq")


def parse_finnhub_quote(payload: dict) -> dict | None:
    """finnhub.io/api/v1/quote -> quote ({c, d, dp, h, l, o, pc, t})."""
    if not isinstance(payload, dict) or not payload.get("c"):
        return None
    t = payload.get("t")
    asof = (pd.Timestamp(int(t), unit="s", tz="UTC").tz_convert(NY).tz_localize(None)
            if t else pd.Timestamp.now(NY).tz_localize(None))
    return _q(payload.get("c"), payload.get("pc"), asof, "finnhub")


# ---------------------------------------------------------------- providers
def _yahoo(tickers: list[str]) -> dict[str, dict]:
    import yfinance as yf

    raw = yf.download(tickers, period="5d", interval="1d", group_by="ticker",
                      auto_adjust=False, progress=False, threads=True)
    return parse_yahoo_download(raw, tickers)


def _nasdaq(ticker: str) -> dict | None:
    from .httpx_util import get_json

    sym = ticker.replace("-", ".").upper()
    payload = get_json(f"https://api.nasdaq.com/api/quote/{sym}/info",
                       {"assetclass": "stocks"}, headers=_BROWSER_HEADERS,
                       min_interval=0.15, retries=1, timeout=6)
    return parse_nasdaq_quote(payload)


def _finnhub(ticker: str, key: str) -> dict | None:
    from .httpx_util import get_json

    payload = get_json("https://finnhub.io/api/v1/quote",
                       {"symbol": ticker.upper(), "token": key},
                       min_interval=1.05, retries=1, timeout=6)   # free tier: 60/min
    return parse_finnhub_quote(payload)


def stored(tickers: Iterable[str]) -> dict[str, dict]:
    """Last two stored daily closes per ticker (the offline fallback)."""
    from .db import read_sql

    tks = sorted({str(t).upper() for t in tickers if t})
    if not tks:
        return {}
    ph = ",".join(f":t{i}" for i in range(len(tks)))
    cut = (pd.Timestamp.today() - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    try:
        df = read_sql(f"SELECT ticker, date, close FROM prices WHERE ticker IN ({ph}) "
                      f"AND date >= :c ORDER BY date",
                      {**{f"t{i}": t for i, t in enumerate(tks)}, "c": cut})
    except Exception as exc:  # noqa: BLE001
        log.warning("stored quotes failed: %s", exc)
        return {}
    out = {}
    for t, g in df.groupby("ticker"):
        c = pd.to_numeric(g["close"], errors="coerce").dropna()
        if c.empty:
            continue
        q = _q(c.iloc[-1], c.iloc[-2] if len(c) > 1 else None,
               pd.to_datetime(g["date"].iloc[-1]), "db", source="stored")
        if q:
            out[t] = q
    return out


# ---------------------------------------------------------------- public API
def quotes(tickers: Iterable[str], *, allow_stored: bool = True,
           fallback_cap: int = MAX_PER_TICKER_FALLBACK) -> dict[str, dict]:
    """{TICKER: quote} through the failover chain, cached for ``TTL`` seconds."""
    tks = sorted({str(t).upper().strip() for t in tickers if t and str(t).strip()})
    if not tks:
        return {}
    now = time.monotonic()
    got: dict[str, dict] = {t: q for t in tks
                            if (hit := _CACHE.get(t)) and now - hit[0] < TTL
                            for q in [hit[1]]}
    if enabled():
        need = [t for t in tks if t not in got]
        if need:
            try:
                got.update(_yahoo(need))
            except Exception as exc:  # noqa: BLE001 - Yahoo down / throttled
                log.warning("yahoo quotes failed: %s", exc)
        need = [t for t in tks if t not in got][:fallback_cap]
        for t in need:
            try:
                q = _nasdaq(t)
            except Exception as exc:  # noqa: BLE001
                log.info("nasdaq quote %s failed: %s", t, exc)
                q = None
            if q:
                got[t] = q
        from . import vault

        key = vault.get("FINNHUB_API_KEY")
        if key:
            for t in [t for t in tks if t not in got][:fallback_cap]:
                try:
                    q = _finnhub(t, key)
                except Exception as exc:  # noqa: BLE001
                    log.info("finnhub quote %s failed: %s", t, exc)
                    q = None
                if q:
                    got[t] = q
        stamp = time.monotonic()
        for t, q in got.items():
            if q.get("source") == "live":
                _CACHE[t] = (stamp, q)
    missing = [t for t in tks if t not in got]
    if missing and allow_stored:
        got.update(stored(missing))
    return got


def quote(ticker: str) -> dict | None:
    return quotes([ticker]).get(str(ticker).upper())


def clear_cache() -> None:
    _CACHE.clear()


def movers(universe: Iterable[str], *, min_abs_pct: float = 0.08,
           limit: int = 25) -> list[dict[str, Any]]:
    """Live quotes of the universe, biggest absolute % moves first (live only)."""
    q = quotes(universe, allow_stored=False, fallback_cap=0)
    rows = [{"ticker": t, **v} for t, v in q.items()
            if v.get("source") == "live" and v.get("change_pct") == v.get("change_pct")
            and abs(v["change_pct"]) >= min_abs_pct]
    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return rows[:limit]
