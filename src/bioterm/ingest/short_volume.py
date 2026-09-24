"""FINRA Reg SHO daily short-sale volume -> ``short_volume``.

FINRA publishes, every trading day, how much of each symbol's off-exchange +
consolidated volume was sold short (``CNMSshvolYYYYMMDD.txt``). The short share
of volume is noisy day to day - market makers short to provide liquidity - so
the signal engine only uses its *trend* (5-day vs 20-day), never a level alone.

Free, no key: https://cdn.finra.org/equity/regsho/daily/
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import requests

from ..config import load_settings
from ..db import bulk_upsert, get_engine, read_sql, short_volume
from ..httpx_util import get_bytes
from ..universe import universe_tickers

log = logging.getLogger("bioterm.ingest.short_volume")

URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{ymd}.txt"


def parse(text: str, wanted: set[str] | None = None) -> list[dict]:
    """Pipe-delimited FINRA file -> rows. The last line is a record count."""
    out = []
    for line in (text or "").splitlines()[1:]:
        parts = line.strip().split("|")
        if len(parts) < 5:
            continue
        d, sym = parts[0], parts[1].upper()
        if wanted is not None and sym not in wanted:
            continue
        try:
            out.append({"ticker": sym, "date": pd.to_datetime(d, format="%Y%m%d").date(),
                        "short_volume": float(parts[2]), "short_exempt": float(parts[3]),
                        "total_volume": float(parts[4])})
        except ValueError:
            continue
    return out


def _weekdays_back(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def run(tickers: list[str] | None = None, backfill_days: int | None = None) -> dict:
    cfg = load_settings()
    tickers = tickers or universe_tickers()
    wanted = set(tickers) | set(cfg.benchmarks)
    backfill = int(backfill_days or cfg.get("alt_data", "short_volume_days", default=30))
    keep = int(cfg.get("alt_data", "short_volume_keep_days", default=180))

    have = read_sql("SELECT DISTINCT date FROM short_volume")
    have_dates = {pd.to_datetime(d).date() for d in have["date"]} if not have.empty else set()
    days = [d for d in _weekdays_back(date.today(), backfill) if d not in have_dates]

    total, got_days = 0, 0
    for d in sorted(days):
        try:
            raw = get_bytes(URL.format(ymd=d.strftime("%Y%m%d")), min_interval=0.3,
                            retries=1, timeout=30)
        except requests.HTTPError:
            continue  # holiday, or today's file not published yet
        except Exception as exc:  # noqa: BLE001
            log.warning("short volume %s failed: %s", d, exc)
            continue
        rows = parse(raw.decode("utf-8", errors="ignore"), wanted)
        total += bulk_upsert(short_volume, rows)
        got_days += 1

    with get_engine().begin() as conn:
        conn.execute(short_volume.delete().where(
            short_volume.c.date < date.today() - timedelta(days=keep)))
    log.info("short volume: %d rows over %d new trading days", total, got_days)
    return {"rows": total, "days": got_days}


def short_ratio_trend(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per ticker: 5-day and 20-day short share of volume and the change."""
    df = read_sql("SELECT ticker, date, short_volume, total_volume FROM short_volume") \
        if df is None else df
    cols = ["ticker", "ratio_5d", "ratio_20d", "delta", "days"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    out = []
    for tk, g in df.sort_values("date").groupby("ticker"):
        g = g[g["total_volume"] > 0]
        if len(g) < 5:
            continue
        r = g["short_volume"] / g["total_volume"]
        r5 = float(r.tail(5).mean())
        r20 = float(r.tail(20).mean())
        out.append({"ticker": tk, "ratio_5d": r5, "ratio_20d": r20, "delta": r5 - r20,
                    "days": int(len(g))})
    return pd.DataFrame(out, columns=cols)
