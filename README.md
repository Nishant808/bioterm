# BioTerm

An open-source, self-hosted **biotech / pharma intelligence terminal**.

BioTerm ingests **prices, financials, clinical pipelines, SEC filings, FDA data, news,
specialist-fund and whole-market 13Fs, short volume and options** for the listed
biotech/pharma sector. It turns them into a transparent **Focus Score** (how much
attention a name deserves), an **early BUY / SELL signal engine** (which names show
converging evidence of a move), a **real-time layer** (halts, SEC filings within
minutes, wires, big movers and why they moved), a **Copilot** that answers questions
from the database with citations, and alerts to Telegram, Slack, Discord, phone push
or email. It is built for a **~6-month swing horizon**: the goal is to surface names
*before* a pipeline-driven move (a Phase 3 readout, a PDUFA date, an FDA action).

> **This is a monitoring and screening tool, not investment advice.** Scores and
> signal labels are screening states computed from public data. Every input is shown
> so you can disagree with it. You supply the judgement on whether the science works
> (via watchlist *conviction*).

**Data** comes from no-signup public sources: Yahoo Finance (prices, fundamentals,
options), SEC EDGAR (filings, live current-filings feed, full-text search, XBRL,
Form 4, 13F-HR, the quarterly 13F data sets, company browse by SIC code),
ClinicalTrials.gov v2, openFDA (approvals, FAERS), the FDA Orange Book, the Federal
Register (advisory committees), FINRA Reg SHO, Nasdaq Trader (halts), USAspending,
SSGA (XBI NAV/flows), Europe PMC, OpenFIGI and publisher/wire RSS feeds.
**Optional keys**, entered on the Settings page (stored encrypted): an Anthropic or
any OpenAI-compatible key for the AI features, Finnhub for a third live-quote source,
and your notification channels.

---

## What's in it

**Signals & scoring** — Focus Score with a per-name decomposition; 39 detectors in six
evidence families (price, catalysts, cash & dilution, insiders & funds, news &
regulatory, options & short flow) combined into STRONG BUY … STRONG SELL with the
evidence listed; a daily backtest (event study, point-in-time factor test, live track
record of calls and of every detector).

**Real-time** — NYSE-calendar-aware pulse every 2 hours on Actions (every 5 minutes
with the Docker/launchd worker or while the app is open): trading halts, 8-K / 424B / S-3 /
13D filings matched by CIK, GlobeNewswire / PR Newswire, movers with "why it moved";
live quotes with Yahoo → Nasdaq → Finnhub failover; ticker tape.

**Catalyst intelligence** — PDUFA dates from EDGAR full-text search and AI-read news,
FDA advisory committees from the Federal Register, trial change radar (date slips,
enrollment complete, suspensions), a catalyst outcome database with base rates,
phase-transition PoS priors (BIO/Informa/QLS 2011–2020), options-implied vs realized
moves, competitive landscape with read-through alerts, industry and CHMP calendar.

**Fundamentals & ownership** — cash / runway / below-cash screen, dilution radar
(shelf, recent raises, warrant and option overhang, Form 144), rNPV per molecule and
sum-of-the-parts, whole-market 13F holders plus specialist funds, 13D/13G activists,
Orange Book loss-of-exclusivity, FAERS trends, government awards, XBI flows and
rebalance pressure, short-interest trend.

**AI (with your key)** — Copilot with tool use over the database and SEC documents,
answers cited [n]; headline event extraction (toplines, CRLs, PDUFA dates) feeding the
catalyst calendar and two detectors; 8-K summaries; 10-K risk-factor diffs; a daily
brief to your channels. Daily spend cap and usage chart on Settings.

**Terminal UI** — command bar with mnemonics (`VRTX CAT`, `SCR`, `MKT`, `CMP A B`,
`/` or Ctrl/Cmd+K), TradingView Lightweight Charts with signal and catalyst markers,
live sector heatmap and breadth, Screener with presets, saved screens and entry
alerts, tear sheets (printable HTML + Excel), alert centre with per-channel routing
and snoozes, linked-panel Workspace with saved layouts, Data health page.

**Platform** — core universe (XBI + seed + watchlist) plus an extended tier of every
other US-listed biopharma by SEC industry code; point-in-time snapshots; 13
data-quality checks; retention; backups; versioned migrations; circuit breakers; an
owner passcode so visitors are read-only; a read-only JSON API.

---

## Quick start

```bash
uv venv --python 3.13
uv pip install -e ".[dev]"
cp .env.example .env          # then edit BIOTERM_SEC_USER_AGENT to your name + email

uv run bioterm init-db
uv run bioterm universe                 # XBI + seed + watchlist
uv run bioterm ingest --limit 25        # first ingest over a 25-ticker slice (~2-4 min)
uv run bioterm score && uv run bioterm signals
uv run bioterm serve                    # open http://localhost:8501
```

Open **Settings** in the app to set the owner passcode, paste an LLM API key (tested
before it is saved; delete it any time), and connect alert channels.

A full refresh over the core universe (~175 names) takes about 25 minutes, dominated
by per-ticker news queries and ClinicalTrials.gov calls; the extended tier adds a few.

### Keeping it live

- **Free cloud path** (what the hosted instance uses): GitHub Actions for ingestion
  (full refresh at the US open and close, news 3×/day, pulse every 2 hours, weekly
  backup) +
  Streamlit Community Cloud for the dashboard + Neon Postgres. See
  [deploy/README.md](deploy/README.md).
- **Always-on box**: `cd deploy && docker compose up -d --build` runs the scheduler,
  the 5-minute pulse worker, the API and the dashboard on one volume.
- **Laptop**: `uv run bioterm scheduler` (and `uv run bioterm worker` for the pulse).

---

## How the Focus Score works

```
focus = conviction_mult · insider_mult · ( w_mom·momentum + w_cat·catalyst + w_news·newsflow ) − w_risk·risk
```

| Component | What goes in | Source |
|---|---|---|
| **momentum** | 1/3/6-mo return percentile, 20-day volume z-score, position in 52-week range, MACD/RSI gate | `prices` → `technicals` |
| **catalyst** | upcoming catalysts in the horizon, weighted by type (PDUFA / Phase 3 readout > FDA action > Phase 2 > earnings) and proximity | trials, PDUFA/AdCom extraction, news, earnings, manual dates |
| **newsflow** | headline volume vs baseline, tone (FinBERT/VADER), biotech event tags | `news` |
| **risk** *(subtracted)* | cash runway < 4 quarters, dilution filings, negative events | XBRL + `filings` + `news` |
| **conviction_mult** | your 1–5 watchlist rating → 0.6–1.4 | you |
| **insider_mult** | cluster open-market insider buying | Form 4 |

Weights, catalyst weights, the event lexicon and the conviction map live in
[`config/settings.yml`](config/settings.yml).

## How the signal engine works

A detector that fires contributes a strength *s* ∈ [0, 1]; they combine as independent
evidence — `bull = 1 − Π(1 − s)` over buy detectors, `bear` likewise — and
**net = bull − bear**. Net ≥ 0.25 is **Buy**, ≥ 0.55 **Strong buy** (mirrored for
sells), and a *Strong* call needs at least two families to agree. Strengths are scaled
by the sector regime, your conviction, company size, 13F filing age and — for price
detectors — their measured edge in the latest backtest. The first live backtest found
most price-only detectors have little or negative 3-month edge in biotech; the
calibration damps them. Event detectors are scored live, firing by firing.

---

## Commands

```
bioterm init-db                    create / migrate the schema
bioterm universe [--force]         rebuild the core universe
bioterm ingest [--limit N] [--only prices,news,...] [--preset fast|open|full]
bioterm score | signals | backtest recompute
bioterm pulse [--no-deliver]       one real-time pass (halts, filings, wires, movers)
bioterm worker [--interval 300]    always-on pulse loop
bioterm ai [--brief]               AI jobs (no-op without a key)
bioterm dq                         data-quality checks
bioterm retention [--dry-run]      prune + database size
bioterm backup / restore           JSON-lines zip of every table
bioterm backfill prices|outcomes|institutions
bioterm api                        read-only JSON API (pip install '.[api]'; bearer token)
bioterm status | serve | scheduler
```

## Dashboard pages

- **Overview · Signals · Stock detail · Copilot**
- **Intelligence** — Focus list · Screener · Smart money & flow · Molecules · Backtest
- **Markets** — Market (heatmap, breadth, movers, halts, filings) · Catalysts · News · Compare
- **Workspace** — Workspace · Watchlist · Alerts · Paper trading · Data health · Settings

## Configuration

| File | Purpose |
|---|---|
| `config/settings.yml` | universe + tiers, score weights, detectors, event lexicon, retention |
| `config/watchlist.yml` | seed watchlist (the app's Watchlist page is the source of truth after) |
| `config/universe_seed.yml` | large-cap pharma / biotech anchors |
| `config/sources.yml` | news + wire RSS feeds |
| `config/institutions.yml` | specialist funds whose 13F-HR filings are tracked |
| `config/pos_priors.yml` · `config/events.yml` | PoS priors · verified industry calendar |
| `.env` | `DATABASE_URL`, `BIOTERM_SEC_USER_AGENT`, optional `BIOTERM_ADMIN_PASSWORD`, `BIOTERM_SECRET_KEY` |

## Known limitations

- No paid feeds: live quotes are Yahoo's public feed with Nasdaq / Finnhub failover,
  not an exchange-licensed consolidated tape; no Level 2 or streaming ticks.
- PDUFA dates come from company disclosures (EDGAR full-text search, press releases);
  a date a company never states publicly can't be found.
- 13F positions are quarter-end longs filed up to 45 days later; FINRA short *volume*
  is not short *interest*; options chains are delayed snapshots.
- The backtest's history is today's XBI membership (survivorship bias) and ignores
  costs; membership is snapshotted from now on.
- The hosted ingestion runs on a private repo's Actions minutes; a public repo (or the
  Docker worker) removes that ceiling.

## Disclaimer

BioTerm is for research and educational use. Nothing it produces is a recommendation
to buy or sell any security. Markets are risky; biotech especially so. Do your own
diligence.
