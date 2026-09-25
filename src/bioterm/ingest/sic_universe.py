"""Universe expansion by SEC industry code - the *extended* tier.

Every US-listed company SEC files under the biopharma SIC codes (2834 pharmaceutical
preparations, 2835 in-vitro diagnostics, 2836 biological products, 8731 commercial
physical & biological research) that is not already core (XBI + seed + watchlist).

Extended names get light coverage - prices, technicals and a rotating slice of
fundamentals + EDGAR (``pipeline.refresh_extended``) - so the Screener, the market
heatmap, the command bar and the Copilot reach the whole sector. The Focus Score, the
signal engine and the heavy per-name sources (news, trials, insiders, options) stay on
core. Adding an extended name to the watchlist promotes it to core.

Sources: EDGAR's company browse by SIC (Atom, paginated; company names come back
mangled, so names are taken from the ticker file) and SEC's ticker file with exchanges
(``company_tickers_exchange.json``) - OTC and unlisted CIKs are dropped.
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("bioterm.ingest.sic_universe")

SICS = ("2834", "2835", "2836", "8731")
BROWSE = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type="
          "&dateb=&owner=include&start={start}&count={count}&output=atom")
PAGE = 100
EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_NS = "{http://www.w3.org/2005/Atom}"
_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,6}$")
_MIN_INTERVAL = 0.15


def parse_feed(xml: bytes | str) -> tuple[list[dict[str, str]], str | None]:
    """One page of the SIC browse feed -> ([{cik, sic, state}], next page URL)."""
    root = ET.fromstring(xml.encode("latin-1", "replace") if isinstance(xml, str) else xml)
    out = []
    for e in root.iter(f"{_NS}entry"):
        info = e.find(f"{_NS}content/{_NS}company-info")
        if info is None:
            continue
        cik = (info.findtext(f"{_NS}cik") or "").strip()
        if not cik.isdigit():
            continue
        out.append({"cik": f"{int(cik):010d}",
                    "sic": (info.findtext(f"{_NS}sic") or "").strip()[:8],
                    "state": (info.findtext(f"{_NS}state") or "").strip()[:4]})
    nxt = None
    for link in root.findall(f"{_NS}link"):
        if link.get("rel") == "next" and link.get("href"):
            nxt = link.get("href")
    return out, nxt


def parse_exchange_file(data: Any) -> dict[str, dict[str, str]]:
    """SEC's ``company_tickers_exchange.json`` ({fields, data}) -> {cik10: {ticker,
    name, exchange}}, first (primary) ticker per CIK, OTC / unlisted dropped."""
    fields = [str(f).lower() for f in (data or {}).get("fields") or []]
    try:
        ic, iname, it, ix = (fields.index(k) for k in ("cik", "name", "ticker", "exchange"))
    except ValueError:
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in (data or {}).get("data") or []:
        try:
            cik = f"{int(row[ic]):010d}"
            tk = str(row[it] or "").strip().upper()
            ex = str(row[ix] or "").strip()
        except (IndexError, TypeError, ValueError):
            continue
        if cik in out or not _TICKER_RE.match(tk) or not ex or "otc" in ex.lower():
            continue
        out[cik] = {"ticker": tk, "name": str(row[iname] or tk).strip()[:256],
                    "exchange": ex[:32]}
    return out


def listed() -> dict[str, dict[str, str]]:
    """Currently listed CIKs. Falls back to the plain ticker file (no exchange, so
    OTC names can slip through) when the exchange file is unavailable."""
    from ..httpx_util import get_json

    try:
        out = parse_exchange_file(get_json(EXCHANGE_URL, min_interval=_MIN_INTERVAL,
                                           timeout=40))
        if out:
            return out
    except Exception as exc:  # noqa: BLE001
        log.warning("exchange ticker file failed (%s) - using company_tickers.json", exc)
    from .edgar import _company_tickers

    out = {}
    for row in _company_tickers():
        try:
            cik = f"{int(row['cik_str']):010d}"
            tk = str(row["ticker"]).upper()
        except (KeyError, TypeError, ValueError):
            continue
        if cik not in out and _TICKER_RE.match(tk):
            out[cik] = {"ticker": tk, "name": str(row.get("title") or tk)[:256],
                        "exchange": ""}
    return out


def crawl(sics: tuple[str, ...] = SICS, max_pages: int = 60, budget_s: float = 360,
          attempts: int = 3) -> tuple[dict[str, str], bool]:
    """{cik10: sic} across the SIC codes; ``complete`` is False when a page could not be
    read, or the page cap / wall-clock budget cut a crawl short (then nobody is
    demoted). EDGAR's browse pages are slow and sometimes time out: each page gets
    ``attempts`` tries, and a page that still fails is skipped, not the rest."""
    from ..httpx_util import CircuitOpen, get_bytes

    found: dict[str, str] = {}
    complete = True
    t0 = time.monotonic()
    for sic in sics:
        start = 0
        for _ in range(max_pages):
            if time.monotonic() - t0 > budget_s:
                complete = False
                log.warning("SIC crawl out of time at SIC %s, offset %d", sic, start)
                return found, False
            url = BROWSE.format(sic=sic, start=start, count=PAGE)
            rows = nxt = None
            for attempt in range(attempts):
                try:
                    rows, nxt = parse_feed(get_bytes(url, min_interval=_MIN_INTERVAL,
                                                     retries=1, timeout=45))
                    break
                except CircuitOpen as exc:
                    log.warning("SIC crawl stopped: %s", exc)
                    return found, False
                except Exception as exc:  # noqa: BLE001
                    log.warning("SIC %s offset %d try %d failed: %s", sic, start,
                                attempt + 1, exc)
                    time.sleep(3 * (attempt + 1))
            if rows is None:
                complete = False              # skip the page, keep crawling
                start += PAGE
                continue
            for r in rows:
                found.setdefault(r["cik"], r["sic"] or sic)
            if not nxt or len(rows) < PAGE:
                break
            start += PAGE
        else:
            complete = False
            log.warning("SIC %s crawl hit the %d-page cap", sic, max_pages)
    return found, complete


def plan(found: dict[str, str], listing: dict[str, dict[str, str]],
         existing: list[dict[str, Any]], complete: bool) -> dict[str, list[dict]]:
    """Pure: which securities rows to insert, which to tag with their SIC and which
    extended names to retire (no longer listed under these codes)."""
    now = datetime.now(timezone.utc)
    have = {r["ticker"]: r for r in existing}
    by_cik = {str(r.get("cik") or "").zfill(10): r["ticker"] for r in existing
              if str(r.get("cik") or "").strip().isdigit()}
    new, tag, seen = [], [], set()
    for cik, sic in found.items():
        lst = listing.get(cik)
        if not lst:
            continue
        tk = by_cik.get(cik) or lst["ticker"]
        seen.add(tk)
        if tk in have:
            row = {"ticker": tk, "sic": sic, "cik": cik}
            if have[tk].get("tier") == "inactive":
                row["tier"] = "extended"
            tag.append(row)
        else:
            new.append({"ticker": tk, "name": lst["name"], "exchange": lst["exchange"] or None,
                        "cik": cik, "sic": sic, "tier": "extended", "is_watchlist": 0,
                        "in_xbi": 0, "in_ibb": 0, "in_seed": 0, "etf_weight": None,
                        "updated_at": now})
    retire = []
    if complete:
        retire = [{"ticker": t, "tier": "inactive"} for t, r in have.items()
                  if r.get("tier") == "extended" and t not in seen]
    return {"new": new, "tag": tag, "retire": retire}


def run(sics: tuple[str, ...] | None = None, max_pages: int = 60,
        budget_s: float = 360) -> dict:
    from ..config import load_settings
    from ..db import bulk_upsert, read_sql, securities

    sics = tuple(str(x) for x in (sics or load_settings().get("universe", "sic_codes",
                                                               default=list(SICS))))
    found, complete = crawl(sics, max_pages=max_pages, budget_s=budget_s)
    if not found:
        return {"rows": 0, "error": "SIC crawl returned nothing"}
    listing = listed()
    existing = read_sql("SELECT ticker, cik, tier FROM securities").to_dict("records")
    p = plan(found, listing, existing, complete)
    if p["new"]:
        bulk_upsert(securities, p["new"])
    tag = [r for r in p["tag"] if "tier" not in r]
    if tag:
        bulk_upsert(securities, tag, update_only=["sic", "cik"])
    revive = [r for r in p["tag"] if "tier" in r]
    if revive:
        bulk_upsert(securities, revive, update_only=["sic", "cik", "tier"])
    if p["retire"]:
        bulk_upsert(securities, p["retire"], update_only=["tier"])
    log.info("SIC universe: %d CIKs, %d listed, %d new extended, %d retired%s",
             len(found), len(p["new"]) + len(p["tag"]), len(p["new"]), len(p["retire"]),
             "" if complete else " (crawl incomplete)")
    return {"rows": len(p["new"]) + len(p["tag"]), "ciks": len(found),
            "new": len(p["new"]), "tagged": len(p["tag"]), "retired": len(p["retire"]),
            "complete": complete}
