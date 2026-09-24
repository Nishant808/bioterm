"""Per-molecule evidence: trials across every sponsor + the literature.

A company's lead-sponsored trials miss partnered programs - Moderna's
intismeran (mRNA-4157/V940) Phase 3s are sponsored by Merck, so they never show
up under MRNA. For each tracked molecule this searches ClinicalTrials.gov by
*intervention name* (all sponsors), fetches any NCT ids the user pinned, and
counts Europe PMC publications. Other names printed on the trial records
("V940", "intismeran autogene") are collected so news and papers match every
alias, not just the one typed into the watchlist.

Bounded: one CT.gov search + one Europe PMC query per molecule (+ pinned ids),
under a wall-clock budget.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

import pandas as pd

from ..config import load_settings
from ..db import (bulk_upsert, get_engine, molecule_links, molecule_status,
                  molecule_trials, read_sql)
from ..httpx_util import get_json
from ..store import get_molecules, sync_molecules_from_watchlist
from .clinical import API, _FIELDS, _parse

log = logging.getLogger("bioterm.ingest.molecules")

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def norm(s: str) -> str:
    """Lower-case alphanumerics only - "mRNA-4157" and "mrna 4157" compare equal."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# Intervention "other names" on CT.gov are free text: besides real aliases
# ("VX-548", "Journavx", "intismeran autogene") they carry arm labels
# ("VX-548 Placebo"), doses ("suzetrigine 100mg") and descriptions ("Seasonal
# influenza vaccine"). Only name-shaped strings may become search terms -
# a generic phrase would link every flu-vaccine headline to the molecule.
_ALIAS_STOP = re.compile(
    r"\b(placebo|matched|matching|without|with|plus|and|or|formerly|previously|study|"
    r"group|regimen|follow|patients?|participants?|vaccines?|therapy|therapies|treatment|"
    r"dose|doses|dosing|arm|cohort|standard|care|vector|profile|oral|injection|infusion|"
    r"tablets?|capsules?|combination|active|control|comparator|drug|product|solution|"
    r"formulation|low|high|part|period|single|multiple|investigational|experimental|"
    r"level|mg|mcg|kg|ml)\b|\d+\s*(mg|mcg|µg|ug|ml)\b", re.I)
_AKA = re.compile(r"(?:formerly|previously|also)\s+(?:known\s+as|called)\s+(.+)", re.I)


def clean_aliases(names, known: list[str] | None = None) -> list[str]:
    """Name-shaped aliases only, de-duplicated against ``known`` (by norm)."""
    seen = {norm(k) for k in (known or [])}
    out: list[str] = []
    for raw in names or []:
        s = re.sub(r"[®™©]", "", str(raw or ""))
        m = _AKA.search(s)
        if m:
            s = m.group(1)
        parts = [s]
        # "suzetrigine (Journavx)" / "X, Y" -> two candidates
        for sep in (r"\(", r"\)", ",", ";", " / "):
            parts = [q for p in parts for q in re.split(sep, p)]
        for p in parts:
            p = " ".join(p.split()).strip(" -.:")
            if not p or len(p.split()) > 3 or _ALIAS_STOP.search(p) or len(norm(p)) < 4:
                continue
            if norm(p) not in seen:
                seen.add(norm(p))
                out.append(p)
    return out


def material_trial(source: str | None, sponsor_class: str | None, phase: str | None) -> bool:
    """Could this trial's readout move the holder's stock? Pinned trials always;
    otherwise industry-run (the company or a partner - not an investigator
    study at a university hospital) and not a Phase 4 / non-phased study."""
    if source == "pinned":
        return True
    ph = phase.upper() if isinstance(phase, str) else ""
    if ph in ("", "NA", "P4"):
        return False
    # unknown class (NULL / NaN from older rows) is given the benefit of the doubt
    cls = sponsor_class.upper() if isinstance(sponsor_class, str) and sponsor_class else "INDUSTRY"
    return cls == "INDUSTRY"


def terms_for(m: dict, discovered: list[str] | None = None) -> list[str]:
    """Search terms for a molecule: its name, aliases, discovered other names.
    Very short tokens are dropped (they match noise)."""
    raw = [m["name"], *m.get("aliases", []),
           *clean_aliases(discovered, [m["name"], *m.get("aliases", [])])]
    out = []
    for t in raw:
        t = str(t).strip()
        if len(norm(t)) >= 4 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


def study_mentions(study: dict, terms: list[str]) -> tuple[bool, list[str]]:
    """Does this CT.gov record really name the molecule? + otherNames seen."""
    ps = study.get("protocolSection", {})
    ints = ps.get("armsInterventionsModule", {}).get("interventions", []) or []
    names = []
    for i in ints:
        names.append(i.get("name", ""))
        names.extend(i.get("otherNames", []) or [])
    title = ps.get("identificationModule", {}).get("briefTitle", "")
    hay = norm(" ".join(names) + " " + title)
    hit = any(norm(t) and norm(t) in hay for t in terms)
    others: list[str] = []
    if hit:
        for i in ints:
            names_i = [i.get("name", "")] + list(i.get("otherNames", []) or [])
            if any(norm(t) in norm(" ".join(names_i)) for t in terms):
                others.extend(n for n in names_i if n)
    return hit, others


def _search_trials(terms: list[str]) -> list[dict]:
    q = " OR ".join(f'"{t}"' for t in terms)
    # _FIELDS already asks for whole intervention objects, otherNames included
    data = get_json(API, params={"query.intr": q, "fields": _FIELDS, "pageSize": 60, "sort": "LastUpdatePostDate:desc",
                                 "countTotal": "false"}, min_interval=0.3)
    return data.get("studies", []) or []


def _fetch_nct(nct: str) -> dict | None:
    try:
        return get_json(f"{API}/{nct}", params={"fields": _FIELDS}, min_interval=0.3)
    except Exception as exc:  # noqa: BLE001
        log.warning("CT.gov %s failed: %s", nct, exc)
        return None


def _papers(terms: list[str]) -> tuple[int, list[dict]]:
    q = " OR ".join(f'"{t}"' for t in terms)
    data = get_json(EUROPE_PMC, params={"query": q, "format": "json", "pageSize": 6,
                                        "sort": "P_PDATE_D desc", "resultType": "lite"},
                    min_interval=0.3)
    res = (data or {}).get("resultList", {}).get("result", []) or []
    return int(data.get("hitCount", 0) or 0), res


def run(time_budget_s: float | None = None) -> dict:
    cfg = load_settings()
    budget = float(time_budget_s or cfg.get("alt_data", "molecules_time_budget_s", default=180))
    deadline = time.monotonic() + budget
    sync_molecules_from_watchlist()
    mols = get_molecules()
    now = datetime.now(timezone.utc)
    prior = read_sql("SELECT molecule_id, discovered_aliases FROM molecule_status")
    prior_alias = {r["molecule_id"]: json.loads(r["discovered_aliases"] or "[]")
                   for _, r in prior.iterrows()} if not prior.empty else {}

    trial_rows: list[dict] = []
    paper_rows: list[dict] = []
    status_rows: list[dict] = []
    done: list[str] = []
    for m in mols:
        if time.monotonic() > deadline:
            log.warning("molecules: time budget hit after %d", len(done))
            break
        terms = terms_for(m, prior_alias.get(m["id"]))
        discovered: list[str] = []
        try:
            studies = _search_trials(terms) if terms else []
        except Exception as exc:  # noqa: BLE001
            log.warning("CT.gov search failed for %s: %s", m["name"], exc)
            studies = []
        kept: dict[str, tuple[dict, str]] = {}
        for st in studies:
            hit, others = study_mentions(st, terms)
            if hit:
                nct = st.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
                if nct:
                    kept[nct] = (st, "search")
                    discovered.extend(others)
        for nct in m.get("nct_ids", []):
            if nct not in kept:
                st = _fetch_nct(nct)
                if st:
                    kept[nct] = (st, "pinned")
        for nct, (st, src) in kept.items():
            row = _parse(st, m["ticker"])
            if not row:
                continue
            row.update({"id": f"{m['id']}|{nct}"[:80], "molecule_id": m["id"],
                        "source": src, "fetched_at": now,
                        "sponsor": (row.get("sponsor") or "")[:256],
                        "sponsor_class": st.get("protocolSection", {})
                        .get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
                        .get("class")})
            trial_rows.append(row)

        disc = clean_aliases(dict.fromkeys(discovered), [m["name"], *m.get("aliases", [])])
        try:
            total, papers = _papers(terms_for(m, disc)) if terms else (0, [])
        except Exception as exc:  # noqa: BLE001
            log.warning("Europe PMC failed for %s: %s", m["name"], exc)
            total, papers = None, []
        for p in papers:
            pid = str(p.get("pmid") or p.get("id") or p.get("doi") or p.get("title"))[:40]
            url = (f"https://europepmc.org/article/{p.get('source', 'MED')}/{p.get('id')}"
                   if p.get("id") else "")
            paper_rows.append({
                "id": f"{m['id']}|paper|{pid}"[:64], "molecule_id": m["id"], "kind": "paper",
                "ref_id": pid, "title": p.get("title"),
                "date": pd.to_datetime(p.get("firstPublicationDate"), errors="coerce").date()
                if p.get("firstPublicationDate") else None,
                "url": url, "detail": json.dumps({"journal": p.get("journalTitle"),
                                                  "authors": (p.get("authorString") or "")[:160],
                                                  "year": p.get("pubYear")}),
                "created_at": now})
        status_rows.append({"molecule_id": m["id"], "ticker": m["ticker"],
                            "papers_total": total, "discovered_aliases": json.dumps(disc),
                            "updated_at": now})
        done.append(m["id"])

    if done:
        with get_engine().begin() as conn:
            conn.execute(molecule_trials.delete().where(molecule_trials.c.molecule_id.in_(done)))
            conn.execute(molecule_links.delete().where(
                molecule_links.c.molecule_id.in_(done) & (molecule_links.c.kind == "paper")))
    bulk_upsert(molecule_trials, trial_rows)
    bulk_upsert(molecule_links, paper_rows)
    bulk_upsert(molecule_status, status_rows,
                update_only=["ticker", "papers_total", "discovered_aliases", "updated_at"])
    log.info("molecules: %d molecules, %d trials, %d papers", len(done), len(trial_rows),
             len(paper_rows))
    return {"rows": len(trial_rows), "molecules": len(done), "papers": len(paper_rows)}
