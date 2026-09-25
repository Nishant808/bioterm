"""Competitive landscape + read-through.

For the indications the universe's Phase 2/3 programmes target, fetch the other
industry-sponsored Phase 2/3 trials in the same condition from ClinicalTrials.gov
(``landscape_trials``), and map which universe names share an indication.

Read-through: when one of those names makes a big move, halts or stops a trial,
the peers in the same indication get a "read-through" alert - a competitor's
topline, CRL or safety hold often reprices the whole indication.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ..alerts import register

log = logging.getLogger("bioterm.process.landscape")

API = "https://clinicaltrials.gov/api/v2/studies"
_GENERIC = {"healthy", "healthy volunteers", "cancer", "solid tumor", "solid tumors",
            "advanced solid tumors", "neoplasms", "tumors", "disease", "obesity"}


def norm_condition(c: str) -> str:
    c = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 \-]", " ", str(c or "").lower())).strip()
    c = re.sub(r"\b(disease|disorder|syndrome)s?\b$", r"\1", c)
    return c


def universe_conditions(min_phase: str = "P2") -> pd.DataFrame:
    """(ticker, condition) for the universe's active Phase 2/3 trials."""
    from ..db import read_sql

    df = read_sql("SELECT ticker, nct_id, phase, conditions, status FROM clinical_trials "
                  "WHERE status IN ('RECRUITING','ACTIVE_NOT_RECRUITING','NOT_YET_RECRUITING',"
                  "'ENROLLING_BY_INVITATION','COMPLETED')")
    if df.empty:
        return pd.DataFrame(columns=["ticker", "condition"])
    df = df[df["phase"].fillna("").str.contains("P2|P3")]
    rows = []
    for r in df.itertuples():
        for c in str(r.conditions or "").split(";"):
            k = norm_condition(c)
            if len(k) >= 4 and k not in _GENERIC:
                rows.append({"ticker": r.ticker, "condition": k})
    return pd.DataFrame(rows, columns=["ticker", "condition"]).drop_duplicates()


def peers(ticker: str, cond: pd.DataFrame | None = None) -> dict[str, list[str]]:
    """{peer ticker: [shared conditions]} for one name."""
    cond = universe_conditions() if cond is None else cond
    mine = set(cond[cond["ticker"] == ticker]["condition"])
    if not mine:
        return {}
    others = cond[(cond["condition"].isin(mine)) & (cond["ticker"] != ticker)]
    return {t: sorted(g["condition"].unique().tolist()) for t, g in others.groupby("ticker")}


def _fetch_condition(condition: str) -> list[dict[str, Any]]:
    from ..httpx_util import get_json

    params = {"query.cond": condition,
              "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING",
              "filter.advanced": "AREA[Phase](PHASE2 OR PHASE3) AND "
                                 "AREA[LeadSponsorClass]INDUSTRY",
              "fields": "protocolSection.identificationModule,protocolSection.statusModule,"
                        "protocolSection.designModule.phases,"
                        "protocolSection.sponsorCollaboratorsModule.leadSponsor,"
                        "protocolSection.armsInterventionsModule.interventions",
              "pageSize": 100, "countTotal": "false"}
    data = get_json(API, params, min_interval=0.4, retries=2, timeout=25)
    out = []
    for st in (data or {}).get("studies", []) or []:
        ps = st.get("protocolSection", {})
        ident, status = ps.get("identificationModule", {}), ps.get("statusModule", {})
        design = ps.get("designModule", {})
        spons = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
        ints = ps.get("armsInterventionsModule", {}).get("interventions", []) or []
        out.append({
            "nct_id": ident.get("nctId"), "title": ident.get("briefTitle", ""),
            "phase": "/".join(p.replace("PHASE", "P") for p in design.get("phases", []) or []),
            "status": status.get("overallStatus"),
            "sponsor": spons.get("name", ""), "sponsor_class": spons.get("class", ""),
            "primary_completion_date": pd.to_datetime(
                (status.get("primaryCompletionDateStruct") or {}).get("date"),
                errors="coerce"),
            "interventions": "; ".join(i.get("name", "") for i in ints if i.get("name"))[:400],
        })
    return [r for r in out if r["nct_id"]]


def run(max_conditions: int = 40, budget_s: float = 150) -> dict[str, Any]:
    from ..db import bulk_upsert, get_engine, landscape_trials, read_sql
    from ..util import company_key

    cond = universe_conditions()
    if cond.empty:
        return {"rows": 0}
    # the indications most of the universe's late-stage programmes sit in
    top = cond["condition"].value_counts().head(max_conditions).index.tolist()
    secs = read_sql("SELECT ticker, name FROM securities")
    by_key = {company_key(n): t for t, n in zip(secs["ticker"], secs["name"])}
    now = datetime.now(timezone.utc)
    rows, t0, done = [], time.monotonic(), 0
    for c in top:
        if time.monotonic() - t0 > budget_s:
            break
        try:
            trials = _fetch_condition(c)
        except Exception as exc:  # noqa: BLE001
            log.info("landscape %s failed: %s", c, exc)
            continue
        done += 1
        for t in trials:
            pcd = t.pop("primary_completion_date")
            rows.append({**t, "id": f"{c[:70]}|{t['nct_id']}", "condition": c[:160],
                         "sponsor_ticker": by_key.get(company_key(t["sponsor"])),
                         "primary_completion_date": pcd.date() if pd.notna(pcd) else None,
                         "sponsor": t["sponsor"][:256], "title": t["title"],
                         "fetched_at": now})
    if done:
        with get_engine().begin() as conn:
            conn.execute(landscape_trials.delete().where(landscape_trials.c.condition.in_(
                [c[:160] for c in top[:done]])))
        bulk_upsert(landscape_trials, rows)
    return {"rows": len(rows), "conditions": done}


@register("read-through")
def _alerts(rules: dict) -> list[dict]:
    """Big moves / halts / stopped trials -> alerts for peers in the same indication
    that are on the watchlist."""
    from ..store import get_meta, get_watchlist

    wl = {w["ticker"].upper() for w in get_watchlist()}
    if not wl:
        return []
    triggers: dict[str, str] = {}
    snap = get_meta("movers_live", {}) or {}
    ts = pd.to_datetime(snap.get("ts"), utc=True, errors="coerce")
    if pd.notna(ts) and datetime.now(timezone.utc) - ts < timedelta(hours=3):
        for m in snap.get("movers", []):
            if abs(float(m.get("change_pct") or 0)) >= float(rules.get("readthrough_pct", 0.2)):
                why = m["why"][0]["text"][:90] if m.get("why") else "no reason found yet"
                triggers[m["ticker"]] = f"{float(m['change_pct']):+.0%} ({why})"
    from .trial_changes import recent

    tc = recent(days=2)
    for r in tc.itertuples():
        if r.kind in ("suspended", "terminated", "withdrawn") and r.ticker:
            triggers.setdefault(r.ticker, f"trial {r.nct_id} {r.kind}")
    if not triggers:
        return []
    cond = universe_conditions()
    out = []
    day = datetime.now(timezone.utc).date().isoformat()
    for src, what in triggers.items():
        for peer, shared in peers(src, cond).items():
            if peer not in wl:
                continue
            out.append({"kind": "read-through", "ticker": peer, "key": f"{day}|{src}",
                        "detail": f"{src} {what} - shares {', '.join(shared[:2])}",
                        "weight": 1.0})
    return out
