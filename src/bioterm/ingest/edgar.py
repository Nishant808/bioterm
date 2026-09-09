"""SEC EDGAR ingestion: ticker->CIK map, XBRL company facts (cash / R&D / net income),
and recent material filings (8-K, S-1/S-3, 424B5) -> ``filings`` table.

No API key. EDGAR requires a descriptive User-Agent (set BIOTERM_SEC_USER_AGENT).
Rate limit: <=10 req/s per IP - we stay well under with throttling.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd

from ..config import CACHE_DIR, load_settings
from ..db import bulk_upsert, filings, read_sql, securities
from ..httpx_util import get_json
from ..universe import universe_tickers

log = logging.getLogger("bioterm.ingest.edgar")

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

_MIN_INTERVAL = 0.15  # ~6-7 req/s, safely under EDGAR's 10/s


@lru_cache(maxsize=1)
def ticker_cik_map() -> dict[str, str]:
    """{TICKER: 'zero-padded-10-digit-CIK'} from SEC's official mapping file."""
    cache = CACHE_DIR / "company_tickers.json"
    try:
        data = get_json(TICKERS_URL, min_interval=_MIN_INTERVAL)
        cache.write_text(json.dumps(data))
    except Exception as exc:  # noqa: BLE001
        if not cache.exists():
            raise
        log.warning("using cached ticker map (%s)", exc)
        data = json.loads(cache.read_text())

    out: dict[str, str] = {}
    values = data.values() if isinstance(data, dict) else data
    for row in values:
        try:
            out[str(row["ticker"]).upper()] = f"{int(row['cik_str']):010d}"
        except (KeyError, TypeError, ValueError):
            continue
    log.info("EDGAR ticker map: %d symbols", len(out))
    return out


def _persist_ciks(tickers: list[str]) -> dict[str, str]:
    cmap = ticker_cik_map()
    rows = []
    resolved: dict[str, str] = {}
    for tk in tickers:
        cik = cmap.get(tk.upper())
        if cik:
            resolved[tk] = cik
            rows.append({"ticker": tk, "cik": cik})
    if rows:
        bulk_upsert(securities, rows, update_only=["cik"])
    return resolved


def _latest_ttm(units: list[dict], want_form_quarterly: bool = True) -> float | None:
    """Sum the 4 most recent distinct quarterly values, or take latest annual."""
    if not units:
        return None
    df = pd.DataFrame(units)
    if "end" not in df:
        return None
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df = df.dropna(subset=["end"]).sort_values("end")
    # quarterly duration facts have ~90-day start->end; annual ~365
    if "start" in df:
        df["start"] = pd.to_datetime(df["start"], errors="coerce")
        df["days"] = (df["end"] - df["start"]).dt.days
        q = df[df["days"].between(60, 100)].drop_duplicates("end", keep="last")
        if len(q) >= 4:
            return float(q.tail(4)["val"].sum())
        a = df[df["days"].between(300, 400)].drop_duplicates("end", keep="last")
        if len(a) >= 1:
            return float(a.tail(1)["val"].iloc[0])
    return float(df.tail(1)["val"].iloc[0])


def _latest_instant(units: list[dict]) -> float | None:
    if not units:
        return None
    df = pd.DataFrame(units)
    if "end" not in df:
        return None
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df = df.dropna(subset=["end"]).sort_values("end")
    return float(df.tail(1)["val"].iloc[0]) if not df.empty else None


def company_facts(cik10: str) -> dict:
    """Return {cash, rd_expense_ttm, net_income_ttm} from XBRL facts (USD)."""
    try:
        data = get_json(FACTS_URL.format(cik10=cik10), min_interval=_MIN_INTERVAL)
    except Exception as exc:  # noqa: BLE001
        log.debug("companyfacts failed for %s: %s", cik10, exc)
        return {}
    usgaap = data.get("facts", {}).get("us-gaap", {})

    def units_for(*tags: str) -> list[dict]:
        for t in tags:
            node = usgaap.get(t)
            if node and "units" in node and "USD" in node["units"]:
                return node["units"]["USD"]
        return []

    cash = _latest_instant(
        units_for(
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsAndShortTermInvestments",
            "CashAndShortTermInvestments",
        )
    )
    sti = _latest_instant(units_for("ShortTermInvestments"))
    if cash is not None and sti:
        cash = cash + sti
    rd = _latest_ttm(units_for("ResearchAndDevelopmentExpense"))
    ni = _latest_ttm(units_for("NetIncomeLoss", "ProfitLoss"))
    ocf = _latest_ttm(
        units_for(
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        )
    )
    return {
        "cash": cash,
        "rd_expense_ttm": rd,
        "net_income_ttm": ni,
        "op_cash_flow_ttm": ocf,
    }


def recent_filings(cik10: str, ticker: str, forms: list[str]) -> list[dict]:
    try:
        data = get_json(SUBMISSIONS_URL.format(cik10=cik10), min_interval=_MIN_INTERVAL)
    except Exception as exc:  # noqa: BLE001
        log.debug("submissions failed for %s: %s", ticker, exc)
        return []
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []
    df = pd.DataFrame(recent)
    if df.empty or "form" not in df:
        return []
    df = df[df["form"].isin(forms)].head(40)
    now = datetime.now(timezone.utc)
    rows = []
    for _, r in df.iterrows():
        acc = str(r.get("accessionNumber", "")).replace("-", "")
        acc_dashed = str(r.get("accessionNumber", ""))
        doc = str(r.get("primaryDocument", ""))
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{acc}/{doc}"
            if acc and doc else
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik10}"
        )
        rows.append(
            {
                "id": f"{ticker}:{acc_dashed}",
                "ticker": ticker,
                "cik": cik10,
                "form": r.get("form"),
                "filed_date": pd.to_datetime(r.get("filingDate"), errors="coerce").date()
                if r.get("filingDate") else None,
                "title": r.get("primaryDocDescription") or r.get("form"),
                "items": str(r.get("items", "") or ""),
                "url": url,
                "fetched_at": now,
            }
        )
    return rows


def run(tickers: list[str] | None = None) -> dict:
    cfg = load_settings()
    forms = cfg.get("ingest", "edgar_forms", default=["8-K", "424B5", "S-1", "S-3"])
    tickers = tickers or universe_tickers()
    resolved = _persist_ciks(tickers)
    log.info("EDGAR: resolved %d/%d CIKs", len(resolved), len(tickers))

    filing_rows: list[dict] = []
    for tk, cik in resolved.items():
        filing_rows.extend(recent_filings(cik, tk, forms))
    n_filings = bulk_upsert(filings, filing_rows)

    log.info("EDGAR: %d filings upserted", n_filings)
    return {"rows": n_filings, "ciks": len(resolved), "filings": n_filings}
