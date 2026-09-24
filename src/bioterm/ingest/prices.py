"""Price ingestion via yfinance -> ``prices`` table (daily OHLCV).

Incremental: a ticker already stored with a recent close only fetches the last
month (a handful of rows to upsert instead of years of history on every run);
a new ticker - or one whose history hasn't been deepened to the configured
period yet - gets one full backfill, remembered in app_meta so short-history
names (recent IPOs) aren't re-downloaded daily. Benchmark ETFs (XBI, IBB, SPY)
ride along for the market-regime and relative-strength signals.
"""
from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from ..config import load_settings
from ..db import bulk_upsert, prices, read_sql
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


def plan(tickers: list[str], period: str, backfilled: set[str],
         today: pd.Timestamp | None = None) -> dict[str, list[str]]:
    """Split tickers into {period: [tickers]} - "1mo" for names that are current
    and already backfilled, the full ``period`` for everything else. Pure."""
    today = today or pd.Timestamp.today().normalize()
    have = read_sql("SELECT ticker, MAX(date) AS last FROM prices GROUP BY ticker")
    last = dict(zip(have["ticker"], pd.to_datetime(have["last"]))) if not have.empty else {}
    out: dict[str, list[str]] = {"1mo": [], period: []}
    for tk in tickers:
        lt = last.get(tk)
        fresh = lt is not None and (today - lt).days <= 12
        out["1mo" if fresh and tk in backfilled else period].append(tk)
    return {k: v for k, v in out.items() if v}


def run(tickers: list[str] | None = None) -> dict:
    from ..store import get_meta, set_meta

    cfg = load_settings()
    period = cfg.get("price_history_period", default="5y")
    tickers = list(dict.fromkeys((tickers or universe_tickers()) + cfg.benchmarks))
    backfilled = set(get_meta(f"prices_backfilled_{period}", []) or [])
    total = 0
    failed: list[str] = []
    done_full: list[str] = []

    # batch to keep memory/URL length sane on a 16 GB machine
    batch_size = 60
    jobs = [(per, grp[i:i + batch_size]) for per, grp in plan(tickers, period, backfilled).items()
            for i in range(0, len(grp), batch_size)]
    for per, batch in jobs:
        try:
            data = _download(batch, per)
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
                if per == period:
                    done_full.append(tk)
            except Exception as exc:  # noqa: BLE001
                log.warning("parse failed for %s: %s", tk, exc)
                failed.append(tk)

    if done_full:
        set_meta(f"prices_backfilled_{period}", sorted(backfilled | set(done_full)))
    log.info("prices: upserted %d rows, %d tickers failed (%d backfilled to %s)",
             total, len(failed), len(done_full), period)
    return {"rows": total, "failed": failed, "backfilled": len(done_full)}


def _f(v) -> float | None:
    try:
        v = float(v)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None
