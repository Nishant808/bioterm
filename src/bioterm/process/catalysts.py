"""Catalyst construction -> ``catalysts`` table.

Merges four sources into one dated, typed, forward-looking catalyst list:
  1. ClinicalTrials.gov primary-completion dates for Phase 1-3 studies
  2. Dates extracted by regex from recent news ("PDUFA date of ...", "topline in Q4 2026")
  3. Next earnings date (yfinance)
  4. Manually pinned catalysts (config/catalysts_manual.yml)

``months_away`` is signed: negative = already passed (kept for a short grace window
because "data expected imminently" is itself a catalyst).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timezone

import pandas as pd
from dateutil.relativedelta import relativedelta

from ..config import load_settings
from ..db import bulk_upsert, catalysts, read_sql

log = logging.getLogger("bioterm.process.catalysts")

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}
_MONTHS.update({m[:3].lower(): i for m, i in list(_MONTHS.items())})

_QUARTER_DATE = {1: (2, 15), 2: (5, 15), 3: (8, 15), 4: (11, 15)}


def _mk_id(ticker: str, ctype: str, d: date, title: str) -> str:
    key = f"{ticker}|{ctype}|{d}|{title[:60]}"
    return hashlib.sha1(key.encode()).hexdigest()[:48]


# ---------------------------------------------------------------- date extraction
_RE_MONTH_DAY_YEAR = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2}),?\s+(20\d{2})\b", re.I)
_RE_MONTH_YEAR = re.compile(r"\b(" + "|".join(_MONTHS) + r")\.?\s+(20\d{2})\b", re.I)
_RE_QUARTER = re.compile(
    r"\b(?:Q([1-4])|([1-4])Q|(first|second|third|fourth)[\s-]quarter)\s*(?:of\s+)?(?:20)?(\d{2})\b",
    re.I)
_RE_HALF = re.compile(
    r"\b(?:(H[12])|(first|second)[\s-]half|([12])H)\s*(?:of\s+)?(?:20)?(\d{2})\b", re.I)
_RE_VAGUE_YEAR = re.compile(r"\b(early|mid|late|end[\s-]of)[\s-]?(20\d{2})\b", re.I)


def extract_date(text: str) -> tuple[date, str] | None:
    """Return (date, granularity) for the first future-ish date found, else None."""
    t = text or ""
    m = _RE_MONTH_DAY_YEAR.search(t)
    if m:
        mon, day, year = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
        try:
            return date(year, mon, min(day, 28)), "day"
        except ValueError:
            pass
    m = _RE_QUARTER.search(t)
    if m:
        q = m.group(1) or m.group(2)
        if not q and m.group(3):
            q = {"first": 1, "second": 2, "third": 3, "fourth": 4}[m.group(3).lower()]
        q = int(q)
        year = 2000 + int(m.group(4))
        mo, dy = _QUARTER_DATE[q]
        return date(year, mo, dy), "quarter"
    m = _RE_HALF.search(t)
    if m:
        half = (m.group(1) or m.group(3) or "").upper().replace("H", "")
        if not half and m.group(2):
            half = "1" if m.group(2).lower() == "first" else "2"
        year = 2000 + int(m.group(4))
        return (date(year, 3, 31) if half == "1" else date(year, 9, 30)), "half"
    m = _RE_MONTH_YEAR.search(t)
    if m:
        return date(int(m.group(2)), _MONTHS[m.group(1).lower()], 15), "month"
    m = _RE_VAGUE_YEAR.search(t)
    if m:
        year = int(m.group(2))
        bucket = {"early": (2, 15), "mid": (6, 30), "late": (11, 15), "end-of": (12, 15),
                  "end of": (12, 15)}.get(m.group(1).lower(), (6, 30))
        return date(year, *bucket), "year"
    return None


_TYPE_KEYWORDS = [
    ("pdufa", re.compile(r"\bPDUFA\b|\baction date\b|\btarget action\b", re.I)),
    ("adcom", re.compile(r"advisory committee|\bAdCom\b|\bODAC\b|\bpanel\b", re.I)),
    ("fda_action", re.compile(r"FDA decision|approval decision|regulatory decision|"
                              r"decision (?:is )?expected|BLA|NDA|sBLA|resubmission", re.I)),
    ("phase3_readout", re.compile(r"phase 3|phase iii|pivotal|registrational", re.I)),
    ("phase2_readout", re.compile(r"phase 2|phase ii\b", re.I)),
    ("phase1_readout", re.compile(r"phase 1|phase i\b", re.I)),
    ("data_presentation", re.compile(r"topline|read ?out|data|results|present(?:ation)?|"
                                     r"ASCO|AACR|ESMO|AHA|ACC|ADA\b", re.I)),
]


def classify_type(text: str) -> str | None:
    for label, pat in _TYPE_KEYWORDS:
        if pat.search(text or ""):
            return label
    return None


# ---------------------------------------------------------------- sources
def _from_clinical(horizon_end: date) -> list[dict]:
    df = read_sql("SELECT * FROM clinical_trials")
    if df.empty:
        return []
    today = date.today()
    grace = today - relativedelta(days=75)
    out = []
    for _, r in df.iterrows():
        pcd = pd.to_datetime(r["primary_completion_date"], errors="coerce")
        if pd.isna(pcd):
            continue
        d = pcd.date()
        if d < grace or d > horizon_end + relativedelta(months=3):
            continue
        phase = (r["phase"] or "").upper()
        if "P3" in phase:
            ctype = "phase3_readout"
        elif "P2" in phase:
            ctype = "phase2_readout"
        elif "P1" in phase:
            ctype = "phase1_readout"
        else:
            ctype = "trial_completion"
        title = f"{phase or 'Trial'} primary completion: {(r['title'] or '')[:120]}"
        out.append(
            {
                "ticker": r["ticker"], "type": ctype, "title": title, "date": d,
                "confidence": "medium" if r["status"] != "COMPLETED" else "high",
                "source": "clinicaltrials.gov", "url": r["url"],
            }
        )
    return out


def _from_news(horizon_end: date) -> list[dict]:
    df = read_sql("SELECT ticker, title, summary, url, published FROM news")
    if df.empty:
        return []
    df["published"] = pd.to_datetime(df["published"], errors="coerce", utc=True)
    cut = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60)
    df = df[df["published"].isna() | (df["published"] >= cut)]
    if df.empty:
        return []
    today = date.today()
    out = []
    for _, r in df.iterrows():
        text = f"{r['title'] or ''}. {r['summary'] or ''}"
        got = extract_date(text)
        if not got:
            continue
        d, gran = got
        if d < today - relativedelta(days=15) or d > horizon_end + relativedelta(months=6):
            continue
        ctype = classify_type(text)
        if not ctype:
            continue
        conf = {"day": "high", "month": "medium", "quarter": "medium",
                "half": "low", "year": "low"}.get(gran, "low")
        out.append(
            {
                "ticker": r["ticker"], "type": ctype,
                "title": f"(news) {(r['title'] or '')[:130]}", "date": d,
                "confidence": conf, "source": "news-extraction", "url": r["url"],
            }
        )
    return out


def _from_earnings() -> list[dict]:
    df = read_sql("SELECT ticker, next_earnings_date FROM fundamentals "
                  "WHERE next_earnings_date IS NOT NULL")
    out = []
    for _, r in df.iterrows():
        d = pd.to_datetime(r["next_earnings_date"], errors="coerce")
        if pd.isna(d):
            continue
        out.append(
            {
                "ticker": r["ticker"], "type": "earnings",
                "title": "Quarterly earnings", "date": d.date(),
                "confidence": "high", "source": "yfinance", "url": "",
            }
        )
    return out


def _from_manual() -> list[dict]:
    from ..store import get_manual_catalysts

    out = []
    for c in get_manual_catalysts():
        d = pd.to_datetime(c.get("date"), errors="coerce")
        if pd.isna(d) or not c.get("ticker"):
            continue
        out.append(
            {
                "ticker": str(c["ticker"]).upper(),
                "type": str(c.get("type", "other")),
                "title": str(c.get("title", "manual catalyst")),
                "date": d.date(),
                "confidence": str(c.get("confidence", "medium")),
                "source": "manual", "url": str(c.get("url", "")),
            }
        )
    return out


def run() -> dict:
    cfg = load_settings()
    horizon_end = date.today() + relativedelta(months=cfg.horizon_months)
    today = date.today()

    raw = (
        _from_clinical(horizon_end)
        + _from_news(horizon_end)
        + _from_earnings()
        + _from_manual()
    )
    # keep the highest-confidence entry per (ticker, type, ~month)
    best: dict[tuple, dict] = {}
    conf_rank = {"high": 3, "medium": 2, "low": 1}
    for c in raw:
        d: date = c["date"]
        key = (c["ticker"], c["type"], d.year, d.month)
        cur = best.get(key)
        if cur is None or conf_rank.get(c["confidence"], 0) > conf_rank.get(cur["confidence"], 0):
            best[key] = c

    now = datetime.now(timezone.utc)
    rows = []
    for c in best.values():
        d: date = c["date"]
        months_away = (d.year - today.year) * 12 + (d.month - today.month) + (d.day - today.day) / 30.0
        rows.append(
            {
                "id": _mk_id(c["ticker"], c["type"], d, c["title"]),
                "ticker": c["ticker"], "type": c["type"], "title": c["title"][:400],
                "date": d, "months_away": round(months_away, 2),
                "confidence": c["confidence"], "source": c["source"],
                "url": (c["url"] or "")[:256], "created_at": now,
            }
        )

    # replace the whole table (catalysts are fully derived each run)
    from ..db import get_engine
    with get_engine().begin() as conn:
        conn.execute(catalysts.delete())
    n = bulk_upsert(catalysts, rows)
    log.info("catalysts: %d dated catalysts (horizon end %s)", n, horizon_end)
    return {"rows": n}
