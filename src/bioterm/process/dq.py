"""Data-quality checks, run after every full refresh -> ``dq_checks`` (rendered on the
Data health page). Each check counts offending rows and keeps a small sample, so a
number that looks off can be traced to its cause without opening the database.

Status: ``ok`` (nothing found), ``warn`` (worth a look), ``fail`` (a source is broken
or the numbers can't be trusted).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

from ..db import bulk_upsert, dq_checks, read_sql

log = logging.getLogger("bioterm.process.dq")

CORE = "(s.tier IS NULL OR s.tier = 'core')"


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return read_sql(sql, params or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("dq query failed: %s", exc)
        return pd.DataFrame()


def _days(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _res(n: int, sample: Any, warn_at: int = 1, fail_at: int | None = None,
         note: str = "") -> dict:
    status = "ok"
    if fail_at is not None and n >= fail_at:
        status = "fail"
    elif n >= warn_at:
        status = "warn"
    return {"status": status, "count": int(n), "sample": sample, "note": note}


def core_size() -> dict:
    n = int(_q("SELECT COUNT(*) AS n FROM securities s WHERE " + CORE).iloc[0]["n"])
    return _res(0 if n >= 100 else 1, {"core_names": n}, fail_at=1,
                note=f"{n} core names" + ("" if n >= 100 else " - XBI holdings fetch broken?"))


def prices_stale() -> dict:
    df = _q("SELECT s.ticker, MAX(p.date) AS last FROM securities s LEFT JOIN prices p "
            "ON p.ticker = s.ticker WHERE " + CORE + " GROUP BY s.ticker")
    if df.empty:
        return _res(1, [], fail_at=1, note="no prices at all")
    last = pd.to_datetime(df["last"], errors="coerce")
    bad = df[last.isna() | (last < pd.Timestamp(_days(7)))]
    return _res(len(bad), bad["ticker"].head(15).tolist(), warn_at=5,
                fail_at=max(20, len(df) // 3),
                note=f"{len(bad)} of {len(df)} core names have no close in 7 days "
                     "(delisted, halted or a download gap)")


def ohlc_invalid() -> dict:
    df = _q("SELECT ticker, date, open, high, low, close FROM prices WHERE date >= :a "
            "AND (high < low OR close > high * 1.001 OR close < low * 0.999 OR close <= 0)",
            {"a": _days(30)})
    return _res(len(df), df.head(10).astype(str).to_dict("records"), warn_at=1, fail_at=50,
                note="bars whose close sits outside their own high-low range")


def price_jumps() -> dict:
    df = _q("SELECT p.ticker, p.date, p.close FROM prices p JOIN securities s ON "
            "s.ticker = p.ticker WHERE p.date >= :a AND " + CORE + " ORDER BY p.ticker, "
            "p.date", {"a": _days(45)})
    if df.empty:
        return _res(0, [], note="no recent core prices")
    df["ret"] = df.groupby("ticker")["close"].pct_change()
    # a 1:5+ reverse split shows as +400%, a forward split as -80%+; real binary moves
    # rarely reach either
    bad = df[(df["ret"] > 2.5) | (df["ret"] < -0.9)]
    return _res(len(bad), bad.head(10).astype(str).to_dict("records"), warn_at=1,
                note=f"{len(bad)} core daily moves above +250% or below -90% - usually a "
                     "split the feed hasn't adjusted")


def fundamentals_cover() -> dict:
    df = _q("SELECT s.ticker, f.market_cap, f.updated_at FROM securities s LEFT JOIN "
            "fundamentals f ON f.ticker = s.ticker WHERE " + CORE)
    if df.empty:
        return _res(0, [])
    upd = pd.to_datetime(df["updated_at"], errors="coerce", utc=True)
    stale = df[df["market_cap"].isna() | upd.isna()
               | (upd < pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=10))]
    return _res(len(stale), stale["ticker"].head(15).tolist(), warn_at=10,
                fail_at=max(40, len(df) // 2),
                note=f"{len(stale)} of {len(df)} core names missing a market cap or not "
                     "refreshed in 10 days")


def runway_outliers() -> dict:
    df = _q("SELECT ticker, cash, burn_ttm, runway_quarters FROM fundamentals "
            "WHERE runway_quarters IS NOT NULL AND (runway_quarters < 0 OR "
            "runway_quarters > 200)")
    return _res(len(df), df.head(10).astype(str).to_dict("records"), warn_at=1,
                note="runway below zero or above 50 years - a units or sign error upstream")


def cik_missing() -> dict:
    df = _q("SELECT s.ticker FROM securities s WHERE " + CORE + " AND (s.cik IS NULL "
            "OR s.cik = '')")
    return _res(len(df), df["ticker"].head(20).tolist() if not df.empty else [], warn_at=15,
                note="core names SEC's ticker file doesn't map (foreign / renamed) - no "
                     "filings, insiders or XBRL for them")


def future_dates() -> dict:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    f = _q("SELECT id, ticker, filed_date FROM filings WHERE filed_date > :d", {"d": tomorrow})
    n = _q("SELECT id, ticker, published FROM news WHERE published > :d", {"d": tomorrow})
    s = pd.concat([f.astype(str), n.astype(str)]).head(10) if not (f.empty and n.empty) \
        else pd.DataFrame()
    return _res(len(f) + len(n), s.to_dict("records") if not s.empty else [], warn_at=1,
                fail_at=20, note="filings or headlines dated in the future (timezone bug)")


def stale_catalysts() -> dict:
    df = _q("SELECT id, ticker, type, date, source FROM catalysts WHERE date < :a",
            {"a": _days(120)})
    return _res(len(df), df.head(10).astype(str).to_dict("records"), warn_at=25,
                note="catalysts more than 4 months past - should have rolled off")


def board_coverage() -> dict:
    core = int(_q("SELECT COUNT(*) AS n FROM securities s WHERE " + CORE).iloc[0]["n"])
    sc = _q("SELECT COUNT(*) AS n FROM scores WHERE asof = (SELECT MAX(asof) FROM scores)")
    sg = _q("SELECT COUNT(*) AS n FROM signal_scores WHERE asof = "
            "(SELECT MAX(asof) FROM signal_scores)")
    n_sc = int(sc.iloc[0]["n"]) if not sc.empty else 0
    n_sg = int(sg.iloc[0]["n"]) if not sg.empty else 0
    worst = min(n_sc, n_sg)
    short = core - worst
    return _res(short if worst < 0.8 * core else 0,
                {"core": core, "scored": n_sc, "signalled": n_sg}, warn_at=1,
                fail_at=max(1, core // 2) if core else None,
                note=f"Focus Score covers {n_sc} and the signal engine {n_sg} of {core} "
                     "core names")


def news_flow() -> dict:
    df = _q("SELECT COUNT(*) AS n FROM news WHERE published >= :a",
            {"a": (datetime.now(timezone.utc) - timedelta(hours=36))
             .strftime("%Y-%m-%d %H:%M:%S")})
    n = int(df.iloc[0]["n"]) if not df.empty else 0
    return _res(1 if n == 0 else 0, {"headlines_36h": n}, warn_at=1,
                note=f"{n} headlines in 36 hours" + (" - every feed silent?" if n == 0 else ""))


def job_failures() -> dict:
    df = _q("SELECT job, started_at, status FROM ingest_runs WHERE started_at >= :a",
            {"a": (datetime.now(timezone.utc) - timedelta(hours=26))
             .strftime("%Y-%m-%d %H:%M:%S")})
    if df.empty:
        return _res(1, [], warn_at=1, note="no job ran in 26 hours - is the schedule on?")
    last = df.sort_values("started_at").groupby("job").last()
    bad = last[last["status"] == "error"]
    return _res(len(bad), bad.index.tolist(), warn_at=1, fail_at=5,
                note=f"{len(bad)} jobs whose latest run failed")


def duplicate_news() -> dict:
    df = _q("SELECT title, COUNT(*) AS n FROM news WHERE published >= :a GROUP BY title "
            "HAVING COUNT(*) > 4 ORDER BY n DESC",
            {"a": (datetime.now(timezone.utc) - timedelta(days=7))
             .strftime("%Y-%m-%d %H:%M:%S")})
    return _res(len(df), df.head(5).astype(str).to_dict("records"), warn_at=3,
                note="the same headline stored 5+ times (syndication the de-dup misses)")


CHECKS: dict[str, Callable[[], dict]] = {
    "core universe size": core_size,
    "stale prices": prices_stale,
    "invalid OHLC bars": ohlc_invalid,
    "unadjusted jumps": price_jumps,
    "fundamentals coverage": fundamentals_cover,
    "runway outliers": runway_outliers,
    "unmapped CIKs": cik_missing,
    "future-dated rows": future_dates,
    "stale catalysts": stale_catalysts,
    "board coverage": board_coverage,
    "news flow": news_flow,
    "failing jobs": job_failures,
    "duplicate headlines": duplicate_news,
}


def run() -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows, summary = [], {"ok": 0, "warn": 0, "fail": 0}
    for name, fn in CHECKS.items():
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001
            r = {"status": "warn", "count": 0, "sample": [], "note": f"check crashed: {exc}"}
        summary[r["status"]] = summary.get(r["status"], 0) + 1
        detail = r["note"] + (f" · e.g. {json.dumps(r['sample'], default=str)[:600]}"
                              if r["sample"] and r["status"] != "ok" else "")
        rows.append({"run_at": now, "check": name[:48], "status": r["status"],
                     "count": r["count"], "detail": detail[:2000]})
    bulk_upsert(dq_checks, rows)
    log.info("dq: %s", summary)
    return {"rows": len(rows), **summary}


def latest() -> pd.DataFrame:
    return _q('SELECT run_at, "check", status, count, detail FROM dq_checks '
              "WHERE run_at = (SELECT MAX(run_at) FROM dq_checks)")


def notify_failures() -> dict:
    """Send the failing checks to the channels routed for "dq" (Settings / Alerts)."""
    from .. import notify

    df = latest()
    bad = df[df["status"] == "fail"] if not df.empty else df
    if bad.empty:
        return {}
    lines = [f"{r.check}: {str(r.detail or '')[:220]}" for r in bad.itertuples()]
    return notify.send_text(f"BioTerm data check failed ({len(bad)})", lines, kind="dq")
