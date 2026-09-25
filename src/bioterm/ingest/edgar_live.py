"""SEC filings within minutes of acceptance, from EDGAR's "latest filings" Atom
feed, matched to the universe by CIK -> ``filings`` (source = "live").

    https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=100&output=atom

The daily EDGAR job (``ingest/edgar.py``) reads each company's full submission
history; this one only asks "what was filed in the last hour or so" for the forms
that move biotech stocks: 8-K / 6-K (data, FDA letters, deals), 424B prospectus
supplements and S-3 shelves (dilution), and Schedule 13D/13G (activist or
5% holders). One request per form type per run; the row ids match the daily
job's (``TICKER:accession``) so the two never duplicate.
"""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import pandas as pd

log = logging.getLogger("bioterm.ingest.edgar_live")

FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}&company="
        "&dateb=&owner=include&start=0&count={count}&output=atom")
# the feed's type filter is a prefix match: "SC 13" covers SC 13D/13G (+ /A)
FORMS = ["8-K", "6-K", "424B", "S-3", "SC 13", "SCHEDULE 13"]
ATOM = {"a": "http://www.w3.org/2005/Atom"}

_TITLE = re.compile(r"^(?P<form>.+?) - (?P<name>.+) \((?P<cik>\d{4,10})\) \((?P<role>[^)]+)\)")
_ACC = re.compile(r"AccNo:</b>\s*([\d-]{20})|accession-number=([\d-]{20})")
_FILED = re.compile(r"Filed:</b>\s*(\d{4}-\d{2}-\d{2})")
_ITEM = re.compile(r"Item\s+(\d+\.\d+)")


def parse(xml_bytes: bytes | str) -> list[dict[str, Any]]:
    """Atom feed -> [{form, company, cik, role, accession, filed, items, url, updated}]."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("latin-1", "ignore")
    root = ET.fromstring(xml_bytes)
    out = []
    for e in root.findall("a:entry", ATOM):
        title = (e.findtext("a:title", default="", namespaces=ATOM) or "").strip()
        m = _TITLE.match(title)
        if not m:
            continue
        summary = html.unescape(e.findtext("a:summary", default="", namespaces=ATOM) or "")
        eid = e.findtext("a:id", default="", namespaces=ATOM) or ""
        acc = _ACC.search(summary) or _ACC.search(eid)
        accession = (acc.group(1) or acc.group(2)) if acc else None
        link = e.find("a:link", ATOM)
        filed = _FILED.search(summary)
        out.append({
            "form": m.group("form").strip(),
            "company": m.group("name").strip(),
            "cik": f"{int(m.group('cik')):010d}",
            "role": m.group("role").strip(),
            "accession": accession,
            "filed": filed.group(1) if filed else None,
            "items": ",".join(dict.fromkeys(_ITEM.findall(summary))),
            "url": link.get("href") if link is not None else None,
            "updated": e.findtext("a:updated", default="", namespaces=ATOM),
        })
    return out


def to_rows(entries: list[dict], cik_to_ticker: dict[str, str]) -> list[dict[str, Any]]:
    """Feed entries for universe companies -> ``filings`` rows. A 13D/13G shows up
    twice (filer and subject); the subject company is the one we track."""
    now = datetime.now(timezone.utc)
    rows: dict[str, dict] = {}
    for en in entries:
        tk = cik_to_ticker.get(en["cik"])
        if not tk or not en["accession"]:
            continue
        if en["form"].upper().startswith(("SC 13", "SCHEDULE 13")) and en["role"] != "Subject":
            continue
        rid = f"{tk}:{en['accession']}"
        rows[rid] = {
            "id": rid[:64], "ticker": tk, "cik": en["cik"], "form": en["form"][:16],
            "filed_date": pd.to_datetime(en["filed"], errors="coerce").date()
            if en["filed"] else now.date(),
            "title": f"{en['form']} - {en['company']}"[:500],
            "items": en["items"][:256], "url": (en["url"] or "")[:256],
            "fetched_at": now, "source": "live",
        }
    return list(rows.values())


def run(forms: list[str] | None = None, count: int = 100) -> dict[str, Any]:
    from ..db import bulk_upsert, filings, read_sql
    from ..httpx_util import get_bytes

    secs = read_sql("SELECT ticker, cik FROM securities WHERE cik IS NOT NULL")
    cik_to_ticker = {f"{int(c):010d}": t for t, c in zip(secs["ticker"], secs["cik"])
                     if str(c).strip().isdigit()}
    if not cik_to_ticker:
        return {"rows": 0, "note": "no CIKs yet - run the EDGAR job first"}
    existing = read_sql("SELECT id FROM filings WHERE filed_date >= :c",
                        {"c": (datetime.now(timezone.utc).date()
                               - pd.Timedelta(days=5)).isoformat()})
    have = set(existing["id"]) if not existing.empty else set()
    new_rows, seen = [], 0
    for form in forms or FORMS:
        try:
            raw = get_bytes(FEED.format(form=form.replace(" ", "+"), count=count),
                            min_interval=0.2, retries=1, timeout=25)
        except Exception as exc:  # noqa: BLE001 - one form type failing is fine
            log.warning("edgar live %s failed: %s", form, exc)
            continue
        entries = parse(raw)
        seen += len(entries)
        # only rows we don't already have - an existing row from the daily job
        # carries the primary-document URL, which is better than the index page
        new_rows += [r for r in to_rows(entries, cik_to_ticker) if r["id"] not in have]
    n = bulk_upsert(filings, new_rows) if new_rows else 0
    log.info("edgar live: %d feed entries, %d new universe filings", seen, n)
    return {"rows": n, "entries": seen}
