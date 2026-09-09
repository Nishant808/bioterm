"""Always-on background scheduler (APScheduler).

    bioterm scheduler

Cadence (all configurable here):
  * market data + technicals   every 30 min, 13:00-21:30 UTC Mon-Fri (US session +buffer)
  * news + sentiment           every 15 min
  * clinical trials            daily 07:10 UTC
  * fundamentals + EDGAR       daily 07:40 UTC
  * universe rebuild           Monday 06:30 UTC
  * catalysts + Focus Score    5 min past every news/market/clinical job (via listener)

On a laptop this only runs while the machine is awake; for true 24/7 use the
GitHub Actions template in deploy/github/ingest.yml.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import pipeline
from .db import init_db

log = logging.getLogger("bioterm.scheduler")


def _market_job() -> None:
    pipeline.refresh_market(pipeline.universe_tickers())
    pipeline.recompute()


def _news_fast_job() -> None:
    """Sector RSS feeds only - cheap, run often."""
    from .ingest import news as news_mod
    from .process import sentiment

    pipeline.run_job("news", news_mod.run, pipeline.universe_tickers(), False)
    pipeline.run_job("sentiment", sentiment.run, True)
    pipeline.recompute()


def _news_full_job() -> None:
    """Sector feeds + per-ticker Google News queries - heavier, hourly."""
    pipeline.refresh_news(pipeline.universe_tickers())
    pipeline.recompute()


def _clinical_job() -> None:
    pipeline.refresh_pipeline_data(pipeline.universe_tickers())
    pipeline.recompute()


def _fundamentals_job() -> None:
    pipeline.refresh_fundamentals(pipeline.universe_tickers())
    pipeline.recompute()


def _universe_job() -> None:
    pipeline.refresh_universe(force=True)


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(_market_job, IntervalTrigger(minutes=30), id="market",
                  max_instances=1, coalesce=True, misfire_grace_time=600)
    sched.add_job(_news_fast_job, IntervalTrigger(minutes=15), id="news_fast",
                  max_instances=1, coalesce=True, misfire_grace_time=600)
    sched.add_job(_news_full_job, IntervalTrigger(minutes=60), id="news_full",
                  max_instances=1, coalesce=True, misfire_grace_time=900)
    sched.add_job(_clinical_job, CronTrigger(hour=7, minute=10), id="clinical",
                  max_instances=1, coalesce=True)
    sched.add_job(_fundamentals_job, CronTrigger(hour=7, minute=40), id="fundamentals",
                  max_instances=1, coalesce=True)
    sched.add_job(_universe_job, CronTrigger(day_of_week="mon", hour=6, minute=30),
                  id="universe", max_instances=1, coalesce=True)
    return sched


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    )
    init_db()
    log.info("bootstrapping: one full refresh before entering the schedule loop")
    pipeline.run_full_refresh()
    sched = build_scheduler()
    log.info("scheduler started - jobs: %s", [j.id for j in sched.get_jobs()])
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")


if __name__ == "__main__":
    main()
