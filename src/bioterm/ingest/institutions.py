"""SEC 13F-HR holdings of biotech specialist funds -> ``inst_holdings``.

The funds that live and breathe drug development (Baker Bros, RA Capital,
Perceptive, OrbiMed, ...) file their long equity book every quarter. What they
*initiate* or *add to* - especially several of them in the same quarter - is one
of the better open "smart money" reads on a small biotech; what they exit is the
mirror image. 13F data is 45 days stale by construction, so this is a slow,
confirming signal, not a timing one.

Per fund: EDGAR submissions -> the two most recent 13F-HR periods -> the filing's
information-table XML -> equity positions aggregated per CUSIP. A (fund, period)
already stored is never re-downloaded. CUSIPs map to universe tickers by company
name first (cheap, exact) and OpenFIGI second (free, rate-limited, cached).

No API key. EDGAR fair-access: descriptive User-Agent, <=10 req/s.
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import pandas as pd

from ..config import load_settings
from ..db import (bulk_upsert, cusip_map, get_engine, inst_filers, inst_holdings,
                  read_sql)
from ..httpx_util import get_bytes, get_json, post_json
from ..util import company_core, company_key

log = logging.getLogger("bioterm.ingest.institutions")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik10}.json"
INDEX_JSON = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}"
ENTITY_SEARCH = "https://efts.sec.gov/LATEST/search-index"
OPENFIGI = "https://api.openfigi.com/v3/mapping"
_MIN_INTERVAL = 0.15
# 13F values switched from thousands of dollars to whole dollars for filings
# submitted from 3 Jan 2023 (SEC release 34-95148).
_WHOLE_DOLLARS_FROM = date(2023, 1, 3)


# ---------------------------------------------------------------- parsing
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el.iter():
        if _local(c.tag) == name:
            return c
    return None


def _text(el: ET.Element, name: str) -> str:
    c = _child(el, name)
    return (c.text or "").strip() if c is not None and c.text else ""


def parse_infotable(xml_bytes: bytes, filed: date | None = None) -> list[dict]:
    """13F information table -> one row per CUSIP (long equity only).

    Options (a ``putCall`` element) and principal amounts (notes, ``PRN``) are
    skipped - they are not a shareholder's conviction in the common stock.
    Namespace-agnostic: filers use several prefixes for the same schema.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    scale = 1.0 if (filed is None or filed >= _WHOLE_DOLLARS_FROM) else 1000.0
    agg: dict[str, dict] = {}
    for it in root.iter():
        if _local(it.tag) != "infoTable":
            continue
        if _child(it, "putCall") is not None and _text(it, "putCall"):
            continue
        if (_text(it, "sshPrnamtType") or "SH").upper() != "SH":
            continue
        cusip = _text(it, "cusip").upper()
        if not cusip:
            continue
        try:
            shares = float(_text(it, "sshPrnamt") or 0)
            value = float(_text(it, "value") or 0) * scale
        except ValueError:
            continue
        cur = agg.setdefault(cusip, {"cusip": cusip, "issuer": _text(it, "nameOfIssuer"),
                                     "title_class": _text(it, "titleOfClass"),
                                     "shares": 0.0, "value": 0.0})
        cur["shares"] += shares
        cur["value"] += value
    return list(agg.values())


def latest_13f_filings(submissions: dict, n_periods: int = 2) -> list[dict]:
    """The newest original 13F-HR per reporting period, most recent ``n_periods``."""
    recent = (submissions or {}).get("filings", {}).get("recent", {})
    if not recent:
        return []
    df = pd.DataFrame(recent)
    if df.empty or "form" not in df:
        return []
    df = df[df["form"] == "13F-HR"].copy()
    if df.empty:
        return []
    df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce")
    df["reportDate"] = pd.to_datetime(df["reportDate"], errors="coerce")
    df = df.dropna(subset=["reportDate"]).sort_values("filingDate", ascending=False)
    df = df.drop_duplicates("reportDate", keep="first").sort_values("reportDate",
                                                                    ascending=False)
    return [{"accession": r["accessionNumber"], "period": r["reportDate"].date(),
             "filed": r["filingDate"].date() if pd.notna(r["filingDate"]) else None}
            for _, r in df.head(n_periods).iterrows()]


def pick_infotable(index: dict) -> str | None:
    """The information-table XML in a filing directory listing."""
    items = (index or {}).get("directory", {}).get("item", []) or []
    xmls = [i for i in items if str(i.get("name", "")).lower().endswith(".xml")
            and str(i.get("name", "")).lower() != "primary_doc.xml"]
    if not xmls:
        return None
    named = [i for i in xmls if "info" in str(i.get("name", "")).lower()]
    pool = named or xmls

    def size(i) -> int:
        try:
            return int(i.get("size") or 0)
        except ValueError:
            return 0
    return str(max(pool, key=size)["name"])


# ---------------------------------------------------------------- CIK resolution
def resolve_cik(name: str) -> str | None:
    """Fund name -> CIK via EDGAR's entity index; accepted only when every
    significant word of the configured name appears in the entity name."""
    try:
        data = get_json(ENTITY_SEARCH, params={"keysTyped": name}, min_interval=0.3)
    except Exception as exc:  # noqa: BLE001
        log.warning("entity search failed for %s: %s", name, exc)
        return None
    want = [w for w in company_key(name).split() if len(w) > 2]
    for hit in (data or {}).get("hits", {}).get("hits", []) or []:
        entity = company_key(hit.get("_source", {}).get("entity", ""))
        if want and all(w in entity.split() for w in want):
            log.info("resolved 13F filer %r -> CIK %s (%s)", name, hit.get("_id"), entity)
            return str(int(hit["_id"]))
    log.warning("no confident EDGAR match for fund %r", name)
    return None


# ---------------------------------------------------------------- CUSIP -> ticker
def name_index(secs: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    """(exact key -> ticker, unique core key -> ticker) over the universe."""
    exact: dict[str, str] = {}
    core_counts: dict[str, list[str]] = {}
    for _, r in secs.iterrows():
        k = company_key(r["name"])
        if k:
            exact.setdefault(k, r["ticker"])
        c = company_core(r["name"])
        if c and len(c) >= 4:
            core_counts.setdefault(c, []).append(r["ticker"])
    core = {c: t[0] for c, t in core_counts.items() if len(set(t)) == 1}
    return exact, core


def match_issuer(issuer: str, exact: dict[str, str], core: dict[str, str]) -> str | None:
    k = company_key(issuer)
    if k in exact:
        return exact[k]
    c = company_core(issuer)
    return core.get(c) if c and len(c) >= 4 else None


def openfigi_lookup(cusips: list[str]) -> dict[str, str | None]:
    """CUSIP -> US ticker via OpenFIGI (no key: 10 jobs/request, 25 requests/min)."""
    out: dict[str, str | None] = {}
    for i in range(0, len(cusips), 10):
        batch = cusips[i:i + 10]
        try:
            data = post_json(OPENFIGI, [{"idType": "ID_CUSIP", "idValue": c} for c in batch],
                             min_interval=2.6)
        except Exception as exc:  # noqa: BLE001
            log.warning("openfigi failed (%s) - stopping lookups this run", exc)
            break
        for c, res in zip(batch, data or []):
            tk = None
            for d in (res or {}).get("data", []) or []:
                if d.get("exchCode") in ("US", "UN", "UW", "UQ", "UA", "UR") and d.get("ticker"):
                    tk = str(d["ticker"]).upper()
                    break
            out[c] = tk
    return out


def map_cusips(max_openfigi: int = 60) -> int:
    """Resolve unmapped CUSIPs in ``inst_holdings`` and stamp tickers onto them."""
    hold = read_sql("SELECT DISTINCT cusip, issuer FROM inst_holdings")
    if hold.empty:
        return 0
    known = read_sql("SELECT cusip, ticker, method FROM cusip_map")
    known_map = dict(zip(known["cusip"], known["ticker"])) if not known.empty else {}
    secs = read_sql("SELECT ticker, name FROM securities")
    universe = set(secs["ticker"]) if not secs.empty else set()
    exact, core = name_index(secs) if not secs.empty else ({}, {})
    now = datetime.now(timezone.utc)

    new_rows: list[dict] = []
    figi_needed: list[tuple[str, str]] = []
    for _, r in hold.iterrows():
        if r["cusip"] in known_map:
            continue
        tk = match_issuer(r["issuer"], exact, core)
        if tk:
            new_rows.append({"cusip": r["cusip"], "ticker": tk, "issuer": r["issuer"],
                             "method": "name", "updated_at": now})
        else:
            figi_needed.append((r["cusip"], r["issuer"]))
    if figi_needed and max_openfigi > 0:
        got = openfigi_lookup([c for c, _ in figi_needed[:max_openfigi]])
        issuer_of = dict(figi_needed)
        for c, tk in got.items():
            new_rows.append({"cusip": c, "ticker": tk, "issuer": issuer_of.get(c),
                             "method": "openfigi" if tk else "none", "updated_at": now})
    if new_rows:
        bulk_upsert(cusip_map, new_rows)

    # stamp tickers (universe members only get a ticker; others keep the FIGI
    # ticker too - the Smart money page can surface consensus names outside it)
    cm = read_sql("SELECT cusip, ticker FROM cusip_map WHERE ticker IS NOT NULL")
    if cm.empty:
        return 0
    from sqlalchemy import text

    # one set-based statement (a correlated subquery is portable across SQLite
    # and Postgres) instead of a round trip per CUSIP to Neon
    with get_engine().begin() as conn:
        conn.execute(text(
            "UPDATE inst_holdings SET ticker = (SELECT m.ticker FROM cusip_map m "
            "WHERE m.cusip = inst_holdings.cusip) "
            "WHERE cusip IN (SELECT cusip FROM cusip_map WHERE ticker IS NOT NULL)"))
    mapped_universe = int(cm["ticker"].isin(universe).sum())
    log.info("13F: %d CUSIPs mapped (%d in universe)", len(cm), mapped_universe)
    return len(cm)


# ---------------------------------------------------------------- run
def run(time_budget_s: float | None = None, keep_periods: int = 4) -> dict:
    cfg = load_settings()
    budget = float(time_budget_s or cfg.get("alt_data", "institutions_time_budget_s",
                                            default=240))
    max_figi = int(cfg.get("alt_data", "openfigi_max_lookups", default=60))
    deadline = time.monotonic() + budget
    have = read_sql("SELECT DISTINCT cik, period FROM inst_holdings")
    have_keys = {(str(c), str(p)[:10]) for c, p in zip(have["cik"], have["period"])} \
        if not have.empty else set()

    now = datetime.now(timezone.utc)
    fetched_periods = 0
    filers = 0
    for fund in cfg.funds:
        if time.monotonic() > deadline:
            log.warning("13F: time budget hit after %d funds", filers)
            break
        cik = str(fund.get("cik") or "") or resolve_cik(fund["name"])
        if not cik:
            continue
        cik = str(int(cik))
        try:
            subs = get_json(SUBMISSIONS.format(cik10=f"{int(cik):010d}"),
                            min_interval=_MIN_INTERVAL)
        except Exception as exc:  # noqa: BLE001
            log.warning("13F submissions failed for %s: %s", fund["name"], exc)
            continue
        filers += 1
        filings = latest_13f_filings(subs)
        bulk_upsert(inst_filers, [{
            "cik": cik, "name": subs.get("name") or fund["name"],
            "short_name": fund.get("short") or fund["name"],
            "last_period": filings[0]["period"] if filings else None,
            "last_filed": filings[0]["filed"] if filings else None,
            "checked_at": now}])
        for f in filings:
            if (cik, str(f["period"])) in have_keys:
                continue
            acc = str(f["accession"]).replace("-", "")
            try:
                idx = get_json(INDEX_JSON.format(cik=cik, acc=acc), min_interval=_MIN_INTERVAL)
                name = pick_infotable(idx)
                if not name:
                    log.warning("13F: no information table in %s %s", fund["name"], acc)
                    continue
                xml = get_bytes(DOC_URL.format(cik=cik, acc=acc, name=name),
                                min_interval=_MIN_INTERVAL, timeout=40)
            except Exception as exc:  # noqa: BLE001
                log.warning("13F fetch failed %s %s: %s", fund["name"], acc, exc)
                continue
            rows = [{**h, "id": f"{cik}|{f['period']}|{h['cusip']}", "cik": cik,
                     "period": f["period"], "filed_date": f["filed"],
                     "accession": f["accession"], "fetched_at": now}
                    for h in parse_infotable(xml, f["filed"])]
            bulk_upsert(inst_holdings, rows)
            fetched_periods += 1
            log.info("13F: %s %s -> %d positions", fund.get("short"), f["period"], len(rows))

    # keep the newest `keep_periods` quarters per filer
    df = read_sql("SELECT DISTINCT cik, period FROM inst_holdings")
    if not df.empty:
        df["period"] = pd.to_datetime(df["period"])
        drop = []
        for cik, g in df.groupby("cik"):
            old = g.sort_values("period", ascending=False).iloc[keep_periods:]
            drop.extend((cik, p.date()) for p in old["period"])
        if drop:
            with get_engine().begin() as conn:
                for cik, p in drop:
                    conn.execute(inst_holdings.delete().where(
                        (inst_holdings.c.cik == cik) & (inst_holdings.c.period == p)))

    mapped = map_cusips(max_openfigi=max_figi)
    return {"rows": fetched_periods, "filers": filers, "periods_fetched": fetched_periods,
            "cusips_mapped": mapped}
