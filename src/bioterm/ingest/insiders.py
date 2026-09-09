"""SEC Form 4 insider transactions -> ``insider_txns``.

Open-market **purchases** by insiders (transaction code ``P``) - especially
clusters, especially ahead of a catalyst - are one of the few genuinely
predictive signals in small biotech. This pulls Form 4s for a bounded set of
tickers (watchlist + top focus names), parses the ownership XML, and stores each
non-derivative transaction.

No API key. EDGAR fair-access: <=10 req/s, descriptive User-Agent.
"""
from __future__ import annotations

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pandas as pd

from ..db import bulk_upsert, get_engine, insider_txns, read_sql
from ..httpx_util import get_bytes, get_json
from . import edgar

log = logging.getLogger("bioterm.ingest.insiders")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik10}.json"
_MIN_INTERVAL = 0.15


def _mk_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:48]


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _role(root: ET.Element) -> str:
    def g(tag):
        e = root.find(f".//reportingOwnerRelationship/{tag}")
        return (e.text or "").strip() if e is not None else ""
    bits = []
    if g("isDirector") in ("1", "true"):
        bits.append("Director")
    if g("isOfficer") in ("1", "true"):
        title = g("officerTitle")
        bits.append(f"Officer:{title}" if title else "Officer")
    if g("isTenPercentOwner") in ("1", "true"):
        bits.append("10% owner")
    return ", ".join(bits) or "insider"


def parse_form4(xml_bytes: bytes, ticker: str, filed_date, url: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    owner_el = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
    owner = (owner_el.text or "").strip() if owner_el is not None else "?"
    role = _role(root)
    now = datetime.now(timezone.utc)
    out = []
    for nd in root.findall(".//nonDerivativeTransaction"):
        code = nd.findtext(".//transactionCoding/transactionCode") or ""
        ad = nd.findtext(".//transactionAmounts/transactionAcquiredDisposedCode/value") or ""
        shares = _f(nd.findtext(".//transactionAmounts/transactionShares/value"))
        price = _f(nd.findtext(".//transactionAmounts/transactionPricePerShare/value"))
        tdate = nd.findtext(".//transactionDate/value")
        if not shares:
            continue
        signed = (shares * (price or 0.0)) * (1 if ad == "A" else -1)
        out.append({
            "id": _mk_id(ticker, url, owner, code, tdate, shares),
            "ticker": ticker,
            "filed_date": filed_date,
            "txn_date": pd.to_datetime(tdate, errors="coerce").date() if tdate else None,
            "owner": owner[:160],
            "role": role[:64],
            "code": code[:4],
            "acquired_disposed": ad[:2],
            "shares": shares,
            "price": price,
            "value": round(signed, 2),
            "url": url[:256],
            "fetched_at": now,
        })
    return out


def _form4_xml_url(cik: str, accession: str, primary_doc: str) -> str:
    accnd = accession.replace("-", "")
    # primary_doc is usually "xslF345X0N/form4.xml" (the rendered view); the raw
    # ownership XML sits at the same dir without the xsl* prefix.
    raw = primary_doc.split("/")[-1] if "/" in primary_doc else primary_doc
    if not raw.endswith(".xml"):
        raw = "form4.xml"
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accnd}/{raw}"


def run(tickers: list[str] | None = None, lookback_days: int = 120,
        max_per_ticker: int = 20, time_budget_s: float = 300.0) -> dict:
    if tickers is None:
        # default: watchlist + top-60 focus names
        from ..store import get_watchlist

        wl = [w["ticker"] for w in get_watchlist()]
        top = read_sql("SELECT ticker FROM scores ORDER BY rank LIMIT 60")
        tickers = list(dict.fromkeys(wl + (top["ticker"].tolist() if not top.empty else [])))

    cmap = edgar.ticker_cik_map()
    cutoff = (datetime.now(timezone.utc) - pd.Timedelta(days=lookback_days)).date()
    deadline = time.monotonic() + time_budget_s
    rows: list[dict] = []
    done = 0

    for tk in tickers:
        if time.monotonic() > deadline:
            log.warning("insiders: hit %.0fs budget after %d tickers", time_budget_s, done)
            break
        cik = cmap.get(tk.upper())
        if not cik:
            continue
        try:
            data = get_json(SUBMISSIONS.format(cik10=cik), min_interval=_MIN_INTERVAL)
        except Exception as exc:  # noqa: BLE001
            log.debug("submissions failed %s: %s", tk, exc)
            continue
        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            continue
        df = pd.DataFrame(recent)
        if df.empty or "form" not in df:
            continue
        df = df[df["form"] == "4"].head(60)
        df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce")
        df = df[df["filingDate"].dt.date >= cutoff].head(max_per_ticker)
        done += 1
        for _, r in df.iterrows():
            url = _form4_xml_url(cik, r["accessionNumber"], r.get("primaryDocument", ""))
            try:
                xml_bytes = get_bytes(url, min_interval=_MIN_INTERVAL)
            except Exception as exc:  # noqa: BLE001
                log.debug("form4 xml failed %s: %s", url, exc)
                continue
            rows.extend(parse_form4(xml_bytes, tk, r["filingDate"].date(), url))

    # replace this batch's tickers cleanly
    if rows:
        touched = sorted({r["ticker"] for r in rows})
        with get_engine().begin() as conn:
            conn.execute(insider_txns.delete().where(insider_txns.c.ticker.in_(touched)))
    n = bulk_upsert(insider_txns, rows)
    log.info("insiders: %d transactions across %d tickers", n, done)
    return {"rows": n, "tickers": done}


def net_open_market(days: int = 90) -> pd.DataFrame:
    """Per-ticker net open-market insider $ (code P buys minus S sells) over `days`."""
    df = read_sql("SELECT * FROM insider_txns WHERE code IN ('P','S')")
    if df.empty:
        return pd.DataFrame(columns=["ticker", "net_value", "n_buyers", "buy_value"])
    df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce")
    df = df[df["txn_date"] >= pd.Timestamp.today() - pd.Timedelta(days=days)]
    out = []
    for tk, g in df.groupby("ticker"):
        buys = g[g["code"] == "P"]
        out.append({
            "ticker": tk,
            "net_value": float(g["value"].sum()),
            "buy_value": float(buys["value"].sum()),
            "n_buyers": int(buys["owner"].nunique()),
        })
    return pd.DataFrame(out)
