# BioTerm

An open-source, self-hosted **biotech / pharma catalyst-monitoring terminal**.

BioTerm ingests **technicals + financials + clinical-pipeline data + news** for a
biotech/pharma universe, turns it into a transparent **Focus Score**, and serves an
interactive Streamlit dashboard. It is built for a **~6-month swing horizon** — the
goal is to surface names *before* a pipeline-driven move (a Phase 3 readout, a PDUFA
date, an FDA action), not to trade intraday.

> **This is a monitoring and screening tool, not investment advice.** The Focus Score
> ranks how much *attention* a name deserves given its catalyst calendar, momentum and
> news flow. Every input is shown so you can disagree with it. You supply the judgement
> on whether the underlying science will actually work (via watchlist *conviction*).

All data comes from **no-signup public sources**: Yahoo Finance (`yfinance`),
SEC EDGAR, ClinicalTrials.gov API v2, openFDA, and publisher RSS feeds. No API keys.

Design inspiration: [OpenBB](https://github.com/OpenBB-finance/OpenBB)'s
provider/router/core separation — BioTerm copies the pattern (uniform fetchers, one
normalized schema) without the heavy dependency.

---

## Quick start

```bash
uv venv --python 3.13
uv pip install -e ".[dev]"
cp .env.example .env          # then edit BIOTERM_SEC_USER_AGENT to your name + email

uv run bioterm init-db
uv run bioterm universe                 # build the ticker universe (XBI + IBB + seed + watchlist)
uv run bioterm ingest --limit 25        # first ingest over a 25-ticker slice (~2-4 min)
uv run bioterm score                    # compute catalysts + Focus Score
uv run bioterm serve                    # open http://localhost:8501
```

Drop `--limit` once you're happy — a full refresh over the whole universe
(~200–400 names) takes roughly 15–40 minutes, dominated by per-ticker news queries
and ClinicalTrials.gov calls.

### Keeping it live

```bash
uv run bioterm scheduler       # one full refresh, then: news q15m, market q30m, pipeline daily
```

The scheduler only runs while this machine is awake. For true 24/7 see
[deploy/README.md](deploy/README.md) — the recommended free path is GitHub Actions
(ingestion cron) + Streamlit Community Cloud (dashboard) + a free Postgres
(Neon/Supabase), wired by pointing `DATABASE_URL` at the shared database.

---

## How the Focus Score works

```
focus = conviction_mult * ( w_mom·momentum + w_cat·catalyst + w_news·newsflow ) − w_risk·risk
```

| Component | What goes in | Source |
|---|---|---|
| **momentum** | 1/3/6-mo return percentile, 20-day volume z-score, position in 52-week range, MACD/RSI gate | `prices` → `technicals` |
| **catalyst** | Σ of upcoming catalysts in the horizon, weighted by type (Phase 3 readout > FDA action > Phase 2 > earnings) and proximity | `clinical_trials` completion dates + dates parsed from news + earnings + `catalysts_manual.yml` |
| **newsflow** | recent headline volume vs 90-day baseline, mean sentiment (VADER), sum of biotech event-tag weights (topline, CRL, breakthrough, …) | `news` → `sentiment` |
| **risk** *(subtracted)* | cash runway < 4 quarters, recent dilution filings (S-1/S-3/424B5), recent negative event tags | SEC XBRL facts + `filings` + `news` |
| **conviction_mult** | your 1–5 rating from `config/watchlist.yml` → 0.6–1.4 | you |

Weights, catalyst type weights, event lexicon and the conviction map all live in
[`config/settings.yml`](config/settings.yml) and are re-read on every run.
`scores.rationale` stores the full decomposition as JSON; the dashboard renders it.

---

## Configuration

| File | Purpose |
|---|---|
| `config/settings.yml` | horizon, universe toggles, score weights, event lexicon |
| `config/watchlist.yml` | your names + conviction + thesis (Watchlist page writes here) |
| `config/universe_seed.yml` | bundled large-cap pharma / biotech anchors |
| `config/sources.yml` | news RSS feed list |
| `config/catalysts_manual.yml` | PDUFA / AdCom / readout dates you know from your own research |
| `.env` | `DATABASE_URL`, `BIOTERM_SEC_USER_AGENT`, universe cap |

---

## Commands

```
bioterm init-db                 create the database schema
bioterm universe [--force]      build/refresh the ticker universe
bioterm ingest [--limit N] [--only prices,news,clinical,...]
bioterm score                   recompute catalysts + Focus Score
bioterm status                  recent ingest runs + table row counts
bioterm serve [--port 8501]     launch the dashboard
bioterm scheduler               always-on background refresh loop
```

## Dashboard pages

- **Home** — top focus names, today's score movers, high-signal headlines, source health
- **Stocks in Focus** — the ranked leaderboard with an expandable score decomposition per name
- **Stock Detail** — candlestick + indicators, cash-runway gauge, clinical pipeline table + trial timeline, catalyst list, news feed with sentiment, SEC filings
- **Catalyst Calendar** — every dated catalyst in the horizon, grouped by month
- **News Firehose** — merged, filterable feed (ticker / source / event tag / sentiment)
- **Watchlist** — add/remove names, set conviction, edit thesis (persists to `watchlist.yml`)

## Known limitations

- **PDUFA / AdCom dates** are not in any no-signup structured feed. BioTerm approximates
  catalyst timing from trial completion dates and regex date-extraction on news; use
  `config/catalysts_manual.yml` to pin the ones you care about.
- yfinance is an unofficial Yahoo scrape — occasionally a ticker returns no data for a run.
- Sentiment is VADER + a domain lexicon, not a fine-tuned model. FinBERT is a planned upgrade.

## Layout

```
src/bioterm/
  config.py db.py universe.py httpx_util.py pipeline.py scheduler.py cli.py
  ingest/    prices fundamentals edgar clinical fda news
  process/   technicals sentiment catalysts score
dashboard/   Home.py + pages/
deploy/      Dockerfile docker-compose.yml launchd/ github/
tests/
```

## Disclaimer

BioTerm is for research and educational use. Nothing it produces is a recommendation
to buy or sell any security. Markets are risky; biotech especially so. Do your own
diligence.
