# BioTerm — Deployment & Build Log

A running journal so anyone (you, or a fresh Claude session) can resume instantly.
**Newest journal entries at the bottom.** The `RESUME HERE` block is always current.

---

## ⏯️ RESUME HERE

**Where we are:** MVP is built and green. All cloud plumbing is written and committed.
The project is a standalone git repo at `~/Desktop/cld` (2 commits, no remote yet).
Blocked on **4 account-gated steps only you can do** (below). Once step A + B are done,
a Claude session can run `bash deploy/setup-github.sh` and finish the GitHub side.

### The 4 things only YOU can do (Claude cannot create accounts / auth as you)

| | Step | How | Output you'll paste back |
|--|------|-----|--------------------------|
| **A** | **Neon Postgres** | Sign up at <https://neon.tech> (free). Create a project/database. Copy the **connection string** from the dashboard (looks like `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`). | that connection string |
| **B** | **GitHub auth** | In Terminal: `export PATH="/opt/homebrew/bin:$PATH"; gh auth login` → GitHub.com → HTTPS → login with browser. (`gh` is already installed.) | nothing — just confirm "done" |
| **C** | **Streamlit Community Cloud** | After the repo exists (step D): <https://share.streamlit.io> → sign in with GitHub → **New app** → repo `bioterm`, branch `main`, main file `dashboard/Home.py` → **Advanced → Python 3.12** → paste secrets (script D prints the exact block) → **Deploy**. | the app URL |
| **D** | *(Claude does this once A+B are done)* create repo + push + set secrets + kick first ingest | Claude runs `deploy/setup-github.sh` | — |

**Fastest path:** do A and B, tell Claude "Neon URL is `...`, gh is authed", and Claude
runs the rest. Then you do C.

### Deployment checklist

| # | Step | Who | Status |
|---|------|-----|--------|
| 1 | Standalone git repo (`git init`) | Claude | ✅ commit `84d7599` |
| 2 | DB-backed watchlist / manual catalysts / notes / meta (survives ephemeral cloud FS) | Claude | ✅ commit `925252b` (`src/bioterm/store.py`, 4 new tables) |
| 3 | Postgres readiness | Claude | ✅ **live-tested** against Postgres 16 in Docker — `init-db`, YAML seed, a full `ingest` (prices/technicals/edgar/fundamentals/news/catalysts/score), dashboard reads, and every `store.py` write path all pass |
| 4 | `.github/workflows/ingest-fast.yml` + `ingest-full.yml` | Claude | ✅ |
| 5 | `requirements.txt` + `.streamlit` secrets bridge in `_shared.py` | Claude | ✅ |
| 6 | `deploy/setup-github.sh` one-shot | Claude | ✅ |
| 7 | Dashboard feature pass (buttons, exports, Compare, Alerts, notes) | Claude | ✅ commit `925252b` — 8 pages, all verified rendering |
| 8 | `gh` CLI installed | Claude | ✅ `/opt/homebrew/bin/gh` v2.100 |
| A | **Neon Postgres created** | **YOU** | ⛔ |
| B | **`gh auth login`** | **YOU** | ⛔ |
| D | repo create + push + secrets + first run (`setup-github.sh`) | Claude (needs A+B) | ⛔ |
| C | **Streamlit Cloud app deployed + secrets set** | **YOU** (needs D) | ⛔ |
| E | Verify: Actions run green → data in Neon → dashboard shows it | Claude + you | ⛔ |

### Feature backlog (build with remaining credits)

- [x] Alert **delivery** — `src/bioterm/alerts.py` + `bioterm alerts` (step in ingest-fast). Telegram push if `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID` secrets set; always records to `alerts_fired`. Dashboard Alerts page has firing-now + history tabs.
- [x] Focus-score history — `score_snapshots` table (one row/ticker/run, 14-day retention). Movers now diff the last snapshot ≥6h old. Sparkline on Stock Detail (shows once ≥2 runs exist).
- [x] "Refresh data now" button — sidebar button that calls the GitHub `workflow_dispatch` API. Gated on `GH_DISPATCH_TOKEN` (fine-grained PAT, Actions:write on the repo) + `GH_REPO` ("owner/bioterm") secrets. Hidden if unset.
- [x] **Insider transactions (SEC Form 4)** — `src/bioterm/ingest/insiders.py` parses
  the ownership XML (`{dir}/form4.xml`) for watchlist + top-60 focus names; `insider_txns`
  table; `net_open_market()` rollup; cluster open-market **buying** → `insider_mult`
  (1.0–1.15) folded into the Focus Score; Stock Detail "👤 Insiders" tab. Live-tested
  (144 txns / 8 tickers in 16 s). Note: biotech insiders rarely open-market **buy**, so
  the multiplier is usually 1.0 — which is the point, it only fires on a real signal.
- [ ] FinBERT sentiment (swap `process/sentiment.py`; ~400 MB model download in the Actions runner — cache it)
- [ ] LLM extraction of expected-readout dates from full news bodies (needs an LLM API key)
- [ ] Backtest: replay the score against past biotech moves
- [ ] Per-molecule tracking (link watchlist `molecules` → specific NCT ids / catalysts)
- [ ] 13F holdings changes (whalewisdom-style, from SEC 13F-HR)

### Local dev

Local Streamlit server was **stopped** (per your request). Re-run for dev:
`cd ~/Desktop/cld && uv run bioterm serve`. Local DB is `data/bioterm.db` (SQLite,
gitignored) with the last 55-ticker refresh in it.

---

## Environment notes (this machine)

- `~/Desktop/cld` is its own git repo now (was a subdir of the `$HOME` repo — that's
  why the very first `git status` showed all your home dotfiles).
- Python 3.13.9 (miniconda) → project uses an isolated `uv` venv at `.venv/`.
- `gh` v2.100 installed via Homebrew (`/opt/homebrew/bin` — not on the default PATH,
  prefix commands with `export PATH="/opt/homebrew/bin:$PATH"`).
- Docker daemon not running; `psql` not installed → no local Postgres test; code is
  Postgres-ready and compile-verified against the `postgresql` dialect.
- `.env` needs `BIOTERM_SEC_USER_AGENT="BioTerm/0.1 (nishantthalwal@gmail.com)"`.

## Key design decisions

- **Two workflows, not one.** `ingest-full` (everything, ~20 min) 3×/day; `ingest-fast`
  (news+sentiment+catalysts+score, ~6 min) every 30 min. Keeps "Stocks in Focus" and
  the feed fresh without burning Actions minutes on the slow FDA/fundamentals calls.
- **Public repo strongly recommended** — unlimited Actions minutes. Private free tier
  is 2000 min/month and `ingest-fast` alone is ~5000/month. `setup-github.sh` defaults
  to `REPO_VISIBILITY=public`. BioTerm is open-source anyway.
- **DB is the source of truth for user edits.** YAML files under `config/` seed the
  `watchlist` / `manual_catalysts` tables once (when empty), then the dashboard writes
  to the DB. This is what makes the cloud dashboard's buttons actually persist —
  Streamlit Cloud's filesystem is ephemeral and is a *different checkout* than the
  Actions runner.
- **openFDA has a 240 s wall-clock budget** in `ingest/fda.py` (it rate-limits hard).

---

## Journal

### 2026-09-09 — session 1 (MVP)

- Built the full pipeline (ingest → process → score → 6-page Streamlit dashboard),
  26 tests. Verified on a 55-ticker slice.

### 2026-09-09 — session 2 (deploy prep + features) — **this session**

- Stopped the local Streamlit server.
- `git init -b main` in `~/Desktop/cld`; commit `84d7599` (52 files, clean — big
  `.RData` files correctly ignored).
- Installed `gh` v2.100 (Homebrew). Not authed (needs your `gh auth login`).
- **DB-backed user state:** added tables `watchlist`, `manual_catalysts`, `notes`,
  `app_meta`; new `src/bioterm/store.py` with get/save helpers + one-time YAML seed
  (`seed_from_yaml`, called from `init_db`). Rewired `universe.build_universe`,
  `process/score.py` (conviction lookup), `process/catalysts.py` (`_from_manual`) to
  read from the DB. Updated `tests/conftest.py` to stub the YAML seed; new
  `tests/test_store.py`. **31 tests green.**
- **Postgres readiness:** added `psycopg[binary]` dep; `db.read_sql` now wraps raw
  strings in `text()`; compile-checked all 15 tables' DDL + the upsert against the
  `postgresql` dialect (passes). Live test deferred until the Neon URL exists.
- **Workflows:** `.github/workflows/ingest-fast.yml` (`*/30`) and `ingest-full.yml`
  (`0 6,13,21`). New `bioterm ingest --preset fast|full`. Removed the old
  `deploy/github/ingest.yml` template.
- **Streamlit Cloud glue:** `requirements.txt` (runtime deps only — the dashboard
  puts `src/` on `sys.path`); `_shared.py` now bridges `st.secrets` → `os.environ`
  for `DATABASE_URL` / `BIOTERM_SEC_USER_AGENT` and calls `init_db()` defensively;
  `.streamlit/secrets.toml.example`.
- **`deploy/setup-github.sh`** — one-shot repo-create + push + `gh secret set` +
  first `workflow run`. Normalises the Neon `postgresql://` scheme to
  `postgresql+psycopg://`. Prints the exact Streamlit Cloud secrets block.
- **Dashboard feature pass** (commit `925252b`, all 8 pages verified rendering in a
  local browser):
  - Stock Detail — conviction slider + add/remove-watchlist buttons, persisted
    research notes (`notes` table), "pin a catalyst" form (`manual_catalysts`).
  - Stocks in Focus — CSV export, one-click add-to-watchlist on the decomposition.
  - Catalyst Calendar — add/delete manual catalysts, CSV export.
  - News Firehose — watchlist-only toggle, CSV export.
  - **new** Compare page — rebased multi-ticker price overlay + side-by-side
    score/fundamental table + catalyst list.
  - **new** Alerts page — rules (score-jump, catalyst-window, event-tags,
    watchlist-only) persisted to `app_meta`; live "what fires now" list (31 firing
    on current data).
- Tested add-to-watchlist end to end (EXEL added via button → row in `watchlist`
  table → removed again to leave your seed list untouched).
- **Postgres live test:** spun up `postgres:16-alpine` in Docker, pointed
  `DATABASE_URL` at it. `bioterm init-db` → 15 tables. YAML seed → watchlist rows.
  `bioterm ingest --limit 10 --only prices,technicals,edgar,fundamentals,news,sentiment,catalysts,score`
  → all green (5020 prices, 397 filings, 483 news, 161 scores). Streamlit dashboard
  read it fine. `store` writes (watchlist add/remove, note, manual catalyst, meta)
  all round-tripped. Tore the container down; Docker Desktop quit; local SQLite
  untouched. **The cloud data path is proven — Neon will "just work".**
- **Feature pass 2** (commit `7908c97`): alerts engine (`src/bioterm/alerts.py`,
  `bioterm alerts`, wired into `ingest-fast.yml`), `alerts_fired` + `score_snapshots`
  tables, Telegram delivery hook (credential-gated), movers via snapshots, Focus-Score
  history sparkline, Alerts page firing/history tabs.
- **Feature pass 3** (this commit): dashboard "↻ refresh data now" sidebar button →
  GitHub `workflow_dispatch` API (gated on `GH_DISPATCH_TOKEN` + `GH_REPO` secrets;
  hidden otherwise). Extended the `st.secrets`→env bridge.
- Commits: `84d7599` MVP · `925252b` deploy prep + features · `246fa73` deploy docs +
  Postgres test · `7908c97` alerts + score history · (next) refresh button + backlog.
- **Next:** wait for your steps A + B, run `setup-github.sh`, you do C, verify E.
  Then the backlog — **insider Form 4 first**.

### 2026-09-09 — session 2, insiders (commit `e9e92a6`)

- SEC Form 4 ingestion. `insider_txns` table, `net_open_market()` 90-day rollup.
- Score: cluster open-market **buying** → `insider_mult` ∈ [1.0, 1.15], multiplies the
  weighted-components term alongside conviction; recorded in `scores.rationale`.
- New Stock-Detail tab. `bioterm ingest --only insiders`; in the full pipeline +
  daily scheduler job. 34 tests total (added parser / rollup / score-lift).
- 4 new DB tables total this session: `score_snapshots`, `alerts_fired`,
  `insider_txns` (+ `watchlist`/`manual_catalysts`/`notes`/`app_meta` earlier) →
  **19 tables**. `bioterm init-db` is idempotent (`create_all` adds only missing
  tables) and was run against the live local DB.

### 2026-09-09 — session 2, later: dashboard now has 8 pages + these buttons

| page | interactive bits |
|---|---|
| Home | KPIs, focus table, movers, high-signal headlines, next catalysts |
| Stocks in Focus | filters, **CSV export**, score decomposition, **★ add to watchlist** |
| Stock Detail | ticker picker, **conviction slider + add/remove watchlist**, **persisted notes**, **Focus-Score history**, **＋ pin a catalyst**, price / pipeline / catalyst / news / **insiders** / filings tabs |
| Catalyst Calendar | filters, **＋ add / delete manual catalysts**, **CSV export**, month buckets |
| News Firehose | filters, **watchlist-only toggle**, **CSV export**, **↻ refresh** |
| Watchlist | **DB-backed editable table**, add rows, save |
| Compare | 2–4 ticker rebased price overlay + side-by-side metrics + catalyst list |
| Alerts | **editable rules (persisted)**, firing-now tab, **history tab w/ delivery status** |
| sidebar (all pages) | data-freshness, **↻ refresh data now** (if GH secrets set) |
