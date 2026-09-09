"""Pipeline orchestration. Each job is wrapped so a failure is logged to
``ingest_runs`` and does not abort the rest of the refresh.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import datetime, timezone

from .db import bulk_upsert, ingest_runs, init_db
from .ingest import clinical, edgar, fda
from .ingest import fundamentals as ingest_fundamentals
from .ingest import news, prices
from .process import catalysts, score, sentiment, technicals
from .universe import build_universe, universe_tickers

log = logging.getLogger("bioterm.pipeline")


def _record(job: str, started: datetime, status: str, detail: dict) -> None:
    bulk_upsert(
        ingest_runs,
        [
            {
                "job": job,
                "started_at": started,
                "finished_at": datetime.now(timezone.utc),
                "status": status,
                "rows": int(detail.get("rows", 0)) if isinstance(detail.get("rows"), (int, float)) else 0,
                "detail": json.dumps(detail, default=str)[:4000],
            }
        ],
    )


def run_job(job: str, fn, *args, **kwargs) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    try:
        detail = fn(*args, **kwargs) or {}
        detail["seconds"] = round(time.monotonic() - t0, 1)
        _record(job, started, "ok", detail)
        log.info("[%s] ok in %.1fs -> %s", job, detail["seconds"], detail)
        return detail
    except Exception as exc:  # noqa: BLE001
        detail = {"error": str(exc), "trace": traceback.format_exc()[-1500:],
                  "seconds": round(time.monotonic() - t0, 1)}
        _record(job, started, "error", detail)
        log.error("[%s] FAILED: %s", job, exc)
        return detail


# ------------------------------------------------------------------ job groups
def refresh_universe(force: bool = False) -> dict:
    def _universe() -> dict:
        df = build_universe(force=force)
        return {"rows": len(df)}

    return run_job("universe", _universe)


def refresh_market(tickers: list[str] | None = None) -> dict:
    out = {}
    out["prices"] = run_job("prices", prices.run, tickers)
    out["technicals"] = run_job("technicals", technicals.run, tickers)
    return out


def refresh_fundamentals(tickers: list[str] | None = None) -> dict:
    out = {}
    out["edgar"] = run_job("edgar", edgar.run, tickers)
    out["fundamentals"] = run_job("fundamentals", ingest_fundamentals.run, tickers)
    return out


def refresh_pipeline_data(tickers: list[str] | None = None) -> dict:
    out = {}
    out["clinical"] = run_job("clinical", clinical.run, tickers)
    out["fda"] = run_job("fda", fda.run, tickers)
    return out


def refresh_news(tickers: list[str] | None = None) -> dict:
    out = {}
    out["news"] = run_job("news", news.run, tickers)
    out["sentiment"] = run_job("sentiment", sentiment.run, True)
    return out


def recompute(_: list[str] | None = None) -> dict:
    out = {}
    out["catalysts"] = run_job("catalysts", catalysts.run)
    out["score"] = run_job("score", score.run)
    return out


def run_full_refresh(limit: int | None = None, skip_universe: bool = False) -> dict:
    init_db()
    if not skip_universe:
        refresh_universe(force=False)
    tickers = universe_tickers(limit=limit)
    log.info("full refresh over %d tickers", len(tickers))
    results = {
        "universe_size": len(tickers),
        "market": refresh_market(tickers),
        "fundamentals": refresh_fundamentals(tickers),
        "pipeline": refresh_pipeline_data(tickers),
        "news": refresh_news(tickers),
        "recompute": recompute(),
    }
    return results


def last_runs(n: int = 30):
    from .db import read_sql
    return read_sql(
        "SELECT job, started_at, finished_at, status, rows FROM ingest_runs "
        "ORDER BY id DESC LIMIT :n", {"n": n}
    )
