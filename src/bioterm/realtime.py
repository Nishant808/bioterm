"""The real-time layer - the "pulse": trading halts, SEC filings within minutes,
wire headlines and big live movers, each explained ("why it moved") and turned
into alerts.

It runs three ways, all sharing one database lease so they never double-fire:
- ``bioterm pulse``   one pass (GitHub Actions ``pulse.yml``, hourly in US hours)
- ``bioterm worker``  a loop every few minutes (Docker / launchd - always on)
- inside the dashboard, a background thread while the app is awake (toggle on
  the Settings page)
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .alerts import register

log = logging.getLogger("bioterm.realtime")

LEASE_KEY = "worker_lease"
STATE_KEY = "worker_state"
MOVERS_KEY = "movers_live"
ME = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"

FILING_KINDS = {  # form prefix -> (alert label, who gets it)
    "424B": ("prospectus supplement (possible raise)", "all"),
    "S-3": ("shelf registration", "all"),
    "S-1": ("registration statement", "all"),
    "SC 13D": ("13D - activist / 5%+ holder", "all"),
    "SCHEDULE 13D": ("13D - activist / 5%+ holder", "all"),
    "8-K": ("8-K", "watchlist"),
    "6-K": ("6-K", "watchlist"),
}
ITEM_NAMES = {"1.01": "material agreement", "1.02": "agreement terminated",
              "2.01": "acquisition/disposition", "2.02": "results",
              "2.05": "restructuring", "3.02": "unregistered equity sale",
              "5.02": "officer/director change", "7.01": "Reg FD", "8.01": "other events"}


# ---------------------------------------------------------------- lease / state
def _meta(key, default=None):
    from .store import get_meta

    return get_meta(key, default)


def _set_meta(key, value):
    from .store import set_meta

    set_meta(key, value)


def acquire_lease(ttl_s: int = 240, owner: str = ME) -> bool:
    """Best-effort single-runner lease in app_meta (the pulse is idempotent, so a
    rare double run only costs a duplicate fetch - alerts are de-duplicated)."""
    now = datetime.now(timezone.utc)
    cur = _meta(LEASE_KEY, {}) or {}
    until = pd.to_datetime(cur.get("until"), utc=True, errors="coerce")
    if cur.get("owner") not in (None, owner) and pd.notna(until) and until > now:
        return False
    _set_meta(LEASE_KEY, {"owner": owner, "until": (now + timedelta(seconds=ttl_s)).isoformat()})
    return (_meta(LEASE_KEY, {}) or {}).get("owner") == owner


def release_lease(owner: str = ME) -> None:
    if (_meta(LEASE_KEY, {}) or {}).get("owner") == owner:
        _set_meta(LEASE_KEY, {"owner": None, "until": None})


def state() -> dict[str, Any]:
    return _meta(STATE_KEY, {}) or {}


# ---------------------------------------------------------------- why it moved
def why(ticker: str, hours: int = 36, limit: int = 6) -> list[dict[str, Any]]:
    """Recent evidence for a move: halts, filings (+AI summaries), headlines
    (+AI events), trial changes - newest first."""
    from .db import read_sql

    t = ticker.upper()
    cut = datetime.now(timezone.utc) - timedelta(hours=hours)
    cs = cut.strftime("%Y-%m-%d %H:%M:%S")
    items: list[dict[str, Any]] = []

    def q(sql, params):
        try:
            return read_sql(sql, params)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    for r in q("SELECT reason, halt_at, resumption_trade_time FROM halts WHERE ticker = :t "
               "AND halt_at >= :c ORDER BY halt_at DESC", {"t": t, "c": cs}).itertuples():
        from .ingest.halts import label

        items.append({"kind": "halt", "when": r.halt_at,
                      "text": f"Trading halt - {label(r.reason)}"
                              + (f", resumed {r.resumption_trade_time}"
                                 if r.resumption_trade_time else ""), "url": None})
    for r in q("SELECT f.form, f.items, f.filed_date, f.fetched_at, f.url, s.summary "
               "FROM filings f LEFT JOIN filing_summaries s ON s.accession = f.id "
               "WHERE f.ticker = :t AND f.filed_date >= :d ORDER BY f.filed_date DESC LIMIT 5",
               {"t": t, "d": (cut.date() - timedelta(days=1)).isoformat()}).itertuples():
        items_txt = ", ".join(ITEM_NAMES.get(i, i) for i in str(r.items or "").split(",") if i)
        summ = str(r.summary).split("\n")[0].lstrip("- ") if isinstance(r.summary, str) else ""
        items.append({"kind": "filing", "when": r.fetched_at or r.filed_date,
                      "text": f"{r.form}" + (f" ({items_txt})" if items_txt else "")
                              + (f": {summ}" if summ else ""), "url": r.url})
    for r in q("SELECT n.title, n.url, n.published, n.source, l.event_type, l.outcome "
               "FROM news n LEFT JOIN news_llm l ON l.id = n.id "
               "WHERE (n.ticker = :t OR n.tickers_csv LIKE :tl) AND n.published >= :c "
               "ORDER BY n.published DESC LIMIT 6", {"t": t, "tl": f"%{t}%", "c": cs}).itertuples():
        from .util import strip_markup

        tag = f" [{r.event_type.replace('_', ' ')}, {r.outcome}]" \
            if isinstance(r.event_type, str) and r.event_type != "other" else ""
        items.append({"kind": "news", "when": r.published,
                      "text": f"{strip_markup(r.title)[:160]}{tag}", "url": r.url})
    for r in q("SELECT kind, nct_id, old, new, detected_at FROM trial_changes WHERE ticker = :t "
               "AND detected_at >= :c ORDER BY detected_at DESC LIMIT 3",
               {"t": t, "c": cs}).itertuples():
        items.append({"kind": "trial", "when": r.detected_at,
                      "text": f"{r.nct_id}: {str(r.kind).replace('_', ' ')} ({r.old} -> {r.new})",
                      "url": f"https://clinicaltrials.gov/study/{r.nct_id}"})
    items.sort(key=lambda i: pd.to_datetime(i["when"], utc=True, errors="coerce")
               if i["when"] is not None else pd.Timestamp.min.tz_localize("UTC"), reverse=True)
    return items[:limit]


def record_movers(min_abs_pct: float = 0.06, limit: int = 30) -> dict[str, Any]:
    """Live quotes for the core universe -> the biggest movers, each with its
    'why', saved for the Market page and the mover alerts."""
    from .db import read_sql
    from .quotes import movers

    uni = read_sql("SELECT ticker FROM securities WHERE tier IS NULL OR tier = 'core'")
    rows = movers(uni["ticker"].tolist(), min_abs_pct=min_abs_pct, limit=limit)
    snap = []
    for r in rows:
        snap.append({"ticker": r["ticker"], "price": round(r["price"], 4),
                     "change_pct": round(r["change_pct"], 5), "asof": str(r.get("asof")),
                     "provider": r.get("provider"),
                     "why": [{**w, "when": str(w["when"])[:16]} for w in why(r["ticker"], limit=3)]})
    _set_meta(MOVERS_KEY, {"ts": datetime.now(timezone.utc).isoformat(), "movers": snap})
    return {"rows": len(snap)}


# ---------------------------------------------------------------- pulse
def pulse(deliver: bool = True, movers_: bool = True) -> dict[str, Any]:
    from . import alerts
    from .ingest import edgar_live, halts, news
    from .pipeline import run_job

    t0 = time.monotonic()
    out: dict[str, Any] = {}
    out["halts"] = run_job("halts", halts.run)
    out["filings_live"] = run_job("filings_live", edgar_live.run)
    out["wires"] = run_job("wires", news.run, None, False, ("wire",))
    if movers_:
        out["movers"] = run_job("movers", record_movers)
    out["alerts"] = run_job("alerts", alerts.run, deliver)
    out["seconds"] = round(time.monotonic() - t0, 1)
    _set_meta(STATE_KEY, {"last_run": datetime.now(timezone.utc).isoformat(), "by": ME,
                          "seconds": out["seconds"],
                          "new_alerts": (out["alerts"] or {}).get("new")})
    return out


def worker(interval_s: int = 300, once: bool = False) -> None:
    """Loop the pulse during the US session (07:00-20:00 New York on trading
    days), sleeping otherwise. Safe to run next to the Actions pulse."""
    from .market_calendar import gate

    while True:
        if gate("pulse") and acquire_lease(ttl_s=interval_s + 60):
            try:
                log.info("pulse: %s", json.dumps(pulse(), default=str)[:500])
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.exception("pulse failed: %s", exc)
        if once:
            return
        time.sleep(interval_s)


# ---------------------------------------------------------------- alert sources
def _recent(sql: str, params: dict) -> pd.DataFrame:
    from .db import read_sql

    try:
        return read_sql(sql, params)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


@register("halt")
def _halt_alerts(rules: dict) -> list[dict]:
    from .ingest.halts import ALERT_CODES, label

    cut = (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    df = _recent("SELECT id, ticker, reason, halt_at, resumption_trade_time FROM halts "
                 "WHERE ticker IS NOT NULL AND halt_at >= :c", {"c": cut})
    out = []
    for r in df.itertuples():
        if str(r.reason).upper() not in ALERT_CODES:
            continue
        t = pd.to_datetime(r.halt_at, utc=True).tz_convert("America/New_York")
        out.append({"kind": "halt", "ticker": r.ticker, "key": r.id,
                    "detail": f"{label(r.reason)} ({r.reason}) at {t:%H:%M} ET"
                              + (f" · resumes {r.resumption_trade_time}"
                                 if r.resumption_trade_time else ""),
                    "weight": 3.0 if r.reason in ("T1", "T12", "H10", "H11") else 1.5})
    return out


@register("filing")
def _filing_alerts(rules: dict) -> list[dict]:
    from .store import get_watchlist

    # default / watchlist / all (core universe) / sector (+ extended tier) / off
    mode = rules.get("filing_alerts", "default")
    if mode == "off":
        return []
    wl = {w["ticker"].upper() for w in get_watchlist()}
    df = _recent("SELECT f.id, f.ticker, f.form, f.items, f.url, s.summary, sec.tier "
                 "FROM filings f LEFT JOIN filing_summaries s ON s.accession = f.id "
                 "LEFT JOIN securities sec ON sec.ticker = f.ticker "
                 "WHERE f.filed_date >= :d", {"d": (datetime.now(timezone.utc).date()
                                                    - timedelta(days=1)).isoformat()})
    out = []
    for r in df.itertuples():
        tier = r.tier if isinstance(r.tier, str) and r.tier else "core"   # NULL/NaN = core
        if mode != "sector" and tier != "core":
            continue          # extended-tier filings are stored and shown, not alerted
        form = str(r.form or "").upper()
        kind = next((v for k, v in FILING_KINDS.items() if form.startswith(k)), None)
        if kind is None:
            continue
        label, who = kind
        if mode == "watchlist" or (mode == "default" and who == "watchlist"):
            if r.ticker not in wl:
                continue
        items = ", ".join(ITEM_NAMES.get(i, i) for i in str(r.items or "").split(",") if i)
        summ = str(r.summary).split("\n")[0].lstrip("- ")[:140] \
            if isinstance(r.summary, str) else ""
        out.append({"kind": "filing", "ticker": r.ticker, "key": r.id,
                    "detail": f"{label}" + (f" · {items}" if items else "")
                              + (f" — {summ}" if summ else ""),
                    "weight": 1.2 if who == "all" else 0.8})
    return out


@register("mover")
def _mover_alerts(rules: dict) -> list[dict]:
    snap = _meta(MOVERS_KEY, {}) or {}
    ts = pd.to_datetime(snap.get("ts"), utc=True, errors="coerce")
    if pd.isna(ts) or datetime.now(timezone.utc) - ts > timedelta(hours=2):
        return []
    thr = float(rules.get("mover_pct", 0.12))
    day = datetime.now(timezone.utc).date().isoformat()
    out = []
    for m in snap.get("movers", []):
        pc = float(m.get("change_pct") or 0)
        if abs(pc) < thr:
            continue
        why_txt = m["why"][0]["text"][:110] if m.get("why") else "no news found yet"
        out.append({"kind": "mover", "ticker": m["ticker"],
                    "key": f"{day}|{'up' if pc > 0 else 'down'}",
                    "detail": f"{pc:+.1%} at ${m['price']:.2f} — {why_txt}",
                    "weight": abs(pc) * 10})
    return out
