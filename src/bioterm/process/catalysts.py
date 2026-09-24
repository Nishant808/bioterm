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

import calendar
import hashlib
import logging
import re
from datetime import date, datetime, timezone
from typing import Callable

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
_QUARTER_WORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_VAGUE_BUCKET = {"early": (2, 15), "mid": (6, 30), "late": (11, 15)}
_GRACE_DAYS = 45  # a date this far in the past is still "the catalyst just happened"


def _mk_id(ticker: str, ctype: str, d: date, title: str) -> str:
    key = f"{ticker}|{ctype}|{d}|{title[:60]}"
    return hashlib.sha1(key.encode()).hexdigest()[:48]


# ---------------------------------------------------------------- date extraction
#
# No single regex tries to do the calendar math. Each shape a catalyst date can
# be written in - an exact day, a quarter, a half, a vague "mid-2026", any of
# those without an explicit year, or "the back half of next year" - gets its own
# small pattern and handler, tried most-specific-first (see ``_DATE_PATTERNS``).
# A date with no stated year resolves to the nearest occurrence that isn't more
# than ``_GRACE_DAYS`` in the past, the same "assume the future" rule
# ``_from_news`` already applies to whatever comes back.
def _clamp_day(year: int, month: int, day: int) -> int:
    """The last real day of the month, if ``day`` overshoots it (e.g. Feb 30)."""
    return min(day, calendar.monthrange(year, month)[1])


def _nearest_future_md(month: int, day: int, today: date, grace_days: int = _GRACE_DAYS) -> date:
    """The next occurrence of ``month``/``day`` not more than ``grace_days`` in the past."""
    day = _clamp_day(today.year, month, day)
    candidate = date(today.year, month, day)
    if candidate < today - relativedelta(days=grace_days):
        candidate = date(today.year + 1, month, _clamp_day(today.year + 1, month, day))
    return candidate


def _relative_year(rel: str | None, today: date) -> int:
    return today.year + 1 if (rel or "").lower() == "next" else today.year


_DAY = r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?"  # "(?!\d)" - never a truncated 4-digit year
_MO = "(" + "|".join(_MONTHS) + ")"
_REL_YEAR = r"(this|next|current)"

_RE_MONTH_DAY_YEAR = re.compile(rf"\b{_MO}\.?\s+{_DAY},?\s+(20\d{{2}})\b", re.I)
_RE_DAY_MONTH_YEAR = re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MO}\.?,?\s+(20\d{{2}})\b", re.I)
_RE_QUARTER_YEAR = re.compile(
    r"\b(?:Q([1-4])|([1-4])Q|(first|second|third|fourth)[\s-]quarter)"
    r"\s*(?:of\s+)?(?:20)?(\d{2})\b", re.I)
_RE_HALF_YEAR = re.compile(
    r"\b(?:(H[12])|(first|second)[\s-]half|([12])H)\s*(?:of\s+)?(?:20)?(\d{2})\b", re.I)
_RE_QUARTER_REL = re.compile(
    rf"\b(?:Q([1-4])|(first|second|third|fourth)[\s-]quarter)\s+of\s+{_REL_YEAR}\s+year\b", re.I)
_RE_HALF_REL = re.compile(
    rf"\b(?:the\s+)?(front|back|first|second|latter)[\s-]half\s+of\s+{_REL_YEAR}\s+year\b"
    rf"|\bH([12])\s+of\s+{_REL_YEAR}\s+year\b", re.I)
_RE_MONTH_DAY = re.compile(rf"\b{_MO}\.?\s+{_DAY}\b(?!\s*,?\s*20\d{{2}})", re.I)
_RE_VAGUE_YEAR = re.compile(r"\b(early|mid|late|end[\s-]of)[\s-]?(20\d{2})\b", re.I)
_RE_VAGUE_REL_YEAR = re.compile(rf"\b(early|mid|late)\s+{_REL_YEAR}\s+year\b", re.I)
_RE_YEAR_END = re.compile(
    r"\bby\s+(?:the\s+end\s+of\s+)?(next\s+)?year[\s-]?end\b"
    r"|\bby\s+(?:the\s+)?end\s+of\s+(next\s+)?(?:the\s+)?year\b", re.I)
_RE_LATER_THIS_YEAR = re.compile(r"\blater\s+this\s+year\b", re.I)
_RE_MONTH_YEAR = re.compile(rf"\b{_MO}\.?\s+(20\d{{2}})\b", re.I)


def _h_month_day_year(m: re.Match, today: date) -> tuple[date, str]:
    mon, day, year = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
    return date(year, mon, _clamp_day(year, mon, day)), "day"


def _h_day_month_year(m: re.Match, today: date) -> tuple[date, str]:
    day, mon, year = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
    return date(year, mon, _clamp_day(year, mon, day)), "day"


def _h_month_day_noyear(m: re.Match, today: date) -> tuple[date, str]:
    mon, day = _MONTHS[m.group(1).lower()], int(m.group(2))
    return _nearest_future_md(mon, day, today), "day"


def _h_quarter_year(m: re.Match, today: date) -> tuple[date, str]:
    q = int(m.group(1) or m.group(2) or _QUARTER_WORD[m.group(3).lower()])
    year = 2000 + int(m.group(4))
    mo, dy = _QUARTER_DATE[q]
    return date(year, mo, dy), "quarter"


def _h_half_year(m: re.Match, today: date) -> tuple[date, str]:
    half = (m.group(1) or m.group(3) or "").upper().replace("H", "")
    if not half:
        half = "1" if m.group(2).lower() == "first" else "2"
    year = 2000 + int(m.group(4))
    return (date(year, 3, 31) if half == "1" else date(year, 9, 30)), "half"


def _h_quarter_rel(m: re.Match, today: date) -> tuple[date, str]:
    q = int(m.group(1) or _QUARTER_WORD[m.group(2).lower()])
    year = _relative_year(m.group(3), today)
    mo, dy = _QUARTER_DATE[q]
    return date(year, mo, dy), "quarter"


def _h_half_rel(m: re.Match, today: date) -> tuple[date, str]:
    # two alternatives share one group numbering: "back half of next year" fills
    # groups 1-2 (word, rel-year); "H2 of next year" fills groups 3-4 (digit, rel-year)
    word, h_token = m.group(1), m.group(3)
    rel = m.group(2) or m.group(4)
    half = h_token if h_token else ("2" if (word or "").lower() in ("second", "back", "latter") else "1")
    year = _relative_year(rel, today)
    return (date(year, 3, 31) if half == "1" else date(year, 9, 30)), "half"


def _h_vague_year(m: re.Match, today: date) -> tuple[date, str]:
    year = int(m.group(2))
    word = m.group(1).lower().replace(" ", "-")
    bucket = _VAGUE_BUCKET.get(word, (12, 15) if word == "end-of" else (6, 30))
    return date(year, *bucket), "year"


def _h_vague_rel_year(m: re.Match, today: date) -> tuple[date, str]:
    year = _relative_year(m.group(2), today)
    return date(year, *_VAGUE_BUCKET[m.group(1).lower()]), "year"


def _h_year_end(m: re.Match, today: date) -> tuple[date, str]:
    if m.group(1) or m.group(2):  # "next year(-)end" / "end of next year"
        return date(today.year + 1, 12, 15), "year"
    return _nearest_future_md(12, 15, today), "year"


def _h_later_this_year(m: re.Match, today: date) -> tuple[date, str]:
    return date(today.year, 11, 15), "year"


def _h_month_year(m: re.Match, today: date) -> tuple[date, str]:
    return date(int(m.group(2)), _MONTHS[m.group(1).lower()], 15), "month"


# Priority order: exact days beat quarters beat halves beat vague years, and a
# stated year always beats one we have to infer relative to ``today``.
_DATE_PATTERNS: list[tuple[re.Pattern, Callable[[re.Match, date], tuple[date, str]]]] = [
    (_RE_MONTH_DAY_YEAR, _h_month_day_year),
    (_RE_DAY_MONTH_YEAR, _h_day_month_year),
    (_RE_QUARTER_YEAR, _h_quarter_year),
    (_RE_HALF_YEAR, _h_half_year),
    (_RE_QUARTER_REL, _h_quarter_rel),
    (_RE_HALF_REL, _h_half_rel),
    (_RE_MONTH_DAY, _h_month_day_noyear),
    (_RE_VAGUE_YEAR, _h_vague_year),
    (_RE_VAGUE_REL_YEAR, _h_vague_rel_year),
    (_RE_YEAR_END, _h_year_end),
    (_RE_LATER_THIS_YEAR, _h_later_this_year),
    (_RE_MONTH_YEAR, _h_month_year),
]


def extract_date(text: str, today: date | None = None) -> tuple[date, str] | None:
    """Return (date, granularity) for the first future-ish date found, else None.

    Tries the most specific shape first, so "Q4 2026 ... PDUFA date of March 15,
    2027" resolves to the day-level date actually named rather than whichever
    shape happens to appear first in the text. ``today`` is injectable for
    tests; it defaults to the real date.
    """
    t = text or ""
    today = today or date.today()
    for pat, handler in _DATE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        try:
            return handler(m, today)
        except (ValueError, KeyError):
            continue
    return None


# ---------------------------------------------------------------- catalyst type
#
# Weighted, not first-match: a headline naming several trial phases in passing
# ("Phase 3 topline supports the March 15 PDUFA date") should classify by the
# rarer, more decisive signal (PDUFA) rather than whichever category happened
# to be listed first. Weight = how specific/rare the keyword is; score sums
# weight over every hit so a category mentioned twice can still out-rank one
# mentioned once with a slightly higher per-hit weight only when that's
# actually warranted.
_TYPE_KEYWORDS: list[tuple[str, re.Pattern, float]] = [
    ("pdufa", re.compile(r"\bPDUFA\b|\btarget action date\b|\baction date\b", re.I), 3.0),
    ("adcom", re.compile(r"advisory committee|\bAdCom\b|\bODAC\b|\bpanel\b", re.I), 2.6),
    ("fda_action", re.compile(
        r"complete response letter|\bCRL\b|FDA decision|approval decision|"
        r"regulatory decision|decision (?:is )?expected|\bBLA\b|\bNDA\b|\bsBLA\b|resubmission",
        re.I), 1.6),
    ("phase3_readout", re.compile(r"phase 3|phase iii|pivotal|registrational", re.I), 1.4),
    ("phase2_readout", re.compile(r"phase 2|phase ii\b", re.I), 1.2),
    ("phase1_readout", re.compile(r"phase 1|phase i\b", re.I), 1.0),
    ("data_presentation", re.compile(r"topline|read ?out|data|results|present(?:ation)?|"
                                     r"ASCO|AACR|ESMO|AHA|ACC|ADA\b", re.I), 0.5),
]


def classify_type(text: str) -> str | None:
    t = text or ""
    best_label, best_score = None, 0.0
    for label, pat, weight in _TYPE_KEYWORDS:
        n = len(pat.findall(t))
        score = weight * n
        if n and score > best_score:
            best_label, best_score = label, score
    return best_label


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


def _from_molecule_trials(horizon_end: date) -> list[dict]:
    """Readouts of tracked molecules' trials run by *any* sponsor - a partnered
    Phase 3 (Merck running Moderna's intismeran) is the holder's catalyst too."""
    try:
        df = read_sql("SELECT t.*, m.name AS molecule FROM molecule_trials t "
                      "JOIN molecules m ON m.id = t.molecule_id")
    except Exception:  # noqa: BLE001 - tables appear with the first molecule run
        return []
    if df.empty:
        return []
    today = date.today()
    grace = today - relativedelta(days=75)
    out = []
    for _, r in df.iterrows():
        pcd = pd.to_datetime(r["primary_completion_date"], errors="coerce")
        if pd.isna(pcd) or not (grace <= pcd.date() <= horizon_end + relativedelta(months=3)):
            continue
        if r["status"] not in ("RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
                               "NOT_YET_RECRUITING", "COMPLETED"):
            continue
        phase = (r["phase"] or "").upper()
        ctype = ("phase3_readout" if "P3" in phase else "phase2_readout" if "P2" in phase
                 else "phase1_readout" if "P1" in phase else "trial_completion")
        out.append({
            "ticker": r["ticker"], "type": ctype,
            "title": f"{r['molecule']} · {phase or 'Trial'} primary completion "
                     f"({r['sponsor']}): {(r['title'] or '')[:100]}",
            "date": pcd.date(),
            "confidence": "medium" if r["status"] != "COMPLETED" else "high",
            "source": "molecule-tracking", "url": r["url"]})
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
        + _from_molecule_trials(horizon_end)
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
