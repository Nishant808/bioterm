# CLAUDE.md — working on BioTerm

Biotech/pharma **intelligence terminal**, 6-month swing horizon. Surfaces names
*before* a pipeline-driven move: a Focus Score (attention ranking) plus an early
BUY/SELL signal engine over price, catalysts, cash, insiders, specialist-fund 13Fs,
news (FinBERT) and options/short flow. Monitoring/screening tool — **never** framed as
investment advice (the labels are screening states, not recommendations).

**Read `DEPLOYMENT_LOG.md` first** — it's the live state + resume checklist.

## Layout

```
src/bioterm/
  config.py     YAML + env (settings.yml, institutions.yml = tracked 13F funds)
  db.py         SQLAlchemy Core schema (34 tables) + portable bulk_upsert + migrate()
                (additive: ADD COLUMN for columns missing on an existing table)
  store.py      DB-backed user state (watchlist / manual catalysts / notes / app_meta /
                pf_* / molecules) — YAML seeds the research state once
  portfolio.py  paper-trading maths — positions (avg cost), cash, equity curve, P&L (pure)
  universe.py   XBI holdings + seed list + watchlist  →  securities
  httpx_util.py pooled session, retry/backoff, per-host throttle, get_json/post_json
  ingest/       prices fundamentals edgar clinical fda insiders news
                short_volume (FINRA Reg SHO)  institutions (13F-HR + CUSIP→ticker)
                options (yfinance chains)  molecules (CT.gov by intervention + Europe PMC)
                (each: run(...) -> dict, bounded + wall-clock budget, fail soft)
  process/      technicals sentiment finbert catalysts score molecules (links/status)
                smart_money (13F quarter-over-quarter)  signals (BUY/SELL engine)
                backtest (event study, factor study, live track record)
  alerts.py     evaluate rules  →  alerts_fired  (+ optional Telegram); incl. signal changes
  pipeline.py   run_job() wrapper (logs to ingest_runs) + run_full_refresh()
  scheduler.py  APScheduler (local "always on")
  cli.py        typer: init-db · universe · ingest · score · signals · backtest · nlp ·
                alerts · status · serve · scheduler
dashboard/      Streamlit — Home.py (router: st.navigation top bar with sections, logo,
                CSS, footer)
                app_pages/  "" : overview signals stock
                            Intelligence: focus smart_money molecules backtest
                            Markets: catalysts news compare · Workspace: watchlist alerts portfolio
                _ui.py (design system: tokens + components + chart helpers + signal
                taxonomy DETECTORS/SIGNAL_FAMILIES + signal_rows/call_rows)
                _shared.py (cached DB reads incl. signal_board, smart_money, short_flow,
                options_latest, molecules_df, backtest_result) · assets/ (logo + mark SVG)
                (portfolio = Paper-Trading Desk — simulated fills, long-only)
.streamlit/config.toml   native theme (colours, Inter/JetBrains Mono, radius, chart palette)
.github/workflows/  ingest-fast.yml (0 11-23/2)  ·  ingest-full.yml (0 9, + FinBERT)
                    probe.yml (push to main-vcyb9o / dispatch: every job against live
                    sources on a Postgres 16 service, then renders every page)
deploy/         Dockerfile, compose, launchd, setup-github.sh, README.md
video/          30s launch film — Remotion 4 (React/SVG) + procedural audio; own package.json,
                see video/README.md (timeline.json drives picture + sound; output/ git-ignored)
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
- Signal calls render with `signal_badge(label)` / `call_rows(board)` / `signal_rows(fired)`;
  detector names + families come from `_ui.DETECTORS` (keep it in sync with the codes
  in `process/signals.py`). BUY/SELL colours are `POS`/`NEG` (states).
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

## Signal engine (`process/signals.py`)

~33 detectors in six evidence families (technical, event, capital, people, news,
flow) each fire with a strength 0–1. `bull = 1 − Π(1 − s)` over BUY detectors, `bear`
likewise, `net = bull − bear` → STRONG BUY ≥ .55 · BUY ≥ .25 · … (settings `signals.labels`).
STRONG needs ≥ 2 families (`strong_min_families`) — price action alone can't make one.
Scaled by the XBI regime, watchlist conviction, company size (catalyst setups), 13F
filing age, and — for price detectors — the measured edge from the latest event study
(`calibration()`: buy ×0.5–1.3, sell ×0.75–1.3; the asymmetry is the survivorship
bias of a today's-XBI universe). `price_features()` is shared with `backtest.py`, so
the backtest tests exactly what runs live. One run per day: today's rows are replaced,
`signal_scores` keeps history (`keep_days`) for the live track record and alerts.
First live-data finding (session 9): in this universe most price detectors have zero or
*negative* 3-month edge (biotech mean-reverts); the calibration damps them — don't
"fix" that by raising their strengths.

## Conventions

- **DB is source of truth** for anything the dashboard edits. `config/*.yml` only seed
  empty tables (`store.seed_from_yaml`, called by `init_db`). Don't reintroduce YAML writes.
- `bulk_upsert(table, rows, update_only=[...])` for partial-row writes — without
  `update_only` it overwrites unlisted columns with NULL.
- Every new ingest source: bounded request count + a wall-clock budget (see `fda.py`,
  `insiders.py`, `institutions.py`); fail soft (warn, continue), never abort the refresh.
- Schema changes: add tables/columns in `db.py`; `init_db()` runs `migrate()` which only
  ADDs missing nullable columns. Renames/type changes need a hand-written migration.
- **Postgres enforces VARCHAR(n)** (SQLite doesn't): truncate external strings to the
  column size before writing, or use `Text`. The `probe` workflow runs on Postgres for this.
- FinBERT (`process/finbert.py`) needs torch + transformers, installed *beside* the
  locked env only in `ingest-full.yml` (never add them to pyproject/uv.lock — the
  dashboard would pull ~700 MB). Everywhere else it's a no-op and VADER tone stays.
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
uv run bioterm ingest --only shortvol,institutions,molecules,options   # alt data
uv run bioterm signals && uv run bioterm backtest
uv run bioterm serve                   # localhost:8501
```
