# CLAUDE.md — working on BioTerm

Biotech/pharma **intelligence terminal**, 6-month swing horizon. Surfaces names
*before* a pipeline-driven move: a Focus Score (attention ranking) plus an early
BUY/SELL signal engine over price, catalysts, cash, insiders, specialist-fund 13Fs,
news (FinBERT + LLM event extraction) and options/short flow, a real-time layer
(halts, live SEC filings, wires, movers), a Copilot over the database, and alerts to
Telegram / Slack / Discord / phone push / email. Monitoring/screening tool — **never** framed as
investment advice (the labels are screening states, not recommendations).

**Read `DEPLOYMENT_LOG.md` first** — it's the live state + resume checklist.

## Layout

```
src/bioterm/
  config.py     YAML + env (settings.yml, institutions.yml = tracked 13F funds, sources.yml
                = RSS/wire feeds, pos_priors.yml, events.yml = verified industry calendar)
  db.py         SQLAlchemy Core schema (57 tables) + portable bulk_upsert + migrate()
                (ADD COLUMN for missing columns) + versioned @migration(n) steps
  store.py      DB-backed user state (watchlist / manual catalysts / notes / app_meta /
                pf_* / molecules) — YAML seeds the research state once
  vault.py      encrypted secrets (Fernet, key from BIOTERM_SECRET_KEY or the DB creds);
                env first, then vault. Only CATALOG names can be stored
  auth.py       owner passcode (PBKDF2 hash in app_meta; BIOTERM_ADMIN_PASSWORD overrides)
  notify.py     Telegram / Slack / Discord / ntfy / email, per-kind routes, snoozes
  market_calendar.py  NYSE sessions + holidays; CLI gates for the workflows
  quotes.py     live quotes: Yahoo -> Nasdaq -> Finnhub failover, stored-close fallback
  realtime.py   pulse (halts, live filings, wires, movers + why) under a DB lease; worker
  universe.py   core (XBI + seed + watchlist) and extended tier (SIC crawl) -> securities
  screener.py   one-row-per-name frame, filter engine, saved screens + entry alerts
  tearsheet.py  printable HTML + Excel per name
  maintenance.py retention windows, db size, JSON-lines backup/restore, backfills
  api.py        read-only FastAPI (bearer token), `bioterm api` — optional `api` extra
  portfolio.py  paper-trading maths — positions (avg cost), cash, equity curve, P&L (pure)
  httpx_util.py pooled session, retry/backoff, per-host throttle, circuit breaker
  ai/           provider adapter (Claude via the anthropic SDK / any OpenAI-compatible),
                budget + usage ledger, tools.py (DB tools with citations), copilot.py,
                jobs.py (news event extraction, 8-K summaries, 10-K risk diffs, brief)
  ingest/       prices fundamentals edgar clinical fda insiders news short_volume
                institutions options molecules · halts edgar_live pdufa (EDGAR FTS +
                Federal Register AdComs) · whole13f drugs (Orange Book LOE + FAERS) gov
                (USAspending) etf (XBI flows) sic_universe (extended tier)
                (each: run(...) -> dict, bounded + wall-clock budget, fail soft)
  process/      technicals sentiment finbert catalysts score molecules smart_money
                signals backtest · trial_changes outcomes (catalyst outcome DB) landscape
                pos (phase-transition priors) industry_calendar valuation (rNPV/SOTP)
                snapshots (point-in-time) dq (data-quality checks)
  alerts.py     rule engine + @register(kind) sources (halt, filing, mover, trial change,
                read-through, screen) -> alerts_fired -> notify routes
  pipeline.py   run_job() wrapper (logs to ingest_runs) + run_full_refresh() groups:
                universe (+ weekly SIC crawl) · market · fundamentals · pipeline · news ·
                insiders · alt data · nlp · intel · recompute · backtest · research ·
                extended · housekeeping (snapshots, retention, DQ)
  scheduler.py  APScheduler (local "always on")
  cli.py        typer: init-db universe ingest score signals backtest nlp alerts pulse
                worker ai status backup restore retention backfill dq api serve scheduler
dashboard/      Streamlit — Home.py (router: st.navigation top bar with sections, logo,
                CSS, ticker tape, command bar, footer; starts the in-app pulse thread)
                app_pages/  "" : overview signals stock copilot
                            Intelligence: focus screener smart_money molecules backtest
                            Markets: market catalysts news compare
                            Workspace: workspace watchlist alerts portfolio health settings
                _ui.py (design system: tokens + components + chart helpers + signal
                taxonomy DETECTORS/SIGNAL_FAMILIES + signal_rows/call_rows)
                _shared.py (cached DB reads) · _live.py (live quotes, 60 s cache)
                _auth.py (owner lock: can_edit / guard / header chip) · _command.py
                (mnemonics + search) · _charts.py (Lightweight Charts, vendored in
                static/) · _worker.py (in-app pulse) · assets/ (logo)
.streamlit/config.toml   native theme + enableStaticServing (dashboard/static/)
.github/workflows/  ingest-full.yml: weekdays at the US open (light preset) + close (full
                    refresh + FinBERT + AI brief), NYSE-calendar gated · ingest-fast.yml
                    3/day · pulse.yml every 2 h in US hours (gated) · backup.yml weekly ·
                    ci.yml (tests + ruff on main/PRs) · probe.yml (push to main-vcyb9o:
                    every job against live sources on Postgres 16, then every page)
deploy/         Dockerfile, compose (scheduler, pulse worker, API, dashboard), launchd
                (scheduler + pulse agents), setup-github.sh, README.md
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
- **Prices shown in the app are always live** (`_live.quotes/quote/history/closes`,
  Yahoo, 60 s cache; the stock page's quote re-fetches every 60 s via `st.fragment`).
  The ingested `prices` table feeds the engines only — never read it in a page. If
  Yahoo fails, `_live` falls back to the stored close and `source_note()` says so.
  Tests set `BIOTERM_LIVE_PRICES=0` (conftest) to force that offline path.
- Logo: edit `dashboard/assets/make_logo.py` and regenerate — the wordmark is Inter
  converted to paths (st.logo is an `<img>`, it can't load web fonts).
- No repeated disclaimer on pages — it lives once in the page footer (`_ui.footer()`,
  rendered by the router).

## Coverage tiers

`securities.tier`: **core** (NULL counts as core) = XBI + seed + watchlist — every job,
the Focus Score and the signal engine. **extended** = the rest of US-listed biopharma by
SEC SIC code (2834/2835/2836/8731), added by the weekly `sic_universe` crawl — only
prices (2y), technicals and a rotating EDGAR + fundamentals slice
(`universe.extended_per_run`), visible in the Screener, the Market "whole sector"
scope, the stock page and the API. **inactive** = dropped out (kept for history).
`universe_tickers(tier="core")` is the default everywhere; heavy jobs and anything
per-name that costs requests must stay on core. Watchlisting promotes to core; a
rebuild demotes names that left XBI (only when the XBI download itself succeeded).

## Secrets, owner lock, AI

- Secrets: `vault.get(name)` (env first, then the encrypted `app_secrets` row). New
  secret = add it to `vault.CATALOG`; the Settings page's `secret_editor()` gives it
  add / test / delete. Never log or render a value — `mask()` shows the last 4.
- Writes in the dashboard go through `_auth.can_edit()` / `_auth.guard(what, key)`;
  read-only visitors see everything but can't change state. Tests unlock via the
  header form (`unlock_header_code`).
- LLM calls: `bioterm.ai.complete()` / `run_agent()` only — they pick the provider,
  enforce `daily_budget_usd` (Copilot gets 1.5x headroom) and record `llm_usage`.
  Without a key every AI job is a no-op (`AIUnavailable`), never an error. Prompts
  forbid buy/sell advice; Copilot answers cite tool results as [n].

## Real-time and alerts

- `realtime.pulse()` runs from three places — `pulse.yml`, `bioterm worker`
  (Docker/launchd) and the in-app thread (`dashboard/_worker.py`) — and a lease in
  `app_meta` (`worker_lease`) makes sure only one fires alerts at a time.
- New alert kind: `@alerts.register("kind")` a pure `fn(rules) -> list[dict]`; state
  changes go in an optional `fn.commit()` that `alerts.run` calls after persisting.
  Add the kind to `notify.KINDS` so it gets a routing row.

## Housekeeping

- `pipeline.housekeeping()` ends every full refresh: `snapshots.run` (core
  fundamentals daily; catalysts and membership as changes — `catalysts_known_on(day)` /
  `members_on(day)` rebuild the past), `maintenance.retention` (windows in
  `RETENTION` / settings `retention:` — Neon's free plan is 512 MB) and `dq.run`
  (13 checks -> Data health page; a `fail` is sent to the channels routed for "dq").
- Backups: `bioterm backup` / `restore` (JSON lines in a zip, no secrets unless asked);
  `backup.yml` keeps a weekly artifact for 21 days.

## Focus Score

```
focus = conviction_mult · insider_mult · (w_mom·momentum + w_cat·catalyst + w_news·newsflow) − w_risk·risk
```
All weights + the event lexicon in `config/settings.yml`. Every input is stored in
`scores.rationale` (JSON) and rendered on the *Stocks in Focus* decomposition.
`conviction_mult` = the user's 1–5 watchlist rating. `insider_mult` = cluster
open-market insider buying.

## Signal engine (`process/signals.py`)

39 detectors in six evidence families (technical, event, capital, people, news,
flow) each fire with a strength 0–1 (incl. trial halted / readout delay / enrollment
complete from the trial-change radar, activist 13D, and AI-read news events). `bull = 1 − Π(1 − s)` over BUY detectors, `bear`
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
"fix" that by raising their strengths. The event detectors have no price-only history:
`backtest.detector_record()` scores every live firing forward (Backtest page, "Live
detector record") — that is where their edge will show, or not.

## Conventions

- **DB is source of truth** for anything the dashboard edits. `config/*.yml` only seed
  empty tables (`store.seed_from_yaml`, called by `init_db`). Don't reintroduce YAML writes.
- `bulk_upsert(table, rows, update_only=[...])` for partial-row writes — without
  `update_only` it overwrites unlisted columns with NULL.
- Every new ingest source: bounded request count + a wall-clock budget (see `fda.py`,
  `insiders.py`, `institutions.py`); fail soft (warn, continue), never abort the refresh.
- Schema changes: add tables/columns in `db.py`; `init_db()` runs `migrate()` which only
  ADDs missing nullable columns, then the versioned `@migration(n, "...")` steps (data
  fixes, indexes, renames) recorded in `schema_migrations` — append, never edit one.
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
- Market-hours logic uses `market_calendar` (NYSE holidays + early closes), never a bare
  weekday check. Workflows gate on `python3 src/bioterm/market_calendar.py gate ...`.
- The dashboard reads **only** through `_shared.q` / cached helpers and must render with
  every table empty (a new database, a failed source) — `tests/test_dashboard.py`
  checks both.
- Commit messages end with the Co-Authored-By trailer. Don't push / create PRs unless asked.

## Run locally

```bash
uv pip install -e ".[dev]"
uv run bioterm init-db && uv run bioterm universe
uv run bioterm ingest --limit 40      # fast slice
uv run bioterm ingest --only shortvol,institutions,molecules,options   # alt data
uv run bioterm signals && uv run bioterm backtest
uv run bioterm ingest --only sicuniverse,extended      # extended tier
uv run bioterm pulse --no-deliver      # one real-time pass (halts, filings, wires, movers)
uv run bioterm dq && uv run bioterm retention --dry-run
uv run bioterm backup                  # backups/bioterm-<date>.zip
BIOTERM_API_TOKEN=x uv run --extra api bioterm api     # localhost:8000/docs
uv run bioterm serve                   # localhost:8501
```
