"""Technical indicators computed in-house from the ``prices`` table -> ``technicals``.

Only the ~10 indicators the 6-month swing model needs. Pure pandas/numpy so there
is no third-party indicator library to break on Python upgrades.
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from ..db import bulk_upsert, read_sql, technicals

log = logging.getLogger("bioterm.process.technicals")


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(avg_loss != 0, 100.0)              # no losses -> RSI 100
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)  # flat -> 50
    return out.fillna(50.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift()
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _indicators_for(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    out = pd.DataFrame({"date": df["date"], "close": close})
    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma200"] = close.rolling(200).mean()
    out["rsi14"] = rsi(close)
    line, sig, hist = macd(close)
    out["macd"], out["macd_signal"], out["macd_hist"] = line, sig, hist
    out["atr14"] = atr(df)
    mid = close.rolling(20).mean()
    sd = close.rolling(20).std()
    out["bb_upper"] = mid + 2 * sd
    out["bb_lower"] = mid - 2 * sd
    vol = df["volume"].astype(float)
    vmean = vol.rolling(20).mean()
    vstd = vol.rolling(20).std().replace(0.0, np.nan)
    out["vol_z20"] = ((vol - vmean) / vstd).fillna(0.0)
    roll_max = close.rolling(252, min_periods=30).max()
    roll_min = close.rolling(252, min_periods=30).min()
    rng = (roll_max - roll_min).replace(0.0, np.nan)
    out["pct_52w_range"] = ((close - roll_min) / rng).clip(0, 1)
    out["ret_1m"] = close.pct_change(21)
    out["ret_3m"] = close.pct_change(63)
    out["ret_6m"] = close.pct_change(126)
    return out


def run(tickers: list[str] | None = None, keep_rows: int = 400) -> dict:
    where = ""
    params = None
    if tickers:
        placeholders = ",".join(f":t{i}" for i in range(len(tickers)))
        where = f"WHERE ticker IN ({placeholders})"
        params = {f"t{i}": t for i, t in enumerate(tickers)}
    prices_df = read_sql(f"SELECT * FROM prices {where}", params)
    if prices_df.empty:
        log.warning("no prices to process")
        return {"rows": 0, "tickers": 0}

    prices_df["date"] = pd.to_datetime(prices_df["date"])
    total = 0
    n_tickers = 0

    for tk, grp in prices_df.groupby("ticker"):
        if len(grp) < 30:
            continue
        ind = _indicators_for(grp).tail(keep_rows)
        if ind.empty:
            continue
        rows = []
        for _, r in ind.iterrows():
            row = {"ticker": tk, "date": r["date"].date()}
            for col in ind.columns:
                if col == "date":
                    continue
                val = r[col]
                row[col] = None if pd.isna(val) else float(val)
            rows.append(row)
        total += bulk_upsert(technicals, rows)
        n_tickers += 1

    log.info("technicals: %d rows across %d tickers", total, n_tickers)
    return {"rows": total, "tickers": n_tickers}


def latest_technicals() -> pd.DataFrame:
    """Most recent technicals row per ticker."""
    df = read_sql("SELECT * FROM technicals")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").groupby("ticker", as_index=False).last()
