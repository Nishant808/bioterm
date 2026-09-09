"""Clinical pipeline ingestion via ClinicalTrials.gov API v2 -> ``clinical_trials``.

For each company we pull its lead-sponsored interventional studies, most-recently
updated first, and keep the ones that carry catalyst signal (Phase 1-3, with a
primary-completion date that is upcoming or recent). ``process/catalysts.py`` turns
the completion dates into dated catalysts.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import pandas as pd

from ..config import load_settings
from ..db import bulk_upsert, clinical_trials, get_engine, read_sql
from ..httpx_util import get_json
from ..universe import universe_tickers
from ..util import as_text

log = logging.getLogger("bioterm.ingest.clinical")

API = "https://clinicaltrials.gov/api/v2/studies"

_FIELDS = ",".join(
    [
        "protocolSection.identificationModule.nctId",
        "protocolSection.identificationModule.briefTitle",
        "protocolSection.statusModule.overallStatus",
        "protocolSection.statusModule.startDateStruct.date",
        "protocolSection.statusModule.primaryCompletionDateStruct.date",
        "protocolSection.statusModule.completionDateStruct.date",
        "protocolSection.statusModule.lastUpdatePostDateStruct.date",
        "protocolSection.designModule.phases",
        "protocolSection.designModule.studyType",
        "protocolSection.designModule.enrollmentInfo.count",
        "protocolSection.conditionsModule.conditions",
        "protocolSection.armsInterventionsModule.interventions",
        "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    ]
)

_CORP_STOP = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "llc", "plc", "ag", "nv", "n.v.", "sa", "s.a.", "asa", "ab", "oyj", "holdings",
    "holding", "group", "pharmaceuticals", "pharmaceutical", "pharma", "therapeutics",
    "therapeutic", "biosciences", "bioscience", "biopharmaceuticals", "biopharma",
    "sciences", "science", "biotechnology", "biotech", "bio", "genetics", "genomics",
    "medicines", "medicine", "labs", "laboratories", "and", "the", "&",
}


def sponsor_query_name(name: str) -> str:
    """Company legal name -> short token(s) to match against LeadSponsorName."""
    name = as_text(name)
    if not name:
        return ""
    cleaned = re.sub(r"[.,]", " ", name)
    tokens = [t for t in cleaned.split() if t.strip()]
    keep: list[str] = []
    for t in tokens:
        if t.lower() in _CORP_STOP:
            break
        keep.append(t)
        if len(keep) == 2:
            break
    if not keep and tokens:
        keep = tokens[:1]
    return " ".join(keep)


def _d(s) -> "pd.Timestamp | None":
    if not s:
        return None
    return pd.to_datetime(s, errors="coerce")


def fetch_sponsor_trials(query_name: str, max_pages: int = 2, page_size: int = 200) -> list[dict]:
    params = {
        "filter.advanced": f'AREA[LeadSponsorName]"{query_name}"',
        "fields": _FIELDS,
        "sort": "LastUpdatePostDate:desc",
        "pageSize": page_size,
        "countTotal": "false",
    }
    studies: list[dict] = []
    token = None
    for _ in range(max_pages):
        if token:
            params["pageToken"] = token
        data = get_json(API, params=params, min_interval=0.3)
        studies.extend(data.get("studies", []))
        token = data.get("nextPageToken")
        if not token:
            break
    return studies


def _parse(study: dict, ticker: str) -> dict | None:
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    conds = ps.get("conditionsModule", {}).get("conditions", []) or []
    ints = ps.get("armsInterventionsModule", {}).get("interventions", []) or []
    spons = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "")

    nct = ident.get("nctId")
    if not nct:
        return None
    phases = design.get("phases", []) or []
    return {
        "nct_id": nct,
        "ticker": ticker,
        "sponsor": spons,
        "title": ident.get("briefTitle", ""),
        "phase": "/".join(p.replace("PHASE", "P").replace("EARLY_P1", "EP1") for p in phases) or "NA",
        "status": status.get("overallStatus", ""),
        "study_type": design.get("studyType", ""),
        "start_date": _date(status.get("startDateStruct", {}).get("date")),
        "primary_completion_date": _date(status.get("primaryCompletionDateStruct", {}).get("date")),
        "completion_date": _date(status.get("completionDateStruct", {}).get("date")),
        "conditions": "; ".join(conds[:6]),
        "interventions": "; ".join(
            i.get("name", "") for i in ints if i.get("name")
        )[:400],
        "enrollment": _num(design.get("enrollmentInfo", {}).get("count")),
        "last_update_post_date": _date(status.get("lastUpdatePostDateStruct", {}).get("date")),
        "url": f"https://clinicaltrials.gov/study/{nct}",
        "fetched_at": datetime.now(timezone.utc),
    }


# Phase 1 studies that are almost never share-price catalysts
_NON_CATALYST_RE = re.compile(
    r"pharmacokinetic|drug[- ]drug interaction|\bDDI\b|bioequivalence|bioavailability|"
    r"food[- ]effect|mass balance|QT[c]? |thorough qt|relative bioavailability|"
    r"healthy (?:adult )?(?:participants|volunteers|subjects)|hepatic impairment|"
    r"renal impairment|excretion|lactati|breast milk",
    re.I,
)


def _keep(row: dict) -> bool:
    if row["study_type"] and row["study_type"] != "INTERVENTIONAL":
        return False
    ph = row["phase"]
    if ph in ("NA", "P4", ""):
        return False
    active = row["status"] in {
        "RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
        "NOT_YET_RECRUITING", "COMPLETED",
    }
    if not active:
        return False
    # drop clin-pharm Phase 1 housekeeping studies (keep all Phase 2/3)
    if ph in ("P1", "EP1") and _NON_CATALYST_RE.search(row.get("title", "") or ""):
        return False
    return True


def run(tickers: list[str] | None = None) -> dict:
    cfg = load_settings()
    tickers = tickers or universe_tickers()
    max_sponsors = int(cfg.get("ingest", "clinical_max_sponsors_per_run", default=400))

    secs = read_sql("SELECT ticker, name FROM securities")
    name_by_ticker = dict(zip(secs["ticker"], secs["name"])) if not secs.empty else {}

    rows: list[dict] = []
    processed: list[str] = []
    for tk in tickers:
        if len(processed) >= max_sponsors:
            break
        qname = sponsor_query_name(name_by_ticker.get(tk, tk))
        if not qname:
            continue
        try:
            studies = fetch_sponsor_trials(qname)
        except Exception as exc:  # noqa: BLE001
            log.warning("clinical fetch failed for %s (%s): %s", tk, qname, exc)
            continue
        processed.append(tk)
        for st in studies:
            parsed = _parse(st, tk)
            if parsed and _keep(parsed):
                rows.append(parsed)

    # de-dup: a trial can match two tickers (collab); keep first occurrence
    seen: set[str] = set()
    deduped = []
    for r in rows:
        if r["nct_id"] in seen:
            continue
        seen.add(r["nct_id"])
        deduped.append(r)

    # drop trials we previously stored for these sponsors that no longer qualify
    # (status changed, or now filtered as a non-catalyst clin-pharm study)
    if processed:
        keep_ids = {r["nct_id"] for r in deduped}
        engine = get_engine()
        with engine.begin() as conn:
            existing = read_sql(
                "SELECT nct_id, ticker FROM clinical_trials WHERE ticker IN "
                f"({','.join(f':t{i}' for i in range(len(processed)))})",
                {f"t{i}": t for i, t in enumerate(processed)},
            )
            stale = [x for x in existing["nct_id"].tolist() if x not in keep_ids]
            for chunk_start in range(0, len(stale), 500):
                chunk = stale[chunk_start:chunk_start + 500]
                conn.execute(
                    clinical_trials.delete().where(clinical_trials.c.nct_id.in_(chunk))
                )

    n = bulk_upsert(clinical_trials, deduped)
    log.info("clinical: %d trials across %d sponsors (%d stale removed)",
             n, len(processed), len(stale) if processed else 0)
    return {"rows": n, "sponsors": len(processed)}


def _date(s):
    ts = _d(s)
    return ts.date() if ts is not None and not pd.isna(ts) else None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
