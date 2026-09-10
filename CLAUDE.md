# CLAUDE.md — working on BioTerm

Biotech/pharma **catalyst-monitoring terminal**, 6-month swing horizon. Surfaces names
*before* a pipeline-driven move. Monitoring/screening tool — **never** framed as
investment advice.

**Read `DEPLOYMENT_LOG.md` first** — it's the live state + resume checklist.

## Layout

```
src/bioterm/
  config.py     YAML + env  ·  db.py  SQLAlchemy Core schema (21 tables) + portable bulk_upsert
  store.py      DB-backed user state (watchlist / manual catalysts / notes / app_meta
                / pf_portfolios / pf_trades) — YAML seeds the research state once
  portfolio.py  paper-trading maths — positions (avg cost), cash, equity curve, P&L (pure)
  universe.py   XBI holdings + seed list + watchlist  →  securities
  httpx_util.py pooled session, retry/backoff, per-host throttle
  ingest/       prices fundamentals edgar clinical fda insiders news   (each: run(tickers) -> dict)
  process/      technicals sentiment catalysts score
  alerts.py     evaluate rules  →  alerts_fired  (+ optional Telegram)
  pipeline.py   run_job() wrapper (logs to ingest_runs) + run_full_refresh()
  scheduler.py  APScheduler (local "always on")
  cli.py        typer:  init-db · universe · ingest · score · alerts · status · serve · scheduler
dashboard/      Streamlit — _ui.py (theme + page_setup + components),
                _shared.py (cached DB reads + sentiment_df), Home.py + pages/1..8
                (8 = Paper-Trading Desk — buy/sell blotter + positions + net-worth curve;
                 fully separate from the research pages, simulated fills, long-only)
.github/workflows/  ingest-fast.yml (0 11-23/2)  ·  ingest-full.yml (0 9)  — private-repo cadence
deploy/         Dockerfile, compose, launchd, setup-github.sh, README.md
```

**Deployed:** dashboard = https://bioterm.streamlit.app (Streamlit Cloud, auto-redeploys
on push to main) · DB = Neon Postgres (secret) · ingestion = GitHub Actions on the
private repo `Nishant808/bioterm`.

## Dashboard UI

- Every page starts with `from _ui import page_setup, …; page_setup(title, subtitle)`.
- `_ui.py` owns the theme CSS (injected every run — Streamlit drops prior-page markup),
  the palette (`ACCENT/POS/NEG/WARN`, `PHASE_COLORS`, `SMA_COLORS`), `plotly_layout()`,
  and components: `eyebrow()`, `stat_strip()`, `signal_dot()`, `sentiment_word()`.
- **Deploy gotcha:** Streamlit Cloud does a *fast* reboot on a `.py`-only push and keeps
  imported helper modules (`_shared`, `_ui`) in `sys.modules`. If a page imports a
  brand-new symbol from `_shared`/`_ui`, it ImportErrors on the live app until a full
  rebuild. **When you add a cross-page helper, also bump the `rebuild-marker` line in
  `requirements.txt`** to force a clean container rebuild.
- News sentiment: `_shared.sentiment_df(days)` / `sentiment_series(ticker, days)`.
- No repeated disclaimer on pages — it lives once in the sidebar footer.

## Focus Score

```
focus = conviction_mult · insider_mult · (w_mom·momentum + w_cat·catalyst + w_news·newsflow) − w_risk·risk
```
All weights + the event lexicon in `config/settings.yml`. Every input is stored in
`scores.rationale` (JSON) and rendered on the *Stocks in Focus* decomposition.
`conviction_mult` = the user's 1–5 watchlist rating. `insider_mult` = cluster
open-market insider buying.

## Conventions

- **DB is source of truth** for anything the dashboard edits. `config/*.yml` only seed
  empty tables (`store.seed_from_yaml`, called by `init_db`). Don't reintroduce YAML writes.
- `bulk_upsert(table, rows, update_only=[...])` for partial-row writes — without
  `update_only` it overwrites unlisted columns with NULL.
- Every new ingest source: bounded request count + a wall-clock budget (see `fda.py`,
  `insiders.py`); fail soft (warn, continue), never abort the whole refresh.
- Works on SQLite (local) **and** Postgres (cloud) — same schema. Test both mentally;
  `read_sql` wraps raw strings in `text()`.
- `uv run pytest -q` before committing. Tests use a tmp SQLite DB and stub the YAML seed.
- Commit messages end with the Co-Authored-By trailer. Don't push / create PRs unless asked.

## Run locally

```bash
uv pip install -e ".[dev]"
uv run bioterm init-db && uv run bioterm universe
uv run bioterm ingest --limit 40      # fast slice
uv run bioterm serve                   # localhost:8501
```
