"""Live market data for the dashboard.

Every price the dashboard *shows* comes from here - the ingested ``prices``
table only feeds the engines (technicals, Focus Score, signals, backtest).
Quotes go through ``bioterm.quotes``' failover chain (Yahoo -> Nasdaq ->
Finnhub when a key is stored -> last stored close) and are cached for 60
seconds; daily and intraday histories come from Yahoo with the stored daily
closes as the fallback.

If no provider answers, the helpers say so (``source == "stored"``) - a page
with a labelled end-of-day price beats a page with no chart.
``BIOTERM_LIVE_PRICES=0`` forces that path (tests, offline).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

log = logging.getLogger("bioterm.dashboard.live")

NY = ZoneInfo("America/New_York")
TTL = 60                      # seconds a quote / history stays cached
PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731,
               "5y": 1827}
COLS = ["date", "open", "high", "low", "close", "volume"]


def enabled() -> bool:
    return os.environ.get("BIOTERM_LIVE_PRICES", "1") != "0"


# ---------------------------------------------------------------- market clock
def market_state(now: datetime | None = None) -> tuple[str, str]:
    """(state, label) for the US equity session: open / pre / after / closed,
    NYSE holidays and early closes included."""
    from bioterm.market_calendar import session

    return session(now)


# ---------------------------------------------------------------- parsing (pure)
def _norm_history(raw: pd.DataFrame) -> pd.DataFrame:
    """yfinance OHLCV frame (DatetimeIndex, Title-case columns) -> COLS, naive
    New York timestamps, rows without a close dropped."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLS)
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):          # single-ticker download
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(NY).tz_localize(None)
    df.index = idx
    df = df.reset_index().rename(columns={df.index.name or "index": "date"})
    df = df.rename(columns={"datetime": "date", "Date": "date", "Datetime": "date"})
    for c in COLS:
        if c not in df:
            df[c] = np.nan
    df = df[COLS].dropna(subset=["close"])
    return df.reset_index(drop=True)


def quotes_from_download(raw: pd.DataFrame, tickers: list[str]) -> dict[str, dict]:
    """Batch ``yf.download(period="5d", interval="1d", group_by="ticker")`` ->
    {ticker: {price, prev_close, change, change_pct, asof, source, provider}}."""
    from bioterm.quotes import parse_yahoo_download

    return parse_yahoo_download(raw, tickers)


# ---------------------------------------------------------------- Yahoo (cached)
@st.cache_data(ttl=TTL, show_spinner=False)
def _yf_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False,
                                    actions=False, prepost=False)
    return _norm_history(raw)


@st.cache_data(ttl=TTL, show_spinner=False)
def _live_quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Yahoo -> Nasdaq -> Finnhub (bioterm.quotes), live answers only."""
    from bioterm import quotes as qmod

    return qmod.quotes(list(tickers), allow_stored=False)


@st.cache_data(ttl=TTL, show_spinner=False)
def _yf_closes(tickers: tuple[str, ...], start: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(list(tickers), start=start, interval="1d", group_by="ticker",
                      auto_adjust=False, progress=False, threads=True)
    frames = []
    for t in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            if t not in raw.columns.get_level_values(0):
                continue
            sub = raw[t]
        else:
            sub = raw
        h = _norm_history(sub)
        if not h.empty:
            frames.append(h.assign(ticker=t)[["ticker", "date", "close"]])
    return pd.concat(frames, ignore_index=True) if frames else \
        pd.DataFrame(columns=["ticker", "date", "close"])


# ---------------------------------------------------------------- stored fallback
@st.cache_data(ttl=300, show_spinner=False)
def _stored_history(ticker: str, days: int) -> pd.DataFrame:
    from bioterm.db import read_sql

    cut = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    df = read_sql("SELECT date, open, high, low, close, volume FROM prices "
                  "WHERE ticker = :t AND date >= :c ORDER BY date", {"t": ticker, "c": cut})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df.reindex(columns=COLS)


@st.cache_data(ttl=300, show_spinner=False)
def _stored_quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    from bioterm.db import read_sql

    if not tickers:
        return {}
    ph = ",".join(f":t{i}" for i in range(len(tickers)))
    df = read_sql(f"SELECT ticker, date, close FROM prices WHERE ticker IN ({ph}) "
                  f"AND date >= :c ORDER BY date",
                  {**{f"t{i}": t for i, t in enumerate(tickers)},
                   "c": (pd.Timestamp.today() - pd.Timedelta(days=14)).strftime("%Y-%m-%d")})
    out = {}
    for t, g in df.groupby("ticker"):
        c = pd.to_numeric(g["close"], errors="coerce").dropna()
        if c.empty:
            continue
        price, prev = float(c.iloc[-1]), float(c.iloc[-2]) if len(c) > 1 else np.nan
        out[t] = {"price": price, "prev_close": prev, "change": price - prev,
                  "change_pct": price / prev - 1 if prev == prev and prev else np.nan,
                  "asof": pd.to_datetime(g["date"].iloc[-1]), "source": "stored"}
    return out


# ---------------------------------------------------------------- public API
def history(ticker: str, period: str = "2y", interval: str = "1d") -> tuple[pd.DataFrame, str]:
    """(OHLCV frame, "live" | "stored"). Intraday intervals are live-only."""
    if enabled():
        try:
            df = _yf_history(ticker, period, interval)
            if not df.empty:
                return df, "live"
        except Exception as exc:  # noqa: BLE001 - Yahoo down / throttled
            log.warning("live history failed for %s: %s", ticker, exc)
    if interval != "1d":
        return pd.DataFrame(columns=COLS), "stored"
    return _stored_history(ticker, PERIOD_DAYS.get(period, 731)), "stored"


def quotes(tickers) -> dict[str, dict]:
    """{ticker: quote} for every ticker Yahoo (else the database) knows."""
    tks = tuple(sorted({str(t).upper() for t in tickers if t}))
    if not tks:
        return {}
    got: dict[str, dict] = {}
    if enabled():
        try:
            got = dict(_live_quotes(tks))
        except Exception as exc:  # noqa: BLE001
            log.warning("live quotes failed: %s", exc)
    missing = tuple(t for t in tks if t not in got)
    if missing:
        got = {**_stored_quotes(missing), **got}
    return got


def quote(ticker: str) -> dict | None:
    return quotes([ticker]).get(str(ticker).upper())


def closes(tickers, start: str) -> tuple[pd.DataFrame, str]:
    """Daily closes since ``start`` (ticker, date, close) for equity curves."""
    tks = tuple(sorted({str(t).upper() for t in tickers if t}))
    if not tks:
        return pd.DataFrame(columns=["ticker", "date", "close"]), "live"
    if enabled():
        try:
            df = _yf_closes(tks, start)
            if not df.empty:
                return df, "live"
        except Exception as exc:  # noqa: BLE001
            log.warning("live closes failed: %s", exc)
    from bioterm.db import read_sql

    ph = ",".join(f":t{i}" for i in range(len(tks)))
    df = read_sql(f"SELECT ticker, date, close FROM prices WHERE ticker IN ({ph}) "
                  f"AND date >= :s ORDER BY date",
                  {**{f"t{i}": t for i, t in enumerate(tks)}, "s": start})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df, "stored"


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    """SMA 20/50/200, RSI 14, 20-day volume z-score, 1/3/6-month returns and the
    position in the 52-week range, computed on the live daily history."""
    if df.empty:
        return df.assign(**{c: pd.Series(dtype=float) for c in
                            ("sma20", "sma50", "sma200", "rsi14", "vol_z20", "ret_1m",
                             "ret_3m", "ret_6m", "pct_52w_range")})
    d = df.copy()
    c = d["close"].astype(float)
    for n in (20, 50, 200):
        d[f"sma{n}"] = c.rolling(n, min_periods=n).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    d["rsi14"] = rsi.mask((loss == 0) & (gain > 0), 100.0)     # no down days = 100
    v = d["volume"].astype(float)
    d["vol_z20"] = (v - v.rolling(20).mean()) / v.rolling(20).std()
    for n, k in ((21, "ret_1m"), (63, "ret_3m"), (126, "ret_6m")):
        d[k] = c / c.shift(n) - 1
    hi, lo = c.rolling(252, min_periods=20).max(), c.rolling(252, min_periods=20).min()
    d["pct_52w_range"] = (c - lo) / (hi - lo).replace(0, np.nan)
    return d


PROVIDERS = {"yahoo": "Yahoo Finance", "nasdaq": "Nasdaq", "finnhub": "Finnhub"}


def source_note(source: str, asof=None, provider: str | None = None) -> str:
    """One caption line saying where a price came from."""
    if source == "live":
        _, label = market_state()
        when = f" · {pd.Timestamp(asof):%b %d, %H:%M} ET" if asof is not None and \
            pd.notna(asof) and pd.Timestamp(asof).hour else ""
        return f"Live · {PROVIDERS.get(provider, 'Yahoo Finance')} · {label}{when}"
    return "Live feed unavailable — showing the last stored daily close"
