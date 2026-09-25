"""Government awards (USAspending.gov) -> ``gov_awards``.

BARDA / HHS / DoD contracts and NIH grants to universe companies - a
non-dilutive funding source and, for vaccine / antiviral / countermeasure
names, often the whole revenue story. One POST per company per award family
(contracts, grants) to the public ``spending_by_award`` search; the watchlist
and the top of the Focus list first, a bounded slice per run.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("bioterm.ingest.gov")

API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
FAMILIES = {"contract": ["A", "B", "C", "D"], "grant": ["02", "03", "04", "05"]}
FIELDS = ["Award ID", "Recipient Name", "Start Date", "End Date", "Award Amount",
          "Awarding Agency", "Awarding Sub Agency", "Description", "generated_internal_id"]


def search(name: str, codes: list[str], since: date) -> list[dict]:
    from ..httpx_util import post_json

    payload = {"filters": {"recipient_search_text": [name], "award_type_codes": codes,
                           "time_period": [{"start_date": since.isoformat(),
                                            "end_date": date.today().isoformat()}]},
               "fields": FIELDS, "limit": 25, "page": 1, "sort": "Award Amount",
               "order": "desc", "subawards": False}
    data = post_json(API, payload, min_interval=0.5, retries=2, timeout=30)
    return (data or {}).get("results", []) or []


def to_rows(results: list[dict], ticker: str, family: str, name_key: str) -> list[dict]:
    from ..util import company_key

    now = datetime.now(timezone.utc)
    out = []
    for r in results:
        # the search is a text match - keep awards whose recipient really is the company
        if company_key(r.get("Recipient Name")) != name_key and \
                not company_key(r.get("Recipient Name")).startswith(name_key + " "):
            continue
        gid = r.get("generated_internal_id") or r.get("Award ID")
        out.append({"id": f"{ticker}|{gid}"[:80], "ticker": ticker,
                    "recipient": str(r.get("Recipient Name") or "")[:200],
                    "agency": str(r.get("Awarding Agency") or "")[:160],
                    "sub_agency": str(r.get("Awarding Sub Agency") or "")[:160],
                    "amount": float(r.get("Award Amount") or 0),
                    "start_date": r.get("Start Date") or None,
                    "end_date": r.get("End Date") or None,
                    "description": str(r.get("Description") or "")[:2000],
                    "award_type": family,
                    "url": f"https://www.usaspending.gov/award/{gid}" if gid else None,
                    "fetched_at": now})
    return out


def run(max_companies: int = 40, years: int = 5, budget_s: float = 150) -> dict[str, Any]:
    from ..db import bulk_upsert, gov_awards, read_sql
    from ..store import get_meta, get_watchlist, set_meta
    from ..util import company_key

    secs = read_sql("SELECT s.ticker, s.name, sc.rank FROM securities s LEFT JOIN scores sc "
                    "ON sc.ticker = s.ticker AND sc.asof = (SELECT MAX(asof) FROM scores) "
                    "WHERE s.tier IS NULL OR s.tier = 'core'")
    wl = {w["ticker"].upper() for w in get_watchlist()}
    secs["pri"] = secs["ticker"].map(lambda t: 0 if t in wl else 1)
    secs = secs.sort_values(["pri", "rank"], na_position="last")
    # rotate through the universe: start after the last name done
    order = secs["ticker"].tolist()
    last = (get_meta("gov_cursor", {}) or {}).get("last")
    if last in order and not wl:
        i = order.index(last) + 1
        order = order[i:] + order[:i]
    names = dict(zip(secs["ticker"], secs["name"]))
    since = date.today() - timedelta(days=365 * years)
    rows, t0, done = [], time.monotonic(), []
    for tk in order[:max_companies]:
        if time.monotonic() - t0 > budget_s:
            break
        key = company_key(names.get(tk))
        if len(key) < 3:
            continue
        for fam, codes in FAMILIES.items():
            try:
                rows += to_rows(search(key.title(), codes, since), tk, fam, key)
            except Exception as exc:  # noqa: BLE001
                log.info("usaspending %s %s: %s", tk, fam, exc)
        done.append(tk)
    if rows:
        bulk_upsert(gov_awards, rows)
    if done:
        set_meta("gov_cursor", {"last": done[-1]})
    return {"rows": len(rows), "companies": len(done)}
