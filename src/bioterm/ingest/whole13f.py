"""Whole-market 13F ownership from the SEC's quarterly Form 13F data sets ->
``inst_ownership`` (one row per universe ticker per quarter).

    https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets

Each ZIP (~85 MB) holds every 13F-HR filed in a three-month window: SUBMISSION
(accession -> filer, period), COVERPAGE (filer name) and INFOTABLE (one row per
position). BioTerm reads the two newest ZIPs, keeps long equity positions in
universe names (CUSIPs mapped by issuer name - the same matcher as the specialist
fund job - plus the cached CUSIP map), and stores for each name and quarter: how
many 13F filers hold it, their shares and value, how many initiated or exited
versus the prior quarter, and the ten largest holders.

A ZIP already processed is skipped (``app_meta.whole13f_done``), so the daily
full run costs one small HTML request until the SEC publishes the next quarter.
Only aggregates are stored - a few hundred rows per quarter, not millions.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Any

import pandas as pd

log = logging.getLogger("bioterm.ingest.whole13f")

PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
ZIP_RE = re.compile(r"(?:https://www\.sec\.gov)?(/files/structureddata/data/form-13f-data-sets/"
                    r"[0-9a-z]+-[0-9a-z]+_form13f\.zip)", re.I)
_MON = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def dataset_urls(html: str) -> list[str]:
    """Data-set ZIP links on the SEC page, newest filing window first."""
    urls = {f"https://www.sec.gov{m.group(1)}" for m in ZIP_RE.finditer(html)}

    def end_key(u: str):
        m = re.search(r"-(\d{2})([a-z]{3})(\d{4})_form13f", u, re.I)
        return (int(m.group(3)), _MON.get(m.group(2).lower(), 0), int(m.group(1))) if m else (0, 0, 0)

    return sorted(urls, key=end_key, reverse=True)


def _read(zf: zipfile.ZipFile, name: str, **kw) -> Any:
    member = next(n for n in zf.namelist() if n.upper().endswith(name))
    return pd.read_csv(zf.open(member), sep="\t", dtype=str, keep_default_na=False,
                       quoting=3, on_bad_lines="skip", **kw)


def aggregate(zip_path: str, cusip_ticker: dict[str, str] | None = None,
              name_matcher=None) -> tuple[pd.DataFrame, str | None]:
    """One data-set ZIP -> per-ticker holdings for its dominant period.
    Returns (frame[ticker, cik, manager, shares, value], period)."""
    with zipfile.ZipFile(zip_path) as zf:
        sub = _read(zf, "SUBMISSION.TSV", usecols=lambda c: c.upper() in
                    {"ACCESSION_NUMBER", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"})
        sub.columns = [c.upper() for c in sub.columns]
        sub = sub[sub["SUBMISSIONTYPE"].str.upper() == "13F-HR"]
        period = sub["PERIODOFREPORT"].mode().iloc[0] if not sub.empty else None
        sub = sub[sub["PERIODOFREPORT"] == period]
        acc_cik = dict(zip(sub["ACCESSION_NUMBER"], sub["CIK"]))
        cov = _read(zf, "COVERPAGE.TSV", usecols=lambda c: c.upper() in
                    {"ACCESSION_NUMBER", "FILINGMANAGER_NAME"})
        cov.columns = [c.upper() for c in cov.columns]
        manager = dict(zip(cov["ACCESSION_NUMBER"], cov["FILINGMANAGER_NAME"]))
        cols = {"ACCESSION_NUMBER", "NAMEOFISSUER", "CUSIP", "VALUE", "SSHPRNAMT",
                "SSHPRNAMTTYPE", "PUTCALL"}
        # pass 1: every CUSIP's issuer name -> universe ticker
        mapping = dict(cusip_ticker or {})
        if name_matcher is not None:
            seen: dict[str, str] = {}
            for ch in _read(zf, "INFOTABLE.TSV", usecols=lambda c: c.upper() in
                            {"CUSIP", "NAMEOFISSUER"}, chunksize=500_000):
                ch.columns = [c.upper() for c in ch.columns]
                for cu, nm in zip(ch["CUSIP"], ch["NAMEOFISSUER"]):
                    if cu not in seen:
                        seen[cu] = nm
            for cu, nm in seen.items():
                if cu not in mapping:
                    tk = name_matcher(nm)
                    if tk:
                        mapping[cu] = tk
        want = {c.upper() for c in mapping}
        # pass 2: long equity positions in mapped CUSIPs, current-period filers
        parts = []
        for ch in _read(zf, "INFOTABLE.TSV", usecols=lambda c: c.upper() in cols,
                        chunksize=500_000):
            ch.columns = [c.upper() for c in ch.columns]
            ch = ch[ch["CUSIP"].str.upper().isin(want) & ch["ACCESSION_NUMBER"].isin(acc_cik)]
            if "PUTCALL" in ch:
                ch = ch[ch["PUTCALL"].str.strip() == ""]
            ch = ch[ch["SSHPRNAMTTYPE"].str.upper().str.strip() == "SH"]
            if not ch.empty:
                parts.append(ch)
    if not parts:
        return pd.DataFrame(columns=["ticker", "cik", "manager", "shares", "value"]), period
    df = pd.concat(parts, ignore_index=True)
    df["ticker"] = df["CUSIP"].str.upper().map({k.upper(): v for k, v in mapping.items()})
    df["cik"] = df["ACCESSION_NUMBER"].map(acc_cik)
    df["manager"] = df["ACCESSION_NUMBER"].map(manager)
    df["shares"] = pd.to_numeric(df["SSHPRNAMT"], errors="coerce")
    df["value"] = pd.to_numeric(df["VALUE"], errors="coerce")
    out = df.groupby(["ticker", "cik", "manager"], as_index=False)[["shares", "value"]].sum()
    return out, period


def summarise(cur: pd.DataFrame, prev: pd.DataFrame | None, period: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = []
    prev = prev if prev is not None else pd.DataFrame(columns=cur.columns)
    for tk, g in cur.groupby("ticker"):
        p = prev[prev["ticker"] == tk]
        cur_ciks, prev_ciks = set(g["cik"]), set(p["cik"])
        top = g.sort_values("value", ascending=False).head(10)
        pmap = dict(zip(p["cik"], p["shares"]))
        rows.append({
            "ticker": tk, "period": pd.to_datetime(period).date(),
            "holders": len(cur_ciks), "shares": float(g["shares"].sum()),
            "value": float(g["value"].sum()),
            "holders_prev": len(prev_ciks) if not p.empty else None,
            "shares_prev": float(p["shares"].sum()) if not p.empty else None,
            "new_holders": len(cur_ciks - prev_ciks) if not p.empty else None,
            "exited_holders": len(prev_ciks - cur_ciks) if not p.empty else None,
            "top_holders": json.dumps([
                {"name": r.manager, "shares": float(r.shares), "value": float(r.value),
                 "change": (float(r.shares - pmap[r.cik]) if r.cik in pmap else "new")}
                for r in top.itertuples()]),
            "computed_at": now})
    return rows


def run(force: bool = False, n: int = 2) -> dict[str, Any]:
    from ..db import bulk_upsert, inst_ownership, read_sql
    from ..httpx_util import get_bytes
    from ..store import get_meta, set_meta
    from .institutions import match_issuer, name_index

    html = get_bytes(PAGE, min_interval=0.5, retries=2, timeout=30).decode("utf-8", "ignore")
    urls = dataset_urls(html)[:n]
    if not urls:
        return {"rows": 0, "note": "no data-set links found"}
    done = get_meta("whole13f_done", {}) or {}
    if not force and done.get("latest") == urls[0]:
        return {"rows": 0, "skipped": "latest data set already processed", "latest": urls[0]}
    secs = read_sql("SELECT ticker, name FROM securities")
    exact, core = name_index(secs)
    cm = read_sql("SELECT cusip, ticker FROM cusip_map WHERE ticker IS NOT NULL")
    known = dict(zip(cm["cusip"], cm["ticker"])) if not cm.empty else {}
    frames: list[tuple[pd.DataFrame, str | None]] = []
    for url in urls:
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            raw = get_bytes(url, min_interval=0.5, retries=2, timeout=300)
            tmp.write(raw)
            tmp.flush()
            del raw
            frames.append(aggregate(tmp.name, known,
                                    lambda nm: match_issuer(nm, exact, core)))
        log.info("13F data set %s: %d universe positions, period %s", url.rsplit("/", 1)[-1],
                 len(frames[-1][0]), frames[-1][1])
    (cur, period) = frames[0]
    prev = frames[1][0] if len(frames) > 1 else None
    rows = summarise(cur, prev, period) if period else []
    if rows:
        bulk_upsert(inst_ownership, rows)
    set_meta("whole13f_done", {"latest": urls[0], "period": period,
                               "at": datetime.now(timezone.utc).isoformat()})
    return {"rows": len(rows), "period": period, "filers": int(cur["cik"].nunique())
            if not cur.empty else 0}

