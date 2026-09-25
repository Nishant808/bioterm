"""Catalyst outcome database + base rates + implied vs realized moves.

Every past catalyst BioTerm can date goes into ``catalyst_events`` with how the
stock traded around it:

    ret_pre60   the run-up: close the day before the event vs 60 sessions earlier
    ret_1d      the reaction: a 2-session window (event day and the next), so a
                pre-market and an after-hours release are both caught
    ret_5d / ret_21d   the follow-through; xret_* are the same minus XBI

Sources: original FDA approvals (openFDA, ``fda_events``); topline readouts,
CRLs, approvals and holds read from headlines and 8-Ks (``news_llm``); and a
historical backfill of company "topline" 8-K press releases found through SEC
full-text search, classified positive/negative with the event lexicon
(``efts_toplines`` - bounded per run, it walks back three years over a few runs).

``base_rates()`` summarises them by event kind and direction (the classic
"run-up, then sell the news" pattern included) and is stored as the "outcomes"
row of ``backtests``. ``implied_vs_realized()`` sets each upcoming binary
catalyst's options-implied move beside the moves this name and its peers
actually made on past events.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("bioterm.process.outcomes")

BUCKETS = [(10e9, "large"), (2e9, "mid"), (3e8, "small"), (0, "micro")]
LLM_KINDS = {"topline_data": "topline", "interim_data": "topline", "fda_approval": "approval",
             "fda_crl": "crl", "adcom_outcome": "adcom", "trial_halt_or_hold": "hold"}


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:40]


def bucket(mcap) -> str | None:
    try:
        m = float(mcap)
    except (TypeError, ValueError):
        return None
    if math.isnan(m):
        return None
    return next(lab for thr, lab in BUCKETS if m >= thr)


# ---------------------------------------------------------------- event sources
def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    from ..db import read_sql

    try:
        return read_sql(sql, params or {})
    except Exception as exc:  # noqa: BLE001
        log.info("outcomes query skipped: %s", exc)
        return pd.DataFrame()


def events_from_db() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    fda = _q("SELECT ticker, event_date, brand_name, description, url FROM fda_events "
             "WHERE kind = 'approval' AND description LIKE 'ORIG%'")
    for r in fda.itertuples():
        out.append({"id": _id("fda", r.ticker, r.event_date, r.brand_name), "ticker": r.ticker,
                    "event_date": pd.to_datetime(r.event_date).date(), "kind": "approval",
                    "direction": "pos", "title": f"FDA approval - {r.brand_name or r.description}",
                    "source": "openfda", "url": r.url})
    ev = _q("SELECT l.id, l.ticker, l.event_type, l.outcome, l.summary, l.kind, "
            "n.published, n.url AS nurl, f.filed_date, f.url AS furl FROM news_llm l "
            "LEFT JOIN news n ON n.id = l.id LEFT JOIN filings f ON f.id = l.id "
            "WHERE l.kind IN ('news','filing') AND l.confidence >= 0.7")
    for r in ev.itertuples():
        kind = LLM_KINDS.get(r.event_type)
        if not kind or r.outcome not in ("positive", "negative"):
            continue
        when = r.published if pd.notna(r.published) else r.filed_date
        d = pd.to_datetime(when, errors="coerce", utc=True)
        if pd.isna(d):
            continue
        out.append({"id": _id("llm", r.id), "ticker": r.ticker,
                    "event_date": d.tz_convert("America/New_York").date(), "kind": kind,
                    "direction": "pos" if r.outcome == "positive" else "neg",
                    "title": str(r.summary or "")[:300], "source": f"ai-{r.kind}",
                    "url": r.nurl if isinstance(r.nurl, str) else r.furl})
    return out


def efts_toplines(max_pages: int = 6, max_fetch: int = 60, budget_s: float = 120) -> list[dict]:
    """Company 'topline' press releases (8-K exhibits) for universe names, walking
    back three years a window at a time (progress kept in app_meta)."""
    from ..httpx_util import get_bytes, get_json
    from ..ingest.edgar import _strip_html
    from ..store import get_meta, set_meta
    from .sentiment import score_text

    secs = _q("SELECT ticker, cik FROM securities WHERE cik IS NOT NULL")
    cmap = {f"{int(c):010d}": t for t, c in zip(secs["ticker"], secs["cik"])
            if str(c).strip().isdigit()}
    if not cmap:
        return []
    cur = get_meta("outcomes_efts_cursor", {}) or {}
    today = datetime.now(timezone.utc).date()
    end = pd.to_datetime(cur.get("end"), errors="coerce")
    end = today if pd.isna(end) or end.date() < today - timedelta(days=3 * 365) else end.date()
    start = end - timedelta(days=90)
    done = _q("SELECT id FROM catalyst_events WHERE source = 'edgar-topline'")
    have = set(done["id"]) if not done.empty else set()
    t0, out, fetched = time.monotonic(), [], 0
    for page in range(max_pages):
        data = get_json("https://efts.sec.gov/LATEST/search-index",
                        {"q": '"topline"', "forms": "8-K", "dateRange": "custom",
                         "startdt": start.isoformat(), "enddt": end.isoformat(),
                         "from": page * 100}, min_interval=0.3, retries=2, timeout=25)
        hits = ((data or {}).get("hits") or {}).get("hits") or []
        for h in hits:
            src = h.get("_source") or {}
            ciks = src.get("ciks") or []
            if not ciks or f"{int(ciks[0]):010d}" not in cmap:
                continue
            if not str(src.get("file_type", "")).upper().startswith("EX-99"):
                continue
            tk = cmap[f"{int(ciks[0]):010d}"]
            eid = _id("efts", src.get("adsh"))
            if eid in have or fetched >= max_fetch or time.monotonic() - t0 > budget_s:
                continue
            have.add(eid)
            fname = str(h.get("_id", "")).split(":", 1)[-1]
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(ciks[0])}/"
                   f"{str(src.get('adsh')).replace('-', '')}/{fname}")
            try:
                text = _strip_html(get_bytes(url, min_interval=0.15, retries=1,
                                             timeout=20)[:600_000])
            except Exception:  # noqa: BLE001
                continue
            fetched += 1
            head = " ".join(text.split())[:2500]
            _, tags, es = score_text(head[:300], head[300:])
            direction = "pos" if es >= 0.5 else "neg" if es <= -0.5 else "unknown"
            out.append({"id": eid, "ticker": tk,
                        "event_date": pd.to_datetime(src.get("file_date")).date(),
                        "kind": "topline", "direction": direction,
                        "title": head[:280], "source": "edgar-topline", "url": url})
        if len(hits) < 100:
            break
    set_meta("outcomes_efts_cursor", {"end": start.isoformat()})
    log.info("efts toplines %s..%s: %d new events (%d docs read)", start, end, len(out), fetched)
    return out


# ---------------------------------------------------------------- returns
def _series(tickers: list[str]) -> dict[str, pd.Series]:
    from ..db import read_sql

    tks = sorted(set(tickers) | {"XBI"})
    out: dict[str, pd.Series] = {}
    for i in range(0, len(tks), 200):
        chunk = tks[i:i + 200]
        df = read_sql(f"SELECT ticker, date, close FROM prices WHERE ticker IN "
                      f"({','.join(f':t{j}' for j in range(len(chunk)))}) ORDER BY date",
                      {f"t{j}": t for j, t in enumerate(chunk)})
        for t, g in df.groupby("ticker"):
            s = pd.Series(pd.to_numeric(g["close"], errors="coerce").values,
                          index=pd.to_datetime(g["date"])).dropna()
            s = s[~s.index.duplicated(keep="last")]
            if len(s) > 30:
                out[t] = s
    return out


def around(s: pd.Series, d: date, bench: pd.Series | None = None) -> dict[str, float | None]:
    """Returns around an event on calendar day ``d`` (see the module docstring)."""
    idx = s.index.searchsorted(pd.Timestamp(d))
    if idx < 61 or idx >= len(s):
        return {}
    base = s.iloc[idx - 1]

    def at(k):
        j = idx + k
        return s.iloc[j] / base - 1 if 0 <= j < len(s) else None

    out = {"ret_pre60": float(base / s.iloc[idx - 61] - 1), "ret_1d": at(1) if idx + 1 < len(s)
           else at(0), "ret_5d": at(5), "ret_21d": at(21)}
    if bench is not None and len(bench) > 70:
        bi = bench.index.searchsorted(s.index[idx - 1])
        if 0 < bi < len(bench):
            bb = bench.iloc[bi]
            for k, n in (("xret_1d", 1), ("xret_5d", 5)):
                j = bi + n
                raw = out["ret_1d" if n == 1 else "ret_5d"]
                if raw is not None and j < len(bench):
                    out[k] = float(raw - (bench.iloc[j] / bb - 1))
    return {k: (None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
            for k, v in out.items()}


def base_rates(df: pd.DataFrame) -> dict[str, Any]:
    df = df.dropna(subset=["ret_1d"])
    res: dict[str, Any] = {"n": int(len(df)), "groups": []}
    for (kind, direction), g in df.groupby(["kind", "direction"]):
        run_up = g[g["ret_pre60"] > 0.3]
        res["groups"].append({
            "kind": kind, "direction": direction, "n": int(len(g)),
            "tickers": int(g["ticker"].nunique()),
            "pre60_median": float(g["ret_pre60"].median()),
            "reaction_median": float(g["ret_1d"].median()),
            "reaction_abs_median": float(g["ret_1d"].abs().median()),
            "reaction_down_share": float((g["ret_1d"] < 0).mean()),
            "d21_median": float(g["ret_21d"].median()) if g["ret_21d"].notna().any() else None,
            "runup_n": int(len(run_up)),
            "runup_then_down_share": float((run_up["ret_1d"] < 0).mean())
            if len(run_up) >= 3 else None,
        })
    by_bucket = df.groupby(["mcap_bucket"])["ret_1d"].apply(lambda s: s.abs().median())
    res["abs_reaction_by_bucket"] = {k: float(v) for k, v in by_bucket.items() if pd.notna(v)}
    return res


def run(backfill: bool = True) -> dict[str, Any]:
    from ..db import backtests, bulk_upsert, catalyst_events

    events = events_from_db()
    if backfill:
        try:
            events += efts_toplines()
        except Exception as exc:  # noqa: BLE001 - the backfill is best effort
            log.warning("topline backfill failed: %s", exc)
    old = _q("SELECT id, ticker, event_date, kind, direction, title, source, url "
             "FROM catalyst_events")
    have = {e["id"] for e in events}
    events += [r for r in old.to_dict("records") if r["id"] not in have]
    if not events:
        return {"rows": 0}
    series = _series([e["ticker"] for e in events])
    fund = _q("SELECT ticker, market_cap FROM fundamentals")
    caps = dict(zip(fund["ticker"], fund["market_cap"])) if not fund.empty else {}
    now = datetime.now(timezone.utc)
    rows = []
    for e in events:
        s = series.get(e["ticker"])
        d = pd.to_datetime(e["event_date"]).date()
        r = around(s, d, series.get("XBI")) if s is not None else {}
        rows.append({**{k: e.get(k) for k in ("id", "ticker", "kind", "direction", "source")},
                     "event_date": d, "title": str(e.get("title") or "")[:500],
                     "url": str(e.get("url") or "")[:512] or None,
                     "mcap_bucket": bucket(caps.get(e["ticker"])), **r, "computed_at": now})
    bulk_upsert(catalyst_events, rows)
    df = pd.DataFrame(rows)
    for c in ("ret_pre60", "ret_1d", "ret_5d", "ret_21d"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    rates = base_rates(df[df["direction"].isin(["pos", "neg"])])
    today = now.date()
    bulk_upsert(backtests, [{"id": f"outcomes|{today}", "kind": "outcomes", "ts": now,
                             "params": json.dumps({"window": "2-session reaction"}),
                             "results": json.dumps(rates, default=str)}])
    return {"rows": len(rows), "with_returns": int(df["ret_1d"].notna().sum()),
            "groups": len(rates["groups"])}


# ---------------------------------------------------------------- implied vs realized
def implied_vs_realized(days_ahead: int = 60) -> pd.DataFrame:
    """Upcoming binary catalysts with the options-implied move next to the moves
    this name (and names of its size) made on past events."""
    today = date.today()
    cats = _q("SELECT ticker, type, date, title FROM catalysts WHERE type IN "
              "('pdufa','adcom','phase3_readout','fda_action') AND date >= :a AND date <= :b "
              "ORDER BY date", {"a": today.isoformat(),
                                "b": (today + timedelta(days=days_ahead)).isoformat()})
    if cats.empty:
        return pd.DataFrame()
    opt = _q("SELECT ticker, date, expiry, atm_iv, iv_back, implied_move FROM options_snapshots "
             "WHERE date >= :c", {"c": (today - timedelta(days=5)).isoformat()})
    opt = opt.sort_values("date").groupby("ticker").last() if not opt.empty else opt
    ev = _q("SELECT ticker, kind, ret_1d, mcap_bucket FROM catalyst_events "
            "WHERE ret_1d IS NOT NULL")
    fund = _q("SELECT ticker, market_cap FROM fundamentals")
    caps = dict(zip(fund["ticker"], fund["market_cap"])) if not fund.empty else {}
    rows = []
    for c in cats.itertuples():
        d = pd.to_datetime(c.date).date()
        imp = None
        if not opt.empty and c.ticker in opt.index:
            o = opt.loc[c.ticker]
            exp = pd.to_datetime(o["expiry"], errors="coerce")
            if pd.notna(exp) and d <= exp.date() and pd.notna(o["implied_move"]):
                imp = float(o["implied_move"])
            elif pd.notna(o["iv_back"]):
                imp = float(o["iv_back"]) * math.sqrt(max(1, (d - today).days) / 365)
        mine = ev[ev["ticker"] == c.ticker]["ret_1d"].abs() if not ev.empty else pd.Series()
        b = bucket(caps.get(c.ticker))
        peers = ev[ev["mcap_bucket"] == b]["ret_1d"].abs() if not ev.empty and b else pd.Series()
        rows.append({"ticker": c.ticker, "date": d, "type": c.type, "title": c.title,
                     "implied_move": imp,
                     "own_median_move": float(mine.median()) if len(mine) >= 2 else None,
                     "own_events": int(len(mine)),
                     "peer_median_move": float(peers.median()) if len(peers) >= 5 else None,
                     "peer_events": int(len(peers)), "bucket": b})
    out = pd.DataFrame(rows)
    ref = out["own_median_move"].fillna(out["peer_median_move"])
    out["implied_vs_history"] = np.where(out["implied_move"].notna() & ref.notna() & (ref > 0),
                                         out["implied_move"] / ref, np.nan)
    return out
