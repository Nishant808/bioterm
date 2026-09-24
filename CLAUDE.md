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
dashboard/      Streamlit — Home.py (router: st.navigation top bar, logo, CSS, footer)
                app_pages/  overview focus stock catalysts news watchlist compare alerts portfolio
                _ui.py (design system: tokens + components + chart helpers)
                _shared.py (cached DB reads + sentiment_df) · assets/ (logo + mark SVG)
                (portfolio = Paper-Trading Desk — buy/sell blotter + positions + net-worth
                 curve; fully separate from the research pages, simulated fills, long-only)
.streamlit/config.toml   native theme (colours, Inter/JetBrains Mono, radius, chart palette)
.github/workflows/  ingest-fast.yml (0 11-23/2)  ·  ingest-full.yml (0 9)  — private-repo cadence
deploy/         Dockerfile, compose, launchd, setup-github.sh, README.md
```

**Deployed:** dashboard = https://bioterm.streamlit.app (Streamlit Cloud, auto-redeploys
on push to main) · DB = Neon Postgres (secret) · ingestion = GitHub Actions on the
private repo `Nishant808/bioterm`.

## Dashboard UI

- `Home.py` is the **router**, not a page: `st.navigation(position="top")` over
  `app_pages/*.py`, then injects the CSS, runs the page, renders the footer, and turns a
  `SQLAlchemyError` into an empty state + retry. Page URLs (`/Stock_Detail?ticker=X`,
  `/Portfolio?pf=…`) are kept from the old multipage layout — deep links still work.
- A page calls `page_header(title, subtitle)` and composes `card()`, `kpi_row(n, name)`
  (a responsive grid of `st.metric(border=True)`), `label()`, `empty_state()`, the list
  renderers `headline_rows()` / `catalyst_rows()` / `alert_rows()`, `kv_list()`, `badge()`.
- **Theme lives in `.streamlit/config.toml`** (native theming reaches every widget);
  `_ui.py` mirrors those tokens (`BG/SURFACE/BORDER/TEXT/MUTED/PRIMARY/ACCENT/POS/NEG/WARN`)
  for Plotly and custom HTML — change a colour in both. `_ui._CSS` only adds what config
  can't express (header, list rows, badges, KPI grid, motion; honours reduced-motion).
- Charts: `fig.update_layout(**plotly_layout(...))` then `chart(fig, key=…)`. Never set a
  plotly `template` (it would override the config's `chartCategoricalColors`), never a dual
  y-axis (stack two panels instead). Series colours follow the entity (`SERIES`,
  catalyst `FAMILIES`, `PHASE_COLORS`, `SMA_COLORS`); `POS/NEG/WARN` mean state only.
- Feed text is untrusted: `plain()` strips markup (mirrors `bioterm.util.strip_markup`),
  `esc()` before any `unsafe_allow_html`/`st.html`, `safe_url()` for hrefs, `md_safe()` for
  `$` in markdown (otherwise it renders as LaTeX), `usd()` for money (`−$826`, not `$-826`).
- **Deploy gotcha:** Streamlit Cloud does a *fast* reboot on a `.py`-only push — it
  pulls the new source but keeps every imported module (`bioterm.*`, `_shared`, `_ui`)
  in `sys.modules`. The router's `_fresh()` now reloads `_shared` / `_ui` when their file
  changed, and `app_pages/` always re-execute — but `bioterm.*` is still stale, so a page
  (or `_ui`) importing a **brand-new symbol** from `bioterm.*` ImportErrors on the live app
  (traceback points at the new source line inside an old frame). To force a full restart
  you must **change a real dependency line in `requirements.txt`** (the `rebuild-marker`
  *comment* alone does NOT trigger a reinstall — learned the hard way, session 5) or
  reboot from the Streamlit Cloud console.
- `tests/test_dashboard.py` renders every page with Streamlit's `AppTest` against an
  empty and a seeded DB, plus deep links and a few interactions — keep it green.
- News sentiment: `_shared.sentiment_df(days)` / `sentiment_series(ticker, days)`.
- No repeated disclaimer on pages — it lives once in the page footer (`_ui.footer()`,
  rendered by the router).

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
  `read_sql` wraps raw strings in `text()` and is for SELECTs only — it runs them in
  autocommit (2 round trips to Neon instead of 4); writes go through `engine.begin()` /
  `bulk_upsert` and stay transactional. SQLite stores DateTime as text with
  microseconds: in raw SQL pass time cuts as `"%Y-%m-%d %H:%M:%S"` strings with `>=`/`<=`,
  and never test `ts = :datetime` — use a Core `select(...).where(col == dt)` so the
  column type binds it (raw equality silently matched nothing on SQLite, session 7).
- `uv run pytest -q` before committing. Tests use a tmp SQLite DB and stub the YAML seed.
  ("Failed to spawn: pytest" = the venv's script shebangs still point at an old repo
  path after a move → `uv sync --extra dev --reinstall`.)
- Commit messages end with the Co-Authored-By trailer. Don't push / create PRs unless asked.

## Run locally

```bash
uv pip install -e ".[dev]"
uv run bioterm init-db && uv run bioterm universe
uv run bioterm ingest --limit 40      # fast slice
uv run bioterm serve                   # localhost:8501
```
