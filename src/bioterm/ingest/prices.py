"""Price ingestion via yfinance -> ``prices`` table (daily OHLCV)."""
from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from ..config import load_settings
from ..db import bulk_upsert, prices
from ..universe import universe_tickers

log = logging.getLogger("bioterm.ingest.prices")


def _download(tickers: list[str], period: str) -> pd.DataFrame:
    data = yf.download(
        tickers=" ".join(tickers),
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        threads=True,
        progress=False,
    )
    return data


def run(tickers: list[str] | None = None) -> dict:
    cfg = load_settings()
    period = cfg.get("price_history_period", default="2y")
    tickers = tickers or universe_tickers()
    total = 0
    failed: list[str] = []

    # batch to keep memory/URL length sane on a 16 GB machine
    batch_size = 60
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        try:
            data = _download(batch, period)
        except Exception as exc:  # noqa: BLE001
            log.warning("batch download failed %s: %s", batch[:3], exc)
            failed.extend(batch)
            continue

        for tk in batch:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if tk not in data.columns.get_level_values(0):
                        failed.append(tk)
                        continue
                    df = data[tk].copy()
                else:  # single ticker in batch
                    df = data.copy()
                df = df.dropna(how="all")
                if df.empty:
                    failed.append(tk)
                    continue
                df = df.reset_index()
                df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
                rows = [
                    {
                        "ticker": tk,
                        "date": pd.to_datetime(r["date"]).date(),
                        "open": _f(r.get("open")),
                        "high": _f(r.get("high")),
                        "low": _f(r.get("low")),
                        "close": _f(r.get("close")),
                        "adj_close": _f(r.get("adj_close", r.get("close"))),
                        "volume": _f(r.get("volume")),
                    }
                    for _, r in df.iterrows()
                ]
                total += bulk_upsert(prices, rows)
            except Exception as exc:  # noqa: BLE001
                log.warning("parse failed for %s: %s", tk, exc)
                failed.append(tk)

    log.info("prices: upserted %d rows, %d tickers failed", total, len(failed))
    return {"rows": total, "failed": failed}


def _f(v) -> float | None:
    try:
        v = float(v)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None
