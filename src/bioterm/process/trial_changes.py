"""Trial change radar: what moved on ClinicalTrials.gov since the last refresh.

``detect(fresh, stored)`` compares freshly fetched records with the ones already
in ``clinical_trials`` and records every material change in ``trial_changes``:

    date_slip / date_pull_in   primary completion moved 30+ days (the readout moved)
    enrollment_complete        recruiting -> active, not recruiting (data is coming)
    started                    not yet recruiting -> recruiting
    completed                  -> completed (primary data should follow)
    suspended / terminated / withdrawn   the trial stopped
    enrollment_change          target enrollment changed 20%+

A record seen for the first time has no baseline and produces nothing. Change
ids hash the trial, field and both values, so re-detecting the same change is a
no-op. The ingest keeps these even for trials it then drops from
``clinical_trials`` (a terminated study no longer qualifies) - that's the point.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ..alerts import register

log = logging.getLogger("bioterm.process.trial_changes")

RECRUITING = {"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"}
STOPPED = {"SUSPENDED": "suspended", "TERMINATED": "terminated", "WITHDRAWN": "withdrawn"}
MATERIAL = {"suspended", "terminated", "withdrawn", "date_slip", "enrollment_complete",
            "completed", "date_pull_in"}


def _cid(nct: str, field: str, old: Any, new: Any) -> str:
    return hashlib.sha1(f"{nct}|{field}|{old}|{new}".encode()).hexdigest()[:48]


def _d(v):
    t = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(t) else t.date()


def diff(old: dict, new: dict) -> list[dict[str, Any]]:
    """Material changes between two versions of one trial record."""
    out: list[dict[str, Any]] = []
    nct = new["nct_id"]
    o_pcd, n_pcd = _d(old.get("primary_completion_date")), _d(new.get("primary_completion_date"))
    if o_pcd and n_pcd and o_pcd != n_pcd:
        days = (n_pcd - o_pcd).days
        if abs(days) >= 30:
            out.append({"field": "primary_completion_date", "old": o_pcd.isoformat(),
                        "new": n_pcd.isoformat(), "days": float(days),
                        "kind": "date_slip" if days > 0 else "date_pull_in"})
    o_st, n_st = str(old.get("status") or ""), str(new.get("status") or "")
    if o_st and n_st and o_st != n_st:
        kind = STOPPED.get(n_st)
        if kind is None:
            if o_st in RECRUITING and n_st == "ACTIVE_NOT_RECRUITING":
                kind = "enrollment_complete"
            elif o_st == "NOT_YET_RECRUITING" and n_st == "RECRUITING":
                kind = "started"
            elif n_st == "COMPLETED":
                kind = "completed"
            else:
                kind = "status_change"
        out.append({"field": "status", "old": o_st, "new": n_st, "days": None, "kind": kind})
    try:
        o_en, n_en = float(old.get("enrollment") or 0), float(new.get("enrollment") or 0)
    except (TypeError, ValueError):
        o_en = n_en = 0.0
    if o_en > 0 and n_en > 0 and abs(n_en - o_en) / o_en >= 0.2:
        out.append({"field": "enrollment", "old": f"{o_en:.0f}", "new": f"{n_en:.0f}",
                    "days": None, "kind": "enrollment_change"})
    for c in out:
        c["nct_id"] = nct
        c["id"] = _cid(nct, c["field"], c["old"], c["new"])
    return out


def detect(fresh: list[dict], stored: pd.DataFrame) -> list[dict[str, Any]]:
    """Changes between freshly fetched trial rows and their stored versions."""
    if not fresh or stored is None or stored.empty:
        return []
    by_id = stored.set_index("nct_id").to_dict("index")
    now = datetime.now(timezone.utc)
    rows = []
    for r in fresh:
        old = by_id.get(r["nct_id"])
        if not old:
            continue
        for c in diff(old, r):
            rows.append({**c, "ticker": r.get("ticker") or old.get("ticker"),
                         "detected_at": now})
    return rows


def record(fresh: list[dict]) -> int:
    """Diff ``fresh`` against ``clinical_trials`` and store new changes."""
    from ..db import bulk_upsert, read_sql, trial_changes

    ids = sorted({r["nct_id"] for r in fresh})
    if not ids:
        return 0
    stored_parts = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        stored_parts.append(read_sql(
            "SELECT nct_id, ticker, status, primary_completion_date, enrollment "
            f"FROM clinical_trials WHERE nct_id IN ({','.join(f':n{j}' for j in range(len(chunk)))})",
            {f"n{j}": n for j, n in enumerate(chunk)}))
    stored = pd.concat(stored_parts, ignore_index=True) if stored_parts else pd.DataFrame()
    changes = detect(fresh, stored)
    if not changes:
        return 0
    known = read_sql("SELECT id FROM trial_changes")
    seen = set(known["id"]) if not known.empty else set()
    new = [c for c in changes if c["id"] not in seen]
    if new:
        bulk_upsert(trial_changes, [{k: (str(v)[:200] if k in ("old", "new") and v is not None
                                         else v) for k, v in c.items()} for c in new])
    log.info("trial radar: %d new changes (%s)", len(new),
             pd.Series([c["kind"] for c in new]).value_counts().to_dict() if new else {})
    return len(new)


def recent(days: int = 30) -> pd.DataFrame:
    from ..db import read_sql

    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        df = read_sql("SELECT c.*, t.phase, t.title FROM trial_changes c "
                      "LEFT JOIN clinical_trials t ON t.nct_id = c.nct_id "
                      "WHERE c.detected_at >= :c ORDER BY c.detected_at DESC", {"c": cut})
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    return df


@register("trial change")
def _alerts(rules: dict) -> list[dict]:
    df = recent(days=2)
    out = []
    for r in df.itertuples():
        if r.kind not in MATERIAL or not r.ticker:
            continue
        if r.kind in ("date_slip", "date_pull_in") and abs(r.days or 0) < 90:
            continue
        label = str(r.kind).replace("_", " ")
        what = f"{r.old} -> {r.new}" if r.field != "status" else f"{r.old} -> {r.new}"
        out.append({"kind": "trial change", "ticker": r.ticker, "key": r.id,
                    "detail": f"{r.nct_id} {label} ({what})"
                              + (f" · {str(r.phase)}" if isinstance(r.phase, str) else ""),
                    "weight": 2.0 if r.kind in STOPPED.values() else 1.0})
    return out
