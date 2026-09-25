"""Background AI jobs, run with the data refreshes (``bioterm ai``):

- ``news_events``   headlines -> event type, outcome, drug, indication and any
                    PDUFA / AdCom date (feeds the catalyst calendar and alerts)
- ``filing_summaries`` 8-K / 6-K bodies -> 2-4 bullet summaries + the same event
                    fields
- ``risk_diffs``    what was added to / dropped from the Risk Factors section of
                    each new 10-K / 10-Q versus the previous one (the diff is
                    computed deterministically; the LLM only summarises it)
- ``daily_brief``   the day in one page, delivered to the alert channels

Every job is bounded (items per run), skips work already done, stops at the
daily budget and is a no-op without an LLM key.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from . import AIUnavailable, BudgetExceeded, Refused, available, complete, settings

log = logging.getLogger("bioterm.ai.jobs")

EVENT_TYPES = ["topline_data", "interim_data", "pdufa_date_set", "fda_approval", "fda_crl",
               "fda_other", "adcom_scheduled", "adcom_outcome", "trial_start",
               "enrollment_complete", "trial_halt_or_hold", "trial_discontinued", "financing",
               "partnership_or_licensing", "m_and_a", "earnings", "management_change",
               "legal_or_ip", "other"]
OUTCOMES = ["positive", "negative", "mixed", "neutral", "unknown"]


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


EVENT_FIELDS = {
    "event_type": {"type": "string", "enum": EVENT_TYPES},
    "outcome": {"type": "string", "enum": OUTCOMES,
                "description": "for the company's shareholders"},
    "endpoint_met": _nullable({"type": "boolean"}),
    "drug": _nullable({"type": "string"}),
    "indication": _nullable({"type": "string"}),
    "pdufa_date": _nullable({"type": "string", "format": "date"}),
    "adcom_date": _nullable({"type": "string", "format": "date"}),
    "summary": {"type": "string", "description": "one factual sentence, <= 30 words"},
    "confidence": {"type": "number", "description": "0-1"},
}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


NEWS_SCHEMA = _obj({"items": {"type": "array", "items": _obj(
    {"id": {"type": "string"}, "ticker": {"type": "string"}, **EVENT_FIELDS})}})
FILING_SCHEMA = _obj({**EVENT_FIELDS,
                      "bullets": {"type": "array", "items": {"type": "string"}},
                      "dilutive": {"type": "boolean",
                                   "description": "an equity or convertible raise, ATM, "
                                                  "warrants or a shelf registration"},
                      "material": {"type": "boolean"}})

EXTRACT_SYSTEM = """\
You classify biotech and pharma company news for a monitoring terminal. For each item decide \
what kind of event it reports and whether it is good or bad for that company's shareholders. \
Extract the drug and indication when named, and any FDA PDUFA target action date or advisory \
committee meeting date that the text states explicitly (YYYY-MM-DD; null when not stated or \
only a quarter/half-year is given). Use only the text given. The summary is one factual \
sentence. Confidence reflects how clearly the text supports the classification."""

FILING_SYSTEM = """\
You summarise SEC filings by biotech and pharma companies for a monitoring terminal. Report \
what the filing discloses in 2-4 short factual bullets (numbers, dates, drug names, deal \
terms), then classify it. Use only the filing text. Mark dilutive when it registers or sells \
equity, convertibles, warrants or an at-the-market program."""

RISK_SYSTEM = """\
You compare the Risk Factors section of a company's newest SEC report with the previous one. \
Given sentences that were added and removed, say in at most 4 bullets what materially changed \
(new risks, dropped risks, sharpened language about cash, trials, regulators, manufacturing, \
competition, litigation). Ignore reworded boilerplate. Be factual and brief."""

BRIEF_SYSTEM = """\
You write BioTerm's daily brief: a one-page summary of the day for a biotech investor who \
monitors a watchlist and a universe of about 300 names. Use only the JSON facts given. \
Structure: a 2-sentence overview of the sector (XBI regime, breadth), then short sections with \
bullets - Signals that changed, Catalysts ahead (next 14 days), Halts and big movers, Filings \
and news worth reading, Insider and fund activity. Skip empty sections. Tickers in bold. \
Plain factual language; the signals are screening states, not recommendations - never tell \
the reader to buy or sell. At most 350 words."""


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    from ..db import read_sql

    try:
        return read_sql(sql, params or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("ai jobs query failed: %s", exc)
        return pd.DataFrame()


def _date(v) -> date | None:
    if not v:
        return None
    try:
        d = pd.Timestamp(v).date()
    except (ValueError, TypeError):
        return None
    today = datetime.now(timezone.utc).date()
    # a stated regulatory date is recent past or within ~2 years ahead
    return d if today - timedelta(days=30) <= d <= today + timedelta(days=800) else None


def _event_row(rid: str, kind: str, ticker: str, e: dict, model: str) -> dict:
    return {"id": rid[:40], "kind": kind, "ticker": (ticker or "")[:16] or None,
            "event_type": (e.get("event_type") or "other")[:32],
            "outcome": (e.get("outcome") or "unknown")[:12],
            "endpoint_met": None if e.get("endpoint_met") is None else int(bool(e["endpoint_met"])),
            "drug": (e.get("drug") or None) and str(e["drug"])[:120],
            "indication": (e.get("indication") or None) and str(e["indication"])[:200],
            "pdufa_date": _date(e.get("pdufa_date")), "adcom_date": _date(e.get("adcom_date")),
            "summary": str(e.get("summary") or "")[:600],
            "confidence": float(e.get("confidence") or 0), "model": model[:64],
            "scored_at": datetime.now(timezone.utc)}


# keywords that make a headline worth an LLM read (routine PR is skipped)
_WORTH = re.compile(
    r"topline|top-line|phase\s*(?:1|2|3|i|ii|iii)\b|pivotal|primary endpoint|data|results|"
    r"pdufa|fda|approv|complete response|crl|advisory committee|adcom|clinical hold|"
    r"enrol|enroll|discontinu|halt|terminat|offering|private placement|atm|warrant|"
    r"acqui|merger|licens|partner|collaborat|breakthrough|priority review|accelerated|"
    r"guidance|chmp|ema\b", re.I)


def news_events(limit: int = 60, batch: int = 20, days: int = 5) -> dict[str, Any]:
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    df = _q("SELECT n.id, n.ticker, n.title, n.summary, n.source, n.published FROM news n "
            "LEFT JOIN news_llm l ON l.id = n.id WHERE l.id IS NULL AND n.ticker IS NOT NULL "
            "AND n.published >= :c ORDER BY n.published DESC LIMIT 400", {"c": cut})
    if df.empty:
        return {"rows": 0, "scanned": 0}
    from ..util import strip_markup

    df["text"] = (df["title"].map(strip_markup) + ". " +
                  df["summary"].fillna("").map(strip_markup).str.slice(0, 500))
    df = df[df["text"].str.contains(_WORTH)].head(limit)
    rows: list[dict] = []
    model = ""
    for i in range(0, len(df), batch):
        chunk = df.iloc[i:i + batch]
        items = [{"id": r.id, "ticker": r.ticker, "source": r.source,
                  "published": str(r.published)[:10], "text": r.text[:700]}
                 for r in chunk.itertuples()]
        try:
            res = complete(json.dumps({"items": items}, ensure_ascii=False),
                           system=EXTRACT_SYSTEM, role="bulk", max_tokens=8000,
                           json_schema=NEWS_SCHEMA, effort="low")
        except (BudgetExceeded, AIUnavailable) as exc:
            log.info("news events stopped: %s", exc)
            break
        except Refused as exc:
            log.warning("news batch declined (%s) - skipping", exc)
            continue
        model = res.model
        known = {it["id"]: it["ticker"] for it in items}
        for e in (res.data or {}).get("items", []):
            if e.get("id") in known:
                rows.append(_event_row(e["id"], "news", known[e["id"]], e, model))
    if rows:
        from ..db import bulk_upsert, news_llm

        bulk_upsert(news_llm, rows)
    return {"rows": len(rows), "scanned": int(len(df)), "model": model}


# ---------------------------------------------------------------- filings
def _doc_text(url: str, max_bytes: int = 4_000_000) -> str:
    from ..httpx_util import get_bytes
    from ..ingest.edgar import _strip_html

    raw = get_bytes(url, min_interval=0.15, retries=2, timeout=30)
    return re.sub(r"\s+", " ", _strip_html(raw[:max_bytes]))


def filing_summaries(limit: int = 12, days: int = 4) -> dict[str, Any]:
    df = _q("SELECT f.id, f.ticker, f.form, f.filed_date, f.url, f.items FROM filings f "
            "LEFT JOIN filing_summaries s ON s.accession = f.id "
            "WHERE s.accession IS NULL AND f.form IN ('8-K','8-K/A','6-K') "
            "AND f.filed_date >= :c AND f.url LIKE 'https://www.sec.gov/Archives/%' "
            "ORDER BY f.filed_date DESC LIMIT :n",
            {"c": (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat(),
             "n": limit})
    if df.empty:
        return {"rows": 0}
    from ..db import bulk_upsert, filing_summaries as fs_table, news_llm

    done, events = [], []
    for r in df.itertuples():
        try:
            text = _doc_text(r.url)
        except Exception as exc:  # noqa: BLE001
            log.info("filing fetch failed %s: %s", r.id, exc)
            continue
        if len(text) < 200:
            continue
        prompt = (f"Company ticker: {r.ticker}\nForm: {r.form} (items {r.items})\n"
                  f"Filed: {r.filed_date}\n\n{text[:24000]}")
        try:
            res = complete(prompt, system=FILING_SYSTEM, role="bulk", max_tokens=6000,
                           json_schema=FILING_SCHEMA, effort="low")
        except (BudgetExceeded, AIUnavailable) as exc:
            log.info("filing summaries stopped: %s", exc)
            break
        except Refused as exc:
            log.warning("filing %s declined (%s)", r.id, exc)
            continue
        d = res.data or {}
        bullets = [str(b).strip() for b in d.get("bullets") or [] if str(b).strip()]
        flags = []
        if d.get("dilutive"):
            flags.append("dilutive")
        if d.get("material"):
            flags.append("material")
        summary = "\n".join(f"- {b}" for b in bullets[:4])
        if flags:
            summary += f"\n\n_{', '.join(flags)}_"
        done.append({"accession": r.id[:32], "ticker": r.ticker, "form": r.form,
                     "filed_date": r.filed_date, "url": r.url, "summary": summary,
                     "model": res.model[:64], "created_at": datetime.now(timezone.utc)})
        events.append(_event_row(r.id, "filing", r.ticker, d, res.model))
    if done:
        bulk_upsert(fs_table, done)
        bulk_upsert(news_llm, events)
    return {"rows": len(done)}


# ---------------------------------------------------------------- risk factors
_RF_START = re.compile(r"item\s*1a\.?\s*[\-–—:]?\s*risk\s+factors", re.I)
_RF_END = re.compile(r"item\s*(1b|1c|2)\.?\s*[\-–—:]?\s*(unresolved|cybersecurity|properties|"
                     r"unregistered|management)", re.I)


def risk_section(text: str) -> str:
    """The Item 1A Risk Factors section of a 10-K / 10-Q (the longest match - the
    first hit is usually the table of contents)."""
    best = ""
    for m in _RF_START.finditer(text):
        end = _RF_END.search(text, m.end())
        chunk = text[m.end(): end.start() if end else m.end() + 400_000]
        if len(chunk) > len(best):
            best = chunk
    return best


def _sentences(s: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z])", s)
    return [p.strip() for p in parts if 60 <= len(p.strip()) <= 1200]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def diff_risks(old: str, new: str, max_items: int = 40) -> tuple[list[str], list[str]]:
    """Sentences in ``new`` with no close match in ``old`` (added) and vice versa."""
    a, b = _sentences(old), _sentences(new)
    na, nb = {_norm(x) for x in a}, {_norm(x) for x in b}
    added = [x for x in b if _norm(x) not in na]
    removed = [x for x in a if _norm(x) not in nb]

    def novel(cands: list[str], pool: list[str]) -> list[str]:
        out = []
        pool_n = [_norm(p) for p in pool]
        for c in cands:
            cn = _norm(c)
            close = difflib.get_close_matches(cn, pool_n, n=1, cutoff=0.85)
            if not close:
                out.append(c)
            if len(out) >= max_items:
                break
        return out

    return novel(added, a), novel(removed, b)


def risk_diffs(limit: int = 4, days: int = 21) -> dict[str, Any]:
    new = _q("SELECT f.id, f.ticker, f.form, f.filed_date, f.url FROM filings f "
             "LEFT JOIN risk_diffs d ON d.id = f.id WHERE d.id IS NULL "
             "AND f.form IN ('10-K','10-Q') AND f.filed_date >= :c "
             "AND f.url LIKE 'https://www.sec.gov/Archives/%' ORDER BY f.filed_date DESC "
             "LIMIT :n",
             {"c": (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat(),
              "n": limit})
    if new.empty:
        return {"rows": 0}
    from ..db import bulk_upsert, risk_diffs as rd_table

    out = []
    for r in new.itertuples():
        prev = _q("SELECT id, url FROM filings WHERE ticker = :t AND form IN ('10-K','10-Q') "
                  "AND filed_date < :d AND url LIKE 'https://www.sec.gov/Archives/%' "
                  "ORDER BY filed_date DESC LIMIT 1", {"t": r.ticker, "d": r.filed_date})
        if prev.empty:
            continue
        try:
            cur_rf = risk_section(_doc_text(r.url, 12_000_000))
            old_rf = risk_section(_doc_text(prev.iloc[0]["url"], 12_000_000))
        except Exception as exc:  # noqa: BLE001
            log.info("risk-factor fetch failed %s: %s", r.id, exc)
            continue
        if len(cur_rf) < 500 or len(old_rf) < 500:
            continue      # a 10-Q that only refers back to the 10-K
        added, removed = diff_risks(old_rf, cur_rf)
        summary = None
        if (added or removed) and available() and settings()["jobs"].get("risk", True):
            prompt = json.dumps({"ticker": r.ticker, "form": r.form,
                                 "added": added[:25], "removed": removed[:25]})
            try:
                summary = complete(prompt, system=RISK_SYSTEM, role="bulk", max_tokens=3000,
                                   effort="low").text.strip()
            except (BudgetExceeded, AIUnavailable, Refused) as exc:
                log.info("risk summary skipped: %s", exc)
        out.append({"id": r.id[:64], "ticker": r.ticker, "form": r.form,
                    "filed_date": r.filed_date, "prev_accession": str(prev.iloc[0]["id"])[:32],
                    "added": json.dumps(added), "removed": json.dumps(removed),
                    "summary": summary, "url": r.url,
                    "created_at": datetime.now(timezone.utc)})
    if out:
        bulk_upsert(rd_table, out)
    return {"rows": len(out)}


# ---------------------------------------------------------------- daily brief
def brief_facts(day: date | None = None) -> dict[str, Any]:
    """Everything the brief may mention, as compact JSON-able facts."""
    day = day or datetime.now(timezone.utc).date()
    f: dict[str, Any] = {"date": day.isoformat()}
    reg = _q("SELECT regime FROM signal_scores ORDER BY asof DESC LIMIT 1")
    if not reg.empty:
        f["xbi_regime"] = reg.iloc[0]["regime"]
    br = _q("SELECT close, sma50 FROM technicals WHERE date = (SELECT MAX(date) FROM technicals)")
    if not br.empty:
        f["pct_above_50d"] = round(float((br["close"] > br["sma50"]).mean()), 2)
    ch = _q("SELECT a.ticker, a.label, b.label AS prev_label, a.net FROM signal_scores a "
            "LEFT JOIN signal_scores b ON b.ticker = a.ticker AND b.asof = "
            "(SELECT MAX(asof) FROM signal_scores WHERE asof < a.asof) "
            "WHERE a.asof = (SELECT MAX(asof) FROM signal_scores) "
            "AND (b.label IS NULL OR b.label <> a.label) AND a.label <> 'NEUTRAL' "
            "ORDER BY ABS(a.net) DESC LIMIT 12")
    f["signal_changes"] = ch.to_dict("records")
    cats = _q("SELECT ticker, type, date, title FROM catalysts WHERE date >= :a AND date <= :b "
              "ORDER BY date LIMIT 25",
              {"a": day.isoformat(), "b": (day + timedelta(days=14)).isoformat()})
    f["catalysts_next_14d"] = [{**r, "date": str(r["date"])[:10], "title": str(r["title"])[:140]}
                               for r in cats.to_dict("records")]
    cut = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
    h = _q("SELECT ticker, reason, halt_at FROM halts WHERE ticker IS NOT NULL "
           "AND halt_at >= :c", {"c": cut})
    f["halts"] = h.astype(str).to_dict("records")
    mv = _q("SELECT ticker, detail FROM alerts_fired WHERE kind = 'mover' AND ts >= :c "
            "ORDER BY ts DESC LIMIT 10", {"c": cut})
    f["movers"] = mv.to_dict("records")
    fs = _q("SELECT ticker, form, summary FROM filing_summaries WHERE created_at >= :c "
            "LIMIT 12", {"c": cut})
    f["filings"] = [{**r, "summary": str(r["summary"])[:400]} for r in fs.to_dict("records")]
    ev = _q("SELECT ticker, event_type, outcome, summary FROM news_llm WHERE scored_at >= :c "
            "AND event_type NOT IN ('other','earnings') AND confidence >= 0.6 "
            "ORDER BY confidence DESC LIMIT 15", {"c": cut})
    f["news_events"] = ev.to_dict("records")
    ins = _q("SELECT ticker, owner, role, value FROM insider_txns WHERE code = 'P' "
             "AND filed_date >= :c ORDER BY value DESC LIMIT 8",
             {"c": (day - timedelta(days=2)).isoformat()})
    f["insider_buys"] = ins.to_dict("records")
    return f


def daily_brief(deliver: bool = True, force: bool = False) -> dict[str, Any]:
    from ..db import briefs, bulk_upsert

    day = datetime.now(timezone.utc).date()
    if not force and not _q("SELECT day FROM briefs WHERE day = :d", {"d": day}).empty:
        return {"rows": 0, "skipped": "already written today"}
    facts = brief_facts(day)
    try:
        res = complete(json.dumps(facts, default=str), system=BRIEF_SYSTEM, role="copilot",
                       max_tokens=6000, effort="medium")
    except (BudgetExceeded, AIUnavailable, Refused) as exc:
        return {"rows": 0, "skipped": str(exc)}
    body = res.text.strip()
    bulk_upsert(briefs, [{"day": day, "body": body, "model": res.model[:64],
                          "created_at": datetime.now(timezone.utc)}])
    sent = {}
    if deliver:
        from ..notify import send_text

        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
        sent = send_text(f"BioTerm daily brief - {day:%b %d}", plain.splitlines()[:60],
                         kind="digest")
    return {"rows": 1, "delivered": sent}


def run(brief: bool = False) -> dict[str, Any]:
    """All enabled jobs, fail-soft. ``brief`` also writes the daily brief."""
    if not available():
        return {"rows": 0, "skipped": "no LLM key"}
    jobs = settings()["jobs"]
    out: dict[str, Any] = {}
    for name, fn in (("news", news_events), ("filings", filing_summaries),
                     ("risk", risk_diffs)):
        if not jobs.get(name, True):
            continue
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 - one job failing mustn't stop the rest
            log.warning("ai job %s failed: %s", name, exc)
            out[name] = {"error": str(exc)[:200]}
    if brief and jobs.get("brief", True):
        try:
            out["brief"] = daily_brief()
        except Exception as exc:  # noqa: BLE001
            out["brief"] = {"error": str(exc)[:200]}
    out["rows"] = sum(v.get("rows", 0) for v in out.values() if isinstance(v, dict))
    return out
