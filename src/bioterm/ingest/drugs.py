"""Launched-drug tracker: loss-of-exclusivity dates (FDA Orange Book) and
adverse-event report trends (openFDA FAERS) for the universe's marketed drugs.

Orange Book data files (monthly ZIP, tilde-delimited):
    https://www.fda.gov/media/76860/download
    products.txt   Ingredient, Trade_Name, Applicant_Full_Name, Appl_Type, Appl_No, Approval_Date ...
    patent.txt     Appl_Type, Appl_No, Product_No, Patent_No, Patent_Expire_Date_Text ...
    exclusivity.txt Appl_Type, Appl_No, Product_No, Exclusivity_Code, Exclusivity_Date
The LOE date of an application is the later of its last listed patent expiry and
its last regulatory exclusivity. Biologics (BLAs) aren't in the Orange Book; for
a BLA approved in the last 12 years BioTerm records approval + 12 years (the US
reference-product exclusivity) as an estimate.

FAERS: quarterly adverse-event report counts per brand name (openFDA
drug/event), for products approved in the last 10 years - a rising count right
after launch is one of the few public reads on uptake.
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

log = logging.getLogger("bioterm.ingest.drugs")

ORANGE_BOOK = "https://www.fda.gov/media/76860/download"
FAERS = "https://api.fda.gov/drug/event.json"


def _dt(s) -> pd.Timestamp:
    s = str(s or "").replace("Approved Prior to", "").strip()
    return pd.to_datetime(s, errors="coerce", format="mixed")


def parse_orange_book(zip_bytes: bytes) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        def rd(name: str) -> pd.DataFrame:
            member = next(n for n in zf.namelist() if n.lower().endswith(name))
            df = pd.read_csv(zf.open(member), sep="~", dtype=str, keep_default_na=False,
                             encoding="latin-1", on_bad_lines="skip")
            df.columns = [c.strip().lower() for c in df.columns]
            return df
        return rd("products.txt"), rd("patent.txt"), rd("exclusivity.txt")


def loe_rows(products: pd.DataFrame, patents: pd.DataFrame, excl: pd.DataFrame,
             applicant_to_ticker) -> list[dict[str, Any]]:
    """Per NDA of a universe applicant: approval, last patent, last exclusivity, LOE."""
    now = datetime.now(timezone.utc)
    products = products[products.get("type", pd.Series("RX", index=products.index))
                        .str.upper().isin(["RX", ""])]
    pat = patents.assign(exp=patents["patent_expire_date_text"].map(_dt))
    pat_max = pat.groupby("appl_no")["exp"].max()
    ex = excl.assign(exp=excl["exclusivity_date"].map(_dt))
    ex_max = ex.groupby("appl_no")["exp"].max()
    rows: dict[str, dict] = {}
    for r in products.itertuples():
        tk = applicant_to_ticker(getattr(r, "applicant_full_name", "") or r.applicant)
        if not tk:
            continue
        key = f"{r.appl_type}|{r.appl_no}"
        appr = _dt(r.approval_date)
        pe = pat_max.get(r.appl_no)
        ee = ex_max.get(r.appl_no)
        cands = [x for x in (pe, ee) if x is not None and pd.notna(x)]
        loe = max(cands) if cands else None
        cur = rows.get(key)
        if cur is None:
            rows[key] = {"id": key[:64], "ticker": tk,
                         "applicant": str(getattr(r, "applicant_full_name", "") or r.applicant)[:200],
                         "trade_name": str(r.trade_name)[:200],
                         "ingredient": str(r.ingredient)[:300], "appl_no": str(r.appl_no)[:16],
                         "approval_date": appr.date() if pd.notna(appr) else None,
                         "patent_expiry": pe.date() if pe is not None and pd.notna(pe) else None,
                         "exclusivity_expiry": ee.date() if ee is not None and pd.notna(ee)
                         else None,
                         "loe_date": loe.date() if loe is not None else None,
                         "fetched_at": now}
        elif pd.notna(appr) and (cur["approval_date"] is None or appr.date() < cur["approval_date"]):
            cur["approval_date"] = appr.date()      # the original approval of the NDA
    return list(rows.values())


def _applicant_matcher():
    from ..db import read_sql
    from .institutions import match_issuer, name_index

    exact, core = name_index(read_sql("SELECT ticker, name FROM securities"))
    return lambda n: match_issuer(n, exact, core)


# fda.gov sits behind a bot filter that answers scripted clients with an "apology"
# HTML page; a plain browser request gets the ZIP
_BROWSER = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "application/zip,*/*;q=0.8"),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.fda.gov/drugs/drug-approvals-and-databases/"
                       "orange-book-data-files"}


def download_orange_book() -> bytes:
    from ..httpx_util import get_bytes

    raw = get_bytes(ORANGE_BOOK, headers=_BROWSER, min_interval=1.0, retries=2, timeout=120)
    if raw[:2] != b"PK":
        raise ValueError("fda.gov returned a web page instead of the Orange Book ZIP "
                         "(bot filter)")
    return raw


def approvals_rows(since_years: int = 15) -> list[dict[str, Any]]:
    """Fallback when the Orange Book is unreachable: the universe's NDA approvals from
    openFDA (already in ``fda_events``) as marketed products without patent dates -
    enough for the drug list and FAERS, with LOE left unknown."""
    from ..db import read_sql

    df = read_sql("SELECT ticker, application_number, brand_name, generic_name, "
                  "sponsor_name, MIN(event_date) AS approved FROM fda_events WHERE "
                  "kind = 'approval' AND application_number LIKE 'NDA%' AND event_date >= :s "
                  "GROUP BY ticker, application_number, brand_name, generic_name, "
                  "sponsor_name", {"s": (date.today() - timedelta(days=365 * since_years))
                                   .isoformat()})
    now = datetime.now(timezone.utc)
    out = []
    for r in df.itertuples():
        appr = pd.to_datetime(r.approved, errors="coerce")
        if pd.isna(appr) or not r.brand_name:
            continue
        out.append({"id": f"NDA|{r.application_number}"[:64], "ticker": r.ticker,
                    "applicant": str(r.sponsor_name or "")[:200] or None,
                    "trade_name": str(r.brand_name)[:200],
                    "ingredient": str(r.generic_name or "")[:300],
                    "appl_no": str(r.application_number)[:16], "approval_date": appr.date(),
                    "patent_expiry": None, "exclusivity_expiry": None, "loe_date": None,
                    "fetched_at": now})
    return out


def run_orange_book() -> dict[str, Any]:
    from ..db import bulk_upsert, loe_calendar, read_sql

    source = "orange_book"
    try:
        products, patents, excl = parse_orange_book(download_orange_book())
        rows = loe_rows(products, patents, excl, _applicant_matcher())
        from sqlalchemy import text

        from ..db import get_engine

        with get_engine().begin() as conn:      # the real file supersedes the fallback
            conn.execute(text("DELETE FROM loe_calendar WHERE id LIKE 'NDA|%'"))
    except Exception as exc:  # noqa: BLE001 - blocked / moved: keep the drug list alive
        log.warning("Orange Book unavailable (%s) - openFDA approvals without LOE dates",
                    exc)
        products, source = pd.DataFrame(), f"openfda-fallback ({str(exc)[:80]})"
        have = set(read_sql("SELECT id FROM loe_calendar")["id"])
        # never overwrite real Orange Book rows with the date-less fallback
        rows = [r for r in approvals_rows() if r["id"] not in have]
    # biologics: approval + 12 years of reference-product exclusivity (estimate)
    bla = read_sql("SELECT ticker, application_number, brand_name, generic_name, "
                   "MIN(event_date) AS approved FROM fda_events WHERE kind = 'approval' "
                   "AND application_number LIKE 'BLA%' GROUP BY ticker, application_number, "
                   "brand_name, generic_name")
    now = datetime.now(timezone.utc)
    for r in bla.itertuples():
        appr = pd.to_datetime(r.approved, errors="coerce")
        if pd.isna(appr) or appr.date() < date.today() - timedelta(days=365 * 12):
            continue
        rows.append({"id": f"BLA|{r.application_number}"[:64], "ticker": r.ticker,
                     "applicant": None, "trade_name": str(r.brand_name or "")[:200],
                     "ingredient": str(r.generic_name or "")[:300],
                     "appl_no": str(r.application_number)[:16], "approval_date": appr.date(),
                     "patent_expiry": None,
                     "exclusivity_expiry": (appr + pd.DateOffset(years=12)).date(),
                     "loe_date": (appr + pd.DateOffset(years=12)).date(), "fetched_at": now})
    n = bulk_upsert(loe_calendar, rows) if rows else 0
    return {"rows": n, "products": int(len(products)), "source": source}


def faers_quarters(payload: dict) -> dict[str, int]:
    """openFDA count=receivedate -> {YYYYQn: reports}."""
    out: dict[str, int] = {}
    for r in (payload or {}).get("results", []) or []:
        d = pd.to_datetime(str(r.get("time")), format="%Y%m%d", errors="coerce")
        if pd.isna(d):
            continue
        k = f"{d.year}Q{(d.month - 1) // 3 + 1}"
        out[k] = out.get(k, 0) + int(r.get("count") or 0)
    return out


def run_faers(max_brands: int = 40, budget_s: float = 90) -> dict[str, Any]:
    from ..db import bulk_upsert, faers_counts, read_sql
    from ..httpx_util import get_json

    since = date.today() - timedelta(days=365 * 10)
    df = read_sql("SELECT ticker, trade_name, approval_date FROM loe_calendar "
                  "WHERE approval_date >= :s AND trade_name IS NOT NULL", {"s": since.isoformat()})
    df = df.drop_duplicates("trade_name").head(max_brands)
    now = datetime.now(timezone.utc)
    rows, t0 = [], time.monotonic()
    start = (date.today() - timedelta(days=365 * 3)).strftime("%Y%m%d")
    for r in df.itertuples():
        if time.monotonic() - t0 > budget_s:
            break
        brand = str(r.trade_name).strip().upper()
        if len(brand) < 3:
            continue
        q = (f'patient.drug.openfda.brand_name:"{brand}" AND '
             f'receivedate:[{start} TO {date.today():%Y%m%d}]')
        try:
            payload = get_json(FAERS, {"search": q, "count": "receivedate"}, min_interval=0.3,
                               retries=1, timeout=20)
        except Exception as exc:  # noqa: BLE001 - 404 = no reports
            log.debug("faers %s: %s", brand, exc)
            continue
        for qk, n in faers_quarters(payload).items():
            rows.append({"brand": brand[:80], "quarter": qk, "ticker": r.ticker,
                         "reports": n, "serious": None, "fetched_at": now})
    if rows:
        bulk_upsert(faers_counts, rows)
    return {"rows": len(rows), "brands": int(df["trade_name"].nunique())}


def run() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in (("orange_book", run_orange_book), ("faers", run_faers)):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("drugs %s failed: %s", name, exc)
            out[name] = {"error": str(exc)[:200]}
    out["rows"] = sum(v.get("rows", 0) for v in out.values() if isinstance(v, dict))
    return out
