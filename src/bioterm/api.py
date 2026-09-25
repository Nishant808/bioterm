"""Read-only JSON API over the BioTerm database - for spreadsheets, notebooks and
other tools. ``bioterm api`` serves it (needs the ``api`` extra: fastapi + uvicorn).

Every call needs ``Authorization: Bearer <token>``; the token is
``BIOTERM_API_TOKEN`` (environment, or saved on the Settings page). With no token
configured the API refuses everything - there is no anonymous mode.

Endpoints (all GET):
  /health                    liveness + latest refresh (no auth)
  /universe?tier=core        tickers, names, tier, SIC
  /scores                    latest Focus Score board
  /signals                   latest signal board (label, net, evidence)
  /catalysts?days=180        upcoming catalysts
  /stock/{ticker}            one name: fundamentals, score, signal, catalysts, filings
  /screen?preset=...         a Screener preset (or ?field=op:value filters)
  /alerts?limit=100          alerts recorded
  /dq                        latest data-quality checks
"""
from __future__ import annotations

import hmac
import json
import math
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


def _token() -> str | None:
    from . import vault

    return vault.get("BIOTERM_API_TOKEN")


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> JSON-safe records (NaN -> null, timestamps -> ISO)."""
    if df is None or df.empty:
        return []
    out = []
    for r in df.to_dict("records"):
        row = {}
        for k, v in r.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                v = None
            elif isinstance(v, (pd.Timestamp, datetime, date)):
                v = None if pd.isna(v) else v.isoformat()
            elif v is pd.NaT:
                v = None
            elif hasattr(v, "item"):          # numpy scalars
                v = v.item()
            row[k] = v
        out.append(row)
    return out


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    from .db import read_sql

    return read_sql(sql, params or {})


def create_app():
    from fastapi import Depends, FastAPI, Header, HTTPException, Query

    app = FastAPI(title="BioTerm API", version="1.0",
                  description="Read-only access to the BioTerm database. Screening data, "
                              "not investment advice.")

    def auth(authorization: str | None = Header(default=None)) -> None:
        tok = _token()
        if not tok:
            raise HTTPException(503, "API disabled - set BIOTERM_API_TOKEN")
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not given or not hmac.compare_digest(given.encode(), tok.encode()):
            raise HTTPException(401, "bad or missing bearer token")

    @app.get("/health")
    def health() -> dict:
        try:
            r = _q("SELECT MAX(finished_at) AS t FROM ingest_runs")
            last = r.iloc[0]["t"] if not r.empty else None
            return {"ok": True, "last_refresh": str(last) if last is not None else None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}

    @app.get("/universe", dependencies=[Depends(auth)])
    def universe(tier: str = Query("core", pattern="^(core|extended|all)$")) -> list[dict]:
        where = {"core": "tier IS NULL OR tier = 'core'", "extended": "tier = 'extended'",
                 "all": "tier IS NULL OR tier IN ('core', 'extended')"}[tier]
        return _records(_q("SELECT ticker, name, exchange, cik, sic, COALESCE(tier, 'core') "
                           f"AS tier, in_xbi, is_watchlist, etf_weight FROM securities "
                           f"WHERE {where} ORDER BY ticker"))

    @app.get("/scores", dependencies=[Depends(auth)])
    def scores() -> list[dict]:
        return _records(_q("SELECT ticker, asof, focus_score, rank, momentum, catalyst, "
                           "newsflow, risk FROM scores WHERE asof = (SELECT MAX(asof) FROM "
                           "scores) ORDER BY rank"))

    @app.get("/signals", dependencies=[Depends(auth)])
    def signals() -> list[dict]:
        df = _q("SELECT ticker, asof, label, net, bull, bear, n_buy, n_sell, close, regime, "
                "top FROM signal_scores WHERE asof = (SELECT MAX(asof) FROM signal_scores) "
                "ORDER BY net DESC")
        if not df.empty:
            df["top"] = df["top"].map(lambda s: [e.get("title") for e in json.loads(s or "[]")]
                                      if isinstance(s, str) else [])
        return _records(df)

    @app.get("/catalysts", dependencies=[Depends(auth)])
    def catalysts(days: int = Query(180, ge=1, le=730)) -> list[dict]:
        today = date.today()
        return _records(_q("SELECT ticker, date, type, title, confidence, source, url FROM "
                           "catalysts WHERE date >= :a AND date <= :b ORDER BY date",
                           {"a": today.isoformat(),
                            "b": (today + timedelta(days=days)).isoformat()}))

    @app.get("/stock/{ticker}", dependencies=[Depends(auth)])
    def stock(ticker: str) -> dict:
        from .tearsheet import gather

        t = ticker.upper()[:16]
        if _q("SELECT ticker FROM securities WHERE ticker = :t", {"t": t}).empty:
            raise HTTPException(404, f"{t} is not in the universe")
        d = gather(t)
        out: dict[str, Any] = {"ticker": t, "name": d["name"]}
        for k in ("fundamentals", "score", "signal"):
            out[k] = _records(pd.DataFrame([d[k]]))[0] if d[k] else {}
        out["signal_evidence"] = d["signal_evidence"]
        for k in ("catalysts", "trials", "filings", "insiders", "funds", "news", "loe"):
            out[k] = _records(d[k])
        return out

    @app.get("/screen", dependencies=[Depends(auth)])
    def screen(preset: str | None = None,
               filter: list[str] = Query(default=[],  # noqa: A002 - query name
                                         description="field:op:value, e.g. "
                                                     "runway_quarters:>=:8")) -> dict:
        from . import screener as sc

        if preset and preset not in sc.PRESETS:
            raise HTTPException(404, f"unknown preset; one of {list(sc.PRESETS)}")
        flt = [dict(f) for f in sc.PRESETS.get(preset or "", [])]
        for f in filter:
            try:
                field, op, raw = f.split(":", 2)
            except ValueError:
                raise HTTPException(422, f"bad filter {f!r} - use field:op:value") from None
            if field not in sc.FIELDS:
                raise HTTPException(422, f"unknown field {field!r}")
            kind = sc.FIELDS[field][1]
            if kind == "bool":
                val: Any = raw.lower() in ("1", "true", "yes")
            elif kind in ("text", "label"):
                val = [x.strip() for x in raw.split(",")]
            elif op == "between":
                val = [float(x) for x in raw.split(",")[:2]]
            else:
                val = float(raw)
            flt.append({"field": field, "op": op, "value": val})
        res = sc.apply(sc.frame(), flt)
        cols = [c for c in ("ticker", "name", "coverage", "market_cap", "cash",
                            "runway_quarters", "signal", "focus_rank", "next_catalyst_days",
                            "next_catalyst_type", "top_phase", "dilution_risk",
                            "takeout_score") if c in res]
        return {"filters": flt, "count": len(res), "rows": _records(res[cols])}

    @app.get("/alerts", dependencies=[Depends(auth)])
    def alerts(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
        return _records(_q("SELECT ts, kind, ticker, detail, weight, delivered FROM "
                           "alerts_fired ORDER BY ts DESC LIMIT :n", {"n": limit}))

    @app.get("/dq", dependencies=[Depends(auth)])
    def dq() -> list[dict]:
        from .process.dq import latest

        return _records(latest())

    return app
