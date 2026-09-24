# BioTerm

An open-source, self-hosted **biotech / pharma intelligence terminal**.

BioTerm ingests **technicals + financials + clinical-pipeline data + news +
specialist-fund 13Fs + short volume + options** for a biotech/pharma universe. It
turns them into a transparent **Focus Score** (how much attention a name deserves)
and an **early BUY / SELL signal engine** (which names show converging evidence of a
move), tests both against history, and serves an interactive Streamlit dashboard.
It is built for a **~6-month swing horizon**: the goal is to surface names *before* a
pipeline-driven move (a Phase 3 readout, a PDUFA date, an FDA action), not to trade
intraday.

> **This is a monitoring and screening tool, not investment advice.** The Focus Score
> ranks how much *attention* a name deserves given its catalyst calendar, momentum and
> news flow. Every input is shown so you can disagree with it. You supply the judgement
> on whether the underlying science will actually work (via watchlist *conviction*).

All data comes from **no-signup public sources**: Yahoo Finance (`yfinance`: prices,
fundamentals, options chains), SEC EDGAR (filings, Form 4, 13F-HR), ClinicalTrials.gov
API v2, openFDA, FINRA Reg SHO daily short volume, Europe PMC, OpenFIGI (CUSIP →
ticker, keyless tier) and publisher RSS feeds. No API keys. Headline tone uses
FinBERT (ProsusAI/finbert, open weights) when installed, VADER otherwise.

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

## How the signal engine works

Each name is checked by ~33 detectors in six **evidence families**:

| Family | Buy-side examples | Sell-side examples | Source |
|---|---|---|---|
| Price & volume | 52-week breakout on volume, golden cross, accumulation (money flow), RS leader | death cross, loses 200-day, volume surge down, crash day, distribution | `prices` |
| Catalysts & pipeline | pre-catalyst setup (readout 10–120 days out, not extended, funded), new Phase 2/3 | sell-the-news risk (+40% into a binary event), catalyst vacuum | `catalysts`, trials |
| Cash & dilution | — | 424B5/S-1/S-3 filed, runway < 3 quarters with no raise, going-concern | EDGAR, XBRL |
| Insiders & specialist funds | insider cluster buying, ≥ 2 specialist funds initiating/adding | heavy insider selling, ≥ 2 specialists cutting/exiting | Form 4, 13F |
| News & regulatory | topline win / approval headline, FDA designation, tone inflection | CRL / failed trial / clinical hold headline, tone deterioration | news + FinBERT |
| Options & short flow | unusual call volume, short-squeeze setup | unusual put volume, FINRA short share of volume jumping | options, FINRA |

A detector that fires contributes a strength *s* ∈ [0, 1]. They combine as independent
evidence — `bull = 1 − Π(1 − s)` over buy detectors, `bear` likewise — and
**net = bull − bear**. Net ≥ 0.25 is **Buy**, ≥ 0.55 **Strong buy** (mirrored for
sells), and a *Strong* call also needs at least two families to agree. Strengths are
scaled by the sector regime (XBI trend), your watchlist conviction, company size, the
age of a 13F, and — for price detectors — by their measured edge in the latest backtest.
Every call lists its evidence on the Signals page; a change of call fires an alert.

**Backtest** (`bioterm backtest`, daily): an event study of every price detector
(excess return vs the equal-weight universe at 1/3/6 months, hit rate, t-stat), a
point-in-time factor test of the Focus Score momentum and the technical signal
(IC, quintile spread, top-quintile equity curve vs XBI), and the live track record of
the engine's own calls. Caveats are shown on the page: the universe is today's XBI
(survivorship bias), costs aren't modelled, and non-price detectors can only be scored
live. The first live run found most price-only detectors have little or negative edge
in biotech over 3 months — the calibration damps them accordingly.

---

## Configuration

| File | Purpose |
|---|---|
| `config/settings.yml` | horizon, universe toggles, score weights, event lexicon |
| `config/watchlist.yml` | your names + conviction + thesis (Watchlist page writes here) |
| `config/universe_seed.yml` | bundled large-cap pharma / biotech anchors |
| `config/sources.yml` | news RSS feed list |
| `config/catalysts_manual.yml` | PDUFA / AdCom / readout dates you know from your own research |
| `config/institutions.yml` | the biotech specialist funds whose 13F-HR filings are tracked |
| `.env` | `DATABASE_URL`, `BIOTERM_SEC_USER_AGENT`, universe cap |

---

## Commands

```
bioterm init-db                 create the database schema
bioterm universe [--force]      build/refresh the ticker universe
bioterm ingest [--limit N] [--only prices,news,clinical,...]
bioterm score                   recompute catalysts + Focus Score
bioterm signals                 recompute BUY/SELL signals, print the calls
bioterm backtest                event study + factor backtest + track record
bioterm nlp                     FinBERT headline tone (needs torch + transformers)
bioterm status                  recent ingest runs + table row counts
bioterm serve [--port 8501]     launch the dashboard
bioterm scheduler               always-on background refresh loop
```

## Dashboard pages

- **Overview** — signal radar (strongest buy/sell calls, sector regime), KPIs, top focus names, high-signal headlines, next catalysts
- **Signals** — buy/sell boards, calls that changed since the last run, the full board with evidence per name, bull-vs-bear map, what's firing, method + tested edge
- **Stock detail** — the call and its evidence, candlestick + indicators, pipeline + tracked molecules, catalysts, news sentiment, insiders, specialist funds + short volume + options, SEC filings
- **Focus list** — the ranked leaderboard with the signal call and a per-name score decomposition
- **Smart money & flow** — where specialist funds bought and sold last quarter (13F), crowding, each fund's book, FINRA short share of volume, options positioning
- **Molecules** — per-drug dossiers: trials by NCT ID across all sponsors, readout timeline, headlines, catalysts, papers; add/edit molecules and aliases
- **Backtest** — equity curve, quintiles, factor scorecard, event study per detector, live track record
- **Catalysts · News · Compare** — calendar, filterable feed, side-by-side names
- **Watchlist · Alerts · Paper trading** — conviction + thesis, alert rules (incl. signal changes) and history, a simulated long-only desk

## Known limitations

- **PDUFA / AdCom dates** are not in any no-signup structured feed. BioTerm approximates
  catalyst timing from trial completion dates and regex date-extraction on news; use
  `config/catalysts_manual.yml` to pin the ones you care about.
- yfinance is an unofficial Yahoo scrape — occasionally a ticker returns no data for a run.
- Headline tone is FinBERT when the NLP extra is installed (the daily Actions run does),
  VADER otherwise; both are blended with a biotech event-tag lexicon.
- 13F filings describe long positions at quarter end and land up to 45 days later;
  FINRA short *volume* is not short *interest*; options chains are delayed snapshots.
- The backtest universe is today's index membership (survivorship bias) and ignores costs.

## Layout

```
src/bioterm/
  config.py db.py universe.py httpx_util.py pipeline.py scheduler.py cli.py
  ingest/    prices fundamentals edgar clinical fda insiders news
             short_volume institutions options molecules
  process/   technicals sentiment finbert catalysts score molecules smart_money
             signals backtest
dashboard/   Home.py (router) + app_pages/ + _ui.py (design system) + assets/
deploy/      Dockerfile docker-compose.yml launchd/ github/
tests/
```

## Disclaimer

BioTerm is for research and educational use. Nothing it produces is a recommendation
to buy or sell any security. Markets are risky; biotech especially so. Do your own
diligence.
