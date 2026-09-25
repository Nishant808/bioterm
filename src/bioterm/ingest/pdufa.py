"""PDUFA target-action dates and FDA advisory-committee meetings, straight from
primary sources -> ``news_llm`` rows (kind "pdufa" / "adcom"), which the
catalyst builder turns into dated catalysts.

1. SEC EDGAR full-text search (efts.sec.gov) for filings that mention "PDUFA"
   in the last ``days`` days; each hit for a universe company is fetched and the
   date is read from the sentence around the mention ("PDUFA target action date
   of March 15, 2027"). No key; EDGAR fair-access rules apply.
2. The Federal Register API for FDA advisory-committee "Notice of Meeting"
   documents: the meeting date comes from the notice's DATES field and the
   company from its agenda ("... submitted by Example Therapeutics, Inc.").

Both are deterministic (regex); when an LLM key is set, a hit whose date can't
be read by regex is passed to the model (``ai.complete``, structured output).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

log = logging.getLogger("bioterm.ingest.pdufa")

EFTS = "https://efts.sec.gov/LATEST/search-index"
FR_LIST = "https://www.federalregister.gov/api/v1/documents.json"
FORMS = "8-K,10-Q,10-K,6-K,S-1,S-3,424B5,424B4"

_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_DATE = re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}}),?\s+(20\d\d)\b")
_NUM_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
_PDUFA = re.compile(r"PDUFA|Prescription Drug User Fee Act|target action date|"
                    r"action date|goal date", re.I)
_OLD = re.compile(r"\b(?:from|previous(?:ly)?|prior|original(?:ly)?|formerly)\b", re.I)
_TO_END = re.compile(r"\bto\s*$", re.I)


def _to_date(m: re.Match) -> date | None:
    try:
        if m.re is _NUM_DATE:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
    except ValueError:
        return None


def pdufa_dates(text: str, today: date | None = None) -> list[date]:
    """Every plausible PDUFA date stated in ``text`` (a full date within 250
    characters after a PDUFA / target-action mention, or 80 before it). Dates
    announced as the *old* date of an extension are skipped."""
    today = today or date.today()
    found: list[date] = []
    for m in _PDUFA.finditer(text):
        after = text[m.end(): m.end() + 250]
        before = text[max(0, m.start() - 80): m.start()]
        cands = [(after, x) for x in list(_DATE.finditer(after)) + list(_NUM_DATE.finditer(after))]
        cands += [(before, x) for x in _DATE.finditer(before)]
        for ctx, x in sorted(cands, key=lambda c: c[1].start()):
            d = _to_date(x)
            if d is None:
                continue
            lead = ctx[max(0, x.start() - 40): x.start()]
            if _OLD.search(lead) and not _TO_END.search(lead):
                continue                    # "extended from <old date> to <new date>"
            if today - timedelta(days=15) <= d <= today + timedelta(days=800):
                found.append(d)
                break
    return sorted(set(found))


_SUBMITTED = re.compile(r"(?:submitted|sponsored) by\s+([A-Z][\w&.,'’ \-]{2,90}?)"
                        r"(?:,?\s+(?:for|to|with|in|as)\b|\s*\(|\.\s|;)")


def sponsors(text: str) -> list[str]:
    return [m.group(1).strip(" ,.") for m in _SUBMITTED.finditer(text)]


def _name_index() -> tuple[dict[str, str], list[tuple[str, str]]]:
    from ..db import read_sql
    from ..util import company_core, company_key

    secs = read_sql("SELECT ticker, name FROM securities")
    by_key: dict[str, str] = {}
    core_count: dict[str, int] = {}
    for t, n in zip(secs["ticker"], secs["name"]):
        by_key[company_key(n)] = t
        core_count[company_core(n)] = core_count.get(company_core(n), 0) + 1
    for t, n in zip(secs["ticker"], secs["name"]):
        c = company_core(n)
        if core_count.get(c) == 1 and len(c) >= 4:
            by_key.setdefault(c, t)
    try:
        mols = read_sql("SELECT ticker, name, aliases FROM molecules")
    except Exception:  # noqa: BLE001
        mols = pd.DataFrame(columns=["ticker", "name", "aliases"])
    drugs = []
    for r in mols.itertuples():
        names = [r.name] + [a for a in re.findall(r'"([^"]+)"', str(r.aliases or ""))]
        drugs += [(x.lower(), r.ticker) for x in names if x and len(x) >= 5]
    return by_key, drugs


def match_ticker(names: list[str], text: str, by_key: dict[str, str],
                 drugs: list[tuple[str, str]]) -> str | None:
    from ..util import company_core, company_key

    for n in names:
        for k in (company_key(n), company_core(n)):
            if k in by_key:
                return by_key[k]
    low = text.lower()
    hits = {t for d, t in drugs if re.search(rf"\b{re.escape(d)}\b", low)}
    return hits.pop() if len(hits) == 1 else None


# ---------------------------------------------------------------- EDGAR
def efts_hits(days: int = 45, max_pages: int = 4) -> list[dict[str, Any]]:
    from ..httpx_util import get_json

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    out: list[dict] = []
    for page in range(max_pages):
        data = get_json(EFTS, {"q": '"PDUFA"', "forms": FORMS, "dateRange": "custom",
                               "startdt": start.isoformat(), "enddt": end.isoformat(),
                               "from": page * 100},
                        min_interval=0.3, retries=2, timeout=25)
        hits = ((data or {}).get("hits") or {}).get("hits") or []
        for h in hits:
            src = h.get("_source") or {}
            fname = str(h.get("_id", "")).split(":", 1)[-1]
            ciks = src.get("ciks") or []
            adsh = src.get("adsh") or str(h.get("_id", "")).split(":")[0]
            if not ciks or not adsh or not fname:
                continue
            out.append({"cik": f"{int(ciks[0]):010d}", "adsh": adsh, "file": fname,
                        "form": src.get("form") or src.get("file_type"),
                        "filed": src.get("file_date"),
                        "url": f"https://www.sec.gov/Archives/edgar/data/{int(ciks[0])}/"
                               f"{adsh.replace('-', '')}/{fname}"})
        if len(hits) < 100:
            break
    return out


def run_edgar(days: int = 45, max_fetches: int = 40, budget_s: float = 150) -> dict[str, Any]:
    from ..db import bulk_upsert, news_llm, read_sql
    from ..httpx_util import get_bytes
    from .edgar import _strip_html

    secs = read_sql("SELECT ticker, cik FROM securities WHERE cik IS NOT NULL")
    cmap = {f"{int(c):010d}": t for t, c in zip(secs["ticker"], secs["cik"])
            if str(c).strip().isdigit()}
    done = read_sql("SELECT id FROM news_llm WHERE kind = 'pdufa'")
    # ids are pdufa:<accession>:<n> - the accession is what marks a filing as read
    have = {":".join(str(i).split(":")[:2]) for i in done["id"]} if not done.empty else set()
    hits = [h for h in efts_hits(days) if h["cik"] in cmap]
    t0, rows, fetched, undated = time.monotonic(), [], 0, []
    for h in hits:
        rid = f"pdufa:{h['adsh']}"[:40]
        if rid in have or fetched >= max_fetches or time.monotonic() - t0 > budget_s:
            continue
        try:
            raw = get_bytes(h["url"], min_interval=0.15, retries=1, timeout=25)
        except Exception as exc:  # noqa: BLE001
            log.info("pdufa doc fetch failed %s: %s", h["url"], exc)
            continue
        fetched += 1
        have.add(rid)
        text = re.sub(r"\s+", " ", _strip_html(raw[:3_000_000]))
        ds = pdufa_dates(text)
        if not ds:
            undated.append((h, text))
            continue
        tk = cmap[h["cik"]]
        for i, d in enumerate(ds[:3]):        # one filing can list several products
            rows.append({"id": f"{rid}:{i}"[:40], "kind": "pdufa", "ticker": tk,
                         "event_type": "pdufa_date_set", "outcome": "unknown",
                         "pdufa_date": d,
                         "summary": f"PDUFA date stated in {h['form']} filed {h['filed']}",
                         "confidence": 0.9, "model": "regex",
                         "scored_at": datetime.now(timezone.utc)})
    rows += _llm_dates(undated, cmap)
    if rows:
        bulk_upsert(news_llm, rows)
    return {"rows": len(rows), "hits": len(hits), "fetched": fetched}


def _llm_dates(undated: list, cmap: dict[str, str], limit: int = 6) -> list[dict]:
    """Ask the LLM (when configured and enabled) for PDUFA dates the regex missed."""
    from .. import ai

    if not undated or not ai.available() or not ai.settings()["jobs"].get("pdufa", True):
        return []
    schema = {"type": "object", "additionalProperties": False, "required": ["dates"],
              "properties": {"dates": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["date", "drug"],
                  "properties": {"date": {"type": "string", "format": "date"},
                                 "drug": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}}}}
    out = []
    for h, text in undated[:limit]:
        passages = []
        for m in _PDUFA.finditer(text):
            passages.append(text[max(0, m.start() - 300): m.end() + 400])
            if len(passages) >= 6:
                break
        try:
            res = ai.complete("\n...\n".join(passages), role="bulk", max_tokens=3000,
                              system="Extract every FDA PDUFA target action date these filing "
                                     "excerpts state as the current, upcoming date (not a past or "
                                     "superseded one). Return YYYY-MM-DD; empty list if none.",
                              json_schema=schema, effort="low")
        except Exception as exc:  # noqa: BLE001 - budget, refusal, provider error
            log.info("pdufa llm skipped: %s", exc)
            break
        for d in (res.data or {}).get("dates", []):
            dd = pd.to_datetime(d.get("date"), errors="coerce")
            if pd.notna(dd) and dd.date() >= date.today() - timedelta(days=15):
                out.append({"id": f"pdufa:{h['adsh']}:0"[:40], "kind": "pdufa",
                            "ticker": cmap[h["cik"]], "event_type": "pdufa_date_set",
                            "outcome": "unknown", "pdufa_date": dd.date(),
                            "drug": (d.get("drug") or None) and str(d["drug"])[:120],
                            "summary": f"PDUFA date read from {h['form']} filed {h['filed']}",
                            "confidence": 0.75, "model": res.model[:64],
                            "scored_at": datetime.now(timezone.utc)})
                break
    return out


# ---------------------------------------------------------------- Federal Register
def meeting_date(dates_field: str) -> date | None:
    m = _DATE.search(dates_field or "")
    return _to_date(m) if m else None


def run_adcom(days: int = 120) -> dict[str, Any]:
    from ..db import bulk_upsert, news_llm, read_sql
    from ..httpx_util import get_bytes, get_json

    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    params = [("conditions[agencies][]", "food-and-drug-administration"),
              ("conditions[type][]", "NOTICE"),
              ("conditions[term]", '"advisory committee" "notice of meeting"'),
              ("conditions[publication_date][gte]", since), ("order", "newest"),
              ("per_page", "50")] + [("fields[]", f) for f in
                                     ("title", "dates", "document_number", "html_url",
                                      "raw_text_url", "publication_date")]
    from urllib.parse import urlencode

    data = get_json(f"{FR_LIST}?{urlencode(params)}", min_interval=0.5, retries=2, timeout=25)
    docs = (data or {}).get("results") or []
    done = read_sql("SELECT id FROM news_llm WHERE kind = 'adcom'")
    have = set(done["id"]) if not done.empty else set()
    by_key, drugs = _name_index()
    rows = []
    for d in docs:
        title = str(d.get("title") or "")
        if "Devices" in title and "Drug" not in title:
            continue                                    # device panels: not our universe
        rid = f"fr:{d.get('document_number')}"[:40]
        md = meeting_date(str(d.get("dates") or ""))
        if rid in have or md is None or md < date.today() - timedelta(days=2):
            continue
        text = title
        if d.get("raw_text_url"):
            try:
                text += " " + get_bytes(d["raw_text_url"], min_interval=0.5, retries=1,
                                        timeout=25)[:400_000].decode("utf-8", "ignore")
            except Exception as exc:  # noqa: BLE001
                log.info("fedreg text failed: %s", exc)
        text = re.sub(r"\s+", " ", text)
        tk = match_ticker(sponsors(text), text, by_key, drugs)
        if not tk:
            continue
        drug = re.search(r"for ([A-Za-z][\w\- ]{3,60}?)(?:,| injection| tablets| ophthalmic| "
                         r"for | submitted)", title)
        rows.append({"id": rid, "kind": "adcom", "ticker": tk, "event_type": "adcom_scheduled",
                     "outcome": "unknown", "adcom_date": md,
                     "drug": drug.group(1).strip()[:120] if drug else None,
                     "summary": title[:600], "confidence": 0.9, "model": "regex",
                     "scored_at": datetime.now(timezone.utc)})
    if rows:
        bulk_upsert(news_llm, rows)
    return {"rows": len(rows), "notices": len(docs)}


def run() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in (("edgar", run_edgar), ("adcom", run_adcom)):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 - fail soft, per source
            log.warning("pdufa %s failed: %s", name, exc)
            out[name] = {"error": str(exc)[:200]}
    out["rows"] = sum(v.get("rows", 0) for v in out.values() if isinstance(v, dict))
    return out
