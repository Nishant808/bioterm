"""Build the working ticker universe: XBI + IBB holdings + seed list + watchlist.

All sources are public, no-signup downloads. Any source that fails is skipped with
a warning - the seed list + watchlist always guarantee a usable universe.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

import pandas as pd

from .config import load_settings
from .db import bulk_upsert, read_sql, securities
from .httpx_util import get_bytes

log = logging.getLogger("bioterm.universe")

XBI_XLSX = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx"
)
IBB_CSV = (
    "https://www.ishares.com/us/products/239699/"
    "ishares-nasdaq-biotechnology-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IBB_holdings&dataType=fund"
)

_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,6}$")


def _valid_ticker(t) -> bool:
    if not isinstance(t, str):
        return False
    t = t.strip().upper()
    return bool(_TICKER_RE.match(t)) and t not in {"CASH", "USD", "-", "NAN"}


def fetch_xbi() -> pd.DataFrame:
    """SPDR S&P Biotech ETF daily holdings -> DataFrame[ticker, name, weight]."""
    raw = get_bytes(XBI_XLSX, min_interval=1.0)
    # The sheet has a few preamble rows before the 'Ticker' header.
    xls = pd.read_excel(io.BytesIO(raw), header=None)
    header_row = None
    for i in range(min(15, len(xls))):
        row = [str(x).strip().lower() for x in xls.iloc[i].tolist()]
        if "ticker" in row and ("name" in row or "weight" in " ".join(row)):
            header_row = i
            break
    if header_row is None:
        raise ValueError("could not locate header row in XBI holdings sheet")
    df = pd.read_excel(io.BytesIO(raw), header=header_row, dtype_backend="numpy_nullable")
    df.columns = [str(c).strip().lower() for c in df.columns]
    tick_col = next(c for c in df.columns if c == "ticker")
    name_col = next((c for c in df.columns if "name" in c), None)
    wt_col = next((c for c in df.columns if "weight" in c), None)
    out = pd.DataFrame(
        {
            "ticker": df[tick_col].astype("string").fillna("").str.strip().str.upper(),
            "name": df[name_col].astype("string").fillna("").str.strip() if name_col else "",
            "weight": pd.to_numeric(df[wt_col], errors="coerce") if wt_col else pd.NA,
        }
    )
    out = out[out["ticker"].map(_valid_ticker)].reset_index(drop=True)
    out["ticker"] = out["ticker"].astype(str)
    out["name"] = out["name"].astype(str)
    log.info("XBI: %d holdings", len(out))
    return out


def fetch_ibb() -> pd.DataFrame:
    """iShares Biotechnology ETF holdings -> DataFrame[ticker, name, weight]. Best effort.

    NOTE: iShares currently serves an HTML bot-protection interstitial to
    non-browser clients, so this usually fails. It is disabled by default in
    settings.yml; the seed list covers the large-cap biotech that IBB holds.
    """
    raw = get_bytes(
        IBB_CSV,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Referer": "https://www.ishares.com/us/products/239699/"
            "ishares-nasdaq-biotechnology-etf",
            "Accept": "text/csv,application/csv,*/*",
        },
        min_interval=1.0,
    )
    text = raw.decode("utf-8", errors="replace")
    if "<!DOCTYPE html>" in text[:200] or "<html" in text[:200]:
        raise ValueError("iShares returned an HTML interstitial, not CSV")
    # iShares CSV has ~9 preamble lines before the real header 'Ticker,Name,...'
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.lower().startswith('"ticker"') or
         ln.lower().startswith("ticker,")),
        None,
    )
    if start is None:
        raise ValueError("could not locate header row in IBB holdings CSV")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df.columns = [str(c).strip().lower() for c in df.columns]
    tick_col = next(c for c in df.columns if c == "ticker")
    name_col = next((c for c in df.columns if c == "name"), None)
    wt_col = next((c for c in df.columns if "weight" in c), None)
    out = pd.DataFrame(
        {
            "ticker": df[tick_col].astype(str).str.strip().str.upper(),
            "name": df[name_col].astype(str).str.strip() if name_col else "",
            "weight": pd.to_numeric(df[wt_col], errors="coerce") if wt_col else pd.NA,
        }
    )
    out = out[out["ticker"].map(_valid_ticker)].reset_index(drop=True)
    log.info("IBB: %d holdings", len(out))
    return out


def build_universe(force: bool = False) -> pd.DataFrame:
    """Assemble + persist the universe into the ``securities`` table."""
    cfg = load_settings()
    ucfg = cfg.raw.get("universe", {})

    if not force:
        existing = read_sql("SELECT * FROM securities")
        if not existing.empty and "updated_at" in existing:
            last = pd.to_datetime(existing["updated_at"], errors="coerce", utc=True).max()
            if pd.notna(last):
                age_days = (pd.Timestamp.now(tz="UTC") - last).days
                if age_days < int(ucfg.get("refresh_days", 7)):
                    log.info("universe is %d days old - skipping rebuild", age_days)
                    return existing

    frames: dict[str, pd.DataFrame] = {}
    if ucfg.get("use_xbi", True):
        try:
            frames["xbi"] = fetch_xbi()
        except Exception as exc:  # noqa: BLE001
            log.warning("XBI holdings fetch failed: %s", exc)
    if ucfg.get("use_ibb", True):
        try:
            frames["ibb"] = fetch_ibb()
        except Exception as exc:  # noqa: BLE001
            log.warning("IBB holdings fetch failed (falling back to seed): %s", exc)

    records: dict[str, dict] = {}

    def _touch(ticker: str, name: str = "") -> dict:
        ticker = ticker.upper()
        rec = records.setdefault(
            ticker,
            {
                "ticker": ticker, "name": name or ticker, "exchange": None, "cik": None,
                "is_watchlist": 0, "in_xbi": 0, "in_ibb": 0, "in_seed": 0,
                "etf_weight": None, "updated_at": datetime.now(timezone.utc),
            },
        )
        if name and (not rec["name"] or rec["name"] == ticker):
            rec["name"] = name
        return rec

    for key, df in frames.items():
        for _, row in df.iterrows():
            rec = _touch(row["ticker"], str(row.get("name") or ""))
            rec[f"in_{key}"] = 1
            w = row.get("weight")
            if pd.notna(w):
                rec["etf_weight"] = max(rec["etf_weight"] or 0.0, float(w))

    if ucfg.get("use_seed", True):
        for s in cfg.seed:
            rec = _touch(str(s["ticker"]), str(s.get("name", "")))
            rec["in_seed"] = 1

    if ucfg.get("include_watchlist", True):
        from .store import get_watchlist

        for w in get_watchlist():
            rec = _touch(str(w["ticker"]))
            rec["is_watchlist"] = 1

    rows = list(records.values())
    if not rows:
        raise RuntimeError("universe is empty - all sources failed and no seed/watchlist")

    bulk_upsert(securities, rows)
    df = pd.DataFrame(rows)
    log.info(
        "universe built: %d tickers (xbi=%d ibb=%d seed=%d watchlist=%d)",
        len(df), df["in_xbi"].sum(), df["in_ibb"].sum(),
        df["in_seed"].sum(), df["is_watchlist"].sum(),
    )
    return df


def universe_tickers(limit: int | None = None) -> list[str]:
    df = read_sql("SELECT ticker, is_watchlist, etf_weight FROM securities")
    if df.empty:
        df = build_universe()
    # watchlist first, then by ETF weight desc, then alpha
    df["etf_weight"] = pd.to_numeric(df["etf_weight"], errors="coerce").fillna(0.0)
    df = df.sort_values(
        ["is_watchlist", "etf_weight", "ticker"], ascending=[False, False, True]
    )
    tickers = df["ticker"].tolist()
    cfg_limit = load_settings().universe_limit
    if limit:
        tickers = tickers[:limit]
    elif cfg_limit:
        tickers = tickers[:cfg_limit]
    return tickers
