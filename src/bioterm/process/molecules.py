"""Link each tracked molecule to the evidence already in the database.

Derived, cheap, and run on every refresh (fast and full): headlines and dated
catalysts that name the molecule (by any of its names), plus a one-row status
per molecule - trials, most advanced phase, next readout, 30-day news flow and
tone, publications - for the Molecules page and the signal engine.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from ..db import bulk_upsert, get_engine, molecule_links, molecule_status, read_sql
from ..ingest.molecules import material_trial, norm, terms_for
from ..store import get_molecules

log = logging.getLogger("bioterm.process.molecules")

ACTIVE = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
          "NOT_YET_RECRUITING"}
PHASE_RANK = {"P3": 3, "P2/P3": 3, "P2": 2, "P1/P2": 2, "P1": 1, "EP1": 0.5}


def _lid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:48]


def mentions(text: str, terms: list[str]) -> bool:
    hay = norm(text)
    return any(norm(t) in hay for t in terms if len(norm(t)) >= 4)


def top_phase(phases) -> str | None:
    best, rank = None, -1.0
    for p in phases:
        r = PHASE_RANK.get(str(p), -1)
        if r > rank:
            best, rank = str(p), r
    return best


def run() -> dict:
    mols = get_molecules()
    if not mols:
        return {"rows": 0}
    today = date.today()
    now = datetime.now(timezone.utc)
    status = read_sql("SELECT molecule_id, papers_total, discovered_aliases FROM molecule_status")
    st = status.set_index("molecule_id").to_dict("index") if not status.empty else {}
    trials = read_sql("SELECT * FROM molecule_trials")
    if not trials.empty:
        trials["primary_completion_date"] = pd.to_datetime(trials["primary_completion_date"],
                                                           errors="coerce")
    cut = (now - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
    news = read_sql("SELECT id, ticker, title, summary, url, published, sentiment, event_score "
                    "FROM news WHERE published >= :c", {"c": cut})
    if not news.empty:
        news["published"] = pd.to_datetime(news["published"], utc=True, errors="coerce")
    cats = read_sql("SELECT id, ticker, type, title, date, url FROM catalysts")
    papers = read_sql("SELECT molecule_id, MAX(date) AS last FROM molecule_links "
                      "WHERE kind = 'paper' GROUP BY molecule_id")
    last_paper = {k: pd.to_datetime(v).date() for k, v in zip(papers["molecule_id"], papers["last"])
                  if pd.notna(pd.to_datetime(v, errors="coerce"))} if not papers.empty else {}

    links: list[dict] = []
    rows: list[dict] = []
    for m in mols:
        extra = json.loads((st.get(m["id"], {}) or {}).get("discovered_aliases") or "[]")
        terms = terms_for(m, extra)
        n30, tone = 0, None
        if not news.empty and terms:
            hit = news[[mentions(f"{t} {s or ''}", terms)
                        for t, s in zip(news["title"], news["summary"])]]
            for _, n in hit.iterrows():
                links.append({"id": _lid(m["id"], "news", n["id"]), "molecule_id": m["id"],
                              "kind": "news", "ref_id": n["id"], "title": n["title"],
                              "date": n["published"].date() if pd.notna(n["published"]) else None,
                              "url": n["url"], "detail": json.dumps(
                                  {"ticker": n["ticker"], "sentiment": n["sentiment"],
                                   "event_score": n["event_score"]}), "created_at": now})
            recent = hit[hit["published"] >= pd.Timestamp(now) - pd.Timedelta(days=30)]
            n30 = int(len(recent))
            if n30:
                tone = float(pd.to_numeric(recent["sentiment"], errors="coerce").mean())
        if not cats.empty and terms:
            for _, c in cats[[mentions(t, terms) for t in cats["title"]]].iterrows():
                links.append({"id": _lid(m["id"], "catalyst", c["id"]), "molecule_id": m["id"],
                              "kind": "catalyst", "ref_id": c["id"], "title": c["title"],
                              "date": pd.to_datetime(c["date"]).date(), "url": c["url"],
                              "detail": json.dumps({"type": c["type"], "ticker": c["ticker"]}),
                              "created_at": now})
        tr = trials[trials["molecule_id"] == m["id"]] if not trials.empty else trials
        # the next readout that can move the stock (not an investigator's Phase 4)
        mat = tr[[material_trial(a, b, c) for a, b, c in
                  zip(tr["source"], tr.get("sponsor_class", [None] * len(tr)), tr["phase"])]] \
            if not tr.empty else tr
        future = mat[mat["primary_completion_date"] >= pd.Timestamp(today)] if not mat.empty else mat
        rows.append({
            "molecule_id": m["id"], "ticker": m["ticker"],
            "n_trials": int(len(tr)),
            "n_active": int(tr["status"].isin(ACTIVE).sum()) if not tr.empty else 0,
            "top_phase": top_phase(tr["phase"]) if not tr.empty else None,
            "next_readout": future["primary_completion_date"].min().date()
            if not future.empty else None,
            "n_news_30d": n30, "news_tone_30d": tone,
            "last_paper_date": last_paper.get(m["id"]),
            "updated_at": now,
        })

    ids = [m["id"] for m in mols]
    with get_engine().begin() as conn:
        conn.execute(molecule_links.delete().where(
            molecule_links.c.molecule_id.in_(ids) & molecule_links.c.kind.in_(["news", "catalyst"])))
    bulk_upsert(molecule_links, links)
    bulk_upsert(molecule_status, rows, update_only=[
        "ticker", "n_trials", "n_active", "top_phase", "next_readout", "n_news_30d",
        "news_tone_30d", "last_paper_date", "updated_at"])
    log.info("molecules: %d linked items across %d molecules", len(links), len(mols))
    return {"rows": len(links), "molecules": len(mols)}
