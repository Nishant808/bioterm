"""openFDA ingestion -> ``fda_events``.

We pull each sponsor's Drugs@FDA record and record recent **approval** actions
(original NDA/BLA approvals and efficacy supplements). Recent approvals are
realized catalysts; the presence of approved products is a de-risking signal used
by the risk overlay.

No API key (40 req/min unauthenticated - we throttle).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone

import pandas as pd

from ..db import bulk_upsert, fda_events, read_sql
from ..httpx_util import get_json
from ..universe import universe_tickers
from ..util import as_text

log = logging.getLogger("bioterm.ingest.fda")

API = "https://api.fda.gov/drug/drugsfda.json"

_CORP_STOP = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "llc", "plc", "ag", "the", "and", "&",
}


def _sponsor_token(name: str) -> str:
    for t in re.sub(r"[.,]", " ", as_text(name)).split():
        if t.lower() not in _CORP_STOP and len(t) > 2:
            return t.upper()
    return ""


def _mk_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:40]


def fetch_sponsor(token: str, limit: int = 100) -> list[dict]:
    params = {"search": f"sponsor_name:{token}*", "limit": limit}
    try:
        data = get_json(API, params=params, min_interval=2.5, retries=2)
    except Exception as exc:  # noqa: BLE001
        if "NOT_FOUND" in str(exc) or "404" in str(exc):
            return []
        raise
    return data.get("results", []) or []


def run(tickers: list[str] | None = None, time_budget_s: float = 240.0) -> dict:
    tickers = tickers or universe_tickers()
    secs = read_sql("SELECT ticker, name FROM securities")
    name_by_ticker = dict(zip(secs["ticker"], secs["name"])) if not secs.empty else {}
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=365 * 3)
    now = datetime.now(timezone.utc)
    deadline = time.monotonic() + time_budget_s

    rows: list[dict] = []
    seen_tokens: set[str] = set()
    hits = 0
    consecutive_fail = 0
    stopped_early = False
    for tk in tickers:
        token = _sponsor_token(name_by_ticker.get(tk, tk))
        if not token or token in seen_tokens:
            continue
        if time.monotonic() > deadline:
            log.warning("openFDA: hit %.0fs time budget after %d sponsors - stopping",
                        time_budget_s, len(seen_tokens))
            stopped_early = True
            break
        seen_tokens.add(token)
        try:
            results = fetch_sponsor(token)
            consecutive_fail = 0
        except Exception as exc:  # noqa: BLE001
            log.warning("openFDA fetch failed for %s (%s): %s", tk, token, exc)
            consecutive_fail += 1
            if consecutive_fail >= 5:
                log.error("openFDA: 5 consecutive failures - aborting fda ingest")
                stopped_early = True
                break
            continue
        if results:
            hits += 1
        for r in results:
            app_no = r.get("application_number", "")
            products = r.get("products", []) or []
            brand = next((p.get("brand_name") for p in products if p.get("brand_name")), "")
            generic = ""
            if products and products[0].get("active_ingredients"):
                generic = ", ".join(
                    a.get("name", "") for a in products[0]["active_ingredients"]
                )
            for s in r.get("submissions", []) or []:
                if s.get("submission_status") != "AP":
                    continue
                sdate = pd.to_datetime(s.get("submission_status_date"), errors="coerce")
                if pd.isna(sdate) or sdate < cutoff:
                    continue
                stype = s.get("submission_type", "")
                desc = f"{stype} {s.get('submission_number','')} approved for {brand or app_no}"
                rows.append(
                    {
                        "id": _mk_id(tk, app_no, s.get("submission_number"), stype),
                        "ticker": tk,
                        "kind": "approval",
                        "application_number": app_no,
                        "brand_name": brand,
                        "generic_name": generic[:250],
                        "sponsor_name": r.get("sponsor_name", ""),
                        "event_date": sdate.date(),
                        "description": desc,
                        "url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={re.sub(r'[^0-9]', '', app_no)}",
                        "fetched_at": now,
                    }
                )

    n = bulk_upsert(fda_events, rows)
    log.info("fda: %d approval events across %d sponsors (%d queried%s)",
             n, hits, len(seen_tokens), ", stopped early" if stopped_early else "")
    return {"rows": n, "sponsors_with_data": hits, "queried": len(seen_tokens),
            "stopped_early": stopped_early}
