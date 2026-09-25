"""Trading halts from Nasdaq Trader's public RSS feed -> ``halts``.

    https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts

The feed covers every US-listed security Nasdaq halts or tracks (its own and,
for regulatory halts, other venues'), updates within a minute and needs no key.
For biotech the codes that matter most are T1 (news pending - often trial data
or a deal about to cross the wire), T12 (information requested) and H10/H11
(SEC / regulatory); LUDP marks a limit-up/limit-down volatility pause, i.e. a
violent move already under way.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("bioterm.ingest.halts")

URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
NS = {"ndaq": "http://www.nasdaqtrader.com/"}
NY = ZoneInfo("America/New_York")

REASONS = {
    "T1": "News pending", "T2": "News released", "T3": "News and resumption times",
    "T5": "Single-stock trading pause", "T6": "Extraordinary market activity",
    "T7": "Quotation-only period", "T8": "ETF halt",
    "T12": "Additional information requested", "H4": "Non-compliance",
    "H9": "Not current in filings", "H10": "SEC trading suspension",
    "H11": "Regulatory concern", "O1": "Operations halt", "IPO1": "IPO not yet trading",
    "M1": "Corporate action", "M2": "Quotation not available",
    "LUDP": "Volatility trading pause (LULD)", "LUDS": "Volatility pause - straddle",
    "MWC1": "Market-wide circuit breaker L1", "MWC2": "Market-wide circuit breaker L2",
    "MWC3": "Market-wide circuit breaker L3", "MWCQ": "Market-wide circuit breaker resumption",
    "C3": "News not forthcoming - resuming", "C4": "Qualification halt ended",
    "C9": "Qualification halt concluded", "C11": "Other regulator's halt concluded",
    "D": "Deleted from listing",
}
# codes that alert (news-driven, regulatory, or a volatility pause)
ALERT_CODES = {"T1", "T2", "T3", "T6", "T12", "H10", "H11", "LUDP", "LUDS", "M1"}


def _txt(item: ET.Element, tag: str) -> str:
    el = item.find(f"ndaq:{tag}", NS)
    return (el.text or "").strip() if el is not None and el.text else ""


def _ny(date_s: str, time_s: str) -> datetime | None:
    if not date_s:
        return None
    t = (time_s or "00:00:00").split(".")[0]
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(f"{date_s.strip()} {t}", fmt).replace(tzinfo=NY)
        except ValueError:
            continue
    return None


def parse(xml_bytes: bytes | str) -> list[dict[str, Any]]:
    """Feed XML -> halt rows (``halt_at`` in UTC)."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    root = ET.fromstring(xml_bytes.lstrip(b"\xef\xbb\xbf").strip())
    now = datetime.now(timezone.utc)
    out = []
    for item in root.iter("item"):
        sym = _txt(item, "IssueSymbol") or (item.findtext("title") or "").strip()
        if not sym:
            continue
        halt = _ny(_txt(item, "HaltDate"), _txt(item, "HaltTime"))
        code = _txt(item, "ReasonCode").upper()
        res_date = _txt(item, "ResumptionDate")
        res_trade = _txt(item, "ResumptionTradeTime")
        out.append({
            "id": f"{sym}|{_txt(item, 'HaltDate')}|{_txt(item, 'HaltTime')}"[:64],
            "symbol": sym[:16],
            "issue_name": _txt(item, "IssueName")[:200],
            "market": _txt(item, "Market")[:24],
            "reason": code[:12],
            "halt_at": halt.astimezone(timezone.utc) if halt else None,
            "resumption_date": res_date[:16] or None,
            "resumption_trade_time": (f"{res_date} {res_trade}".strip()[:32]
                                      if res_trade else None),
            "fetched_at": now,
        })
    return out


def run(tickers: list[str] | None = None) -> dict[str, Any]:
    from ..db import bulk_upsert, halts, read_sql
    from ..httpx_util import get_bytes

    raw = get_bytes(URL, headers={"User-Agent": "Mozilla/5.0 (BioTerm halts monitor)",
                                  "Accept": "application/rss+xml, application/xml"},
                    min_interval=1.0, retries=2, timeout=15)
    rows = parse(raw)
    if tickers is None:
        uni = read_sql("SELECT ticker FROM securities")
        tickers = uni["ticker"].tolist() if not uni.empty else []
    known = {t.upper() for t in tickers}
    for r in rows:
        # Nasdaq writes class shares as ABC.A; the universe uses ABC-A (Yahoo style)
        tk = r["symbol"].upper().replace(".", "-")
        r["ticker"] = tk if tk in known else None
    n = bulk_upsert(halts, rows)
    ours = sum(1 for r in rows if r["ticker"])
    log.info("halts: %d in feed, %d in the universe", len(rows), ours)
    return {"rows": n, "universe_halts": ours}


def label(code: str) -> str:
    return REASONS.get((code or "").upper(), code or "halt")
