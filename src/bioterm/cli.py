"""BioTerm command line.

    bioterm init-db                 create the database schema
    bioterm universe [--force]      build/refresh the ticker universe
    bioterm ingest [--once] [--limit N] [--only prices,news,...]
    bioterm score                   recompute catalysts + Focus Score
    bioterm status                  show recent ingest runs + row counts
    bioterm serve                   launch the Streamlit dashboard
    bioterm scheduler               run the always-on background scheduler
"""
from __future__ import annotations

import logging

import typer
from rich.console import Console

app = typer.Typer(add_completion=False, help="Biotech/pharma catalyst-monitoring terminal")
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)


@app.command("init-db")
def init_db_cmd() -> None:
    """Create all tables."""
    from .db import init_db

    tables = init_db()
    console.print(f"[green]created[/green] {len(tables)} tables: {', '.join(tables)}")


@app.command()
def universe(force: bool = typer.Option(False, help="rebuild even if recent")) -> None:
    """Build the XBI + IBB + seed + watchlist universe."""
    from .universe import build_universe

    df = build_universe(force=force)
    console.print(f"[green]universe:[/green] {len(df)} tickers")
    console.print(df[["ticker", "name", "in_xbi", "in_ibb", "in_seed", "is_watchlist"]]
                  .head(25).to_string(index=False))


@app.command()
def ingest(
    once: bool = typer.Option(True, "--once/--no-once", help="run a single full refresh"),
    limit: int = typer.Option(0, help="cap universe size (0 = all)"),
    only: str = typer.Option("", help="comma list: prices,technicals,edgar,fundamentals,"
                                      "clinical,fda,news,sentiment,catalysts,score"),
    preset: str = typer.Option("", help="'fast' (news+score, for a frequent cron) or "
                                        "'full' (everything, for a 2-3x/day cron)"),
) -> None:
    """Run the ingestion + processing pipeline."""
    from . import pipeline
    from .universe import universe_tickers

    lim = limit or None

    if preset == "fast":
        only = "news,sentiment,catalysts,score"
    elif preset == "full":
        only = ""  # full refresh path below

    if preset == "full":
        console.print_json(data=pipeline.run_full_refresh(limit=lim))
        return

    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        tickers = universe_tickers(limit=lim)
        jobmap = {
            "prices": lambda: pipeline.run_job("prices", _m("ingest.prices").run, tickers),
            "technicals": lambda: pipeline.run_job("technicals", _m("process.technicals").run, tickers),
            "edgar": lambda: pipeline.run_job("edgar", _m("ingest.edgar").run, tickers),
            "fundamentals": lambda: pipeline.run_job("fundamentals", _m("ingest.fundamentals").run, tickers),
            "clinical": lambda: pipeline.run_job("clinical", _m("ingest.clinical").run, tickers),
            "fda": lambda: pipeline.run_job("fda", _m("ingest.fda").run, tickers),
            "news": lambda: pipeline.run_job("news", _m("ingest.news").run, tickers),
            "sentiment": lambda: pipeline.run_job("sentiment", _m("process.sentiment").run, True),
            "catalysts": lambda: pipeline.run_job("catalysts", _m("process.catalysts").run),
            "score": lambda: pipeline.run_job("score", _m("process.score").run),
        }
        for name in ["prices", "technicals", "edgar", "fundamentals", "clinical",
                     "fda", "news", "sentiment", "catalysts", "score"]:
            if name in wanted:
                console.rule(name)
                console.print(jobmap[name]())
        return

    results = pipeline.run_full_refresh(limit=lim)
    console.print_json(data=results)


@app.command()
def score() -> None:
    """Recompute catalysts and the Focus Score, print the leaderboard."""
    from .process import catalysts, score as score_mod
    from .db import read_sql

    catalysts.run()
    score_mod.run()
    df = read_sql(
        "SELECT rank, s.ticker, name, focus_score, momentum, catalyst, newsflow, risk, "
        "conviction_mult FROM scores s JOIN securities u ON u.ticker = s.ticker "
        "ORDER BY rank LIMIT 25"
    )
    console.print(df.to_string(index=False))


@app.command()
def alerts(
    deliver: bool = typer.Option(True, "--deliver/--no-deliver",
                                 help="push new alerts (Telegram, if configured)"),
) -> None:
    """Evaluate alert rules against the current data; record + optionally push new ones."""
    from . import alerts as alerts_mod

    out = alerts_mod.run(deliver=deliver)
    console.print_json(data=out)
    firing = alerts_mod.evaluate()
    for a in firing[:20]:
        icon = {"score move": "📈", "catalyst soon": "🗓", "headline": "📰"}.get(a["kind"], "•")
        console.print(f"{icon} [bold]{a['ticker']}[/bold] {a['kind']}: {a['detail']}")


@app.command()
def status() -> None:
    """Show recent ingest runs and table row counts."""
    from .db import (catalysts, clinical_trials, fda_events, filings, news,
                     prices, scores, securities, table_count, technicals)
    from . import pipeline

    for tbl in (securities, prices, technicals, news, clinical_trials, fda_events,
                filings, catalysts, scores):
        try:
            console.print(f"  {tbl.name:18s} {table_count(tbl):>8d} rows")
        except Exception as exc:  # noqa: BLE001
            console.print(f"  {tbl.name:18s} [red]{exc}[/red]")
    console.rule("recent runs")
    console.print(pipeline.last_runs(20).to_string(index=False))


@app.command()
def serve(port: int = 8501) -> None:
    """Launch the Streamlit dashboard."""
    import subprocess
    import sys
    from pathlib import Path

    home = Path(__file__).resolve().parents[2] / "dashboard" / "Home.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(home),
         "--server.port", str(port), "--server.headless", "true"],
        check=False,
    )


@app.command()
def scheduler() -> None:
    """Run the always-on background scheduler (Ctrl-C to stop)."""
    from .scheduler import main as sched_main

    sched_main()


def _m(path: str):
    import importlib

    return importlib.import_module(f"bioterm.{path}")


if __name__ == "__main__":
    app()
