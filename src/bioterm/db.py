"""Database layer: SQLAlchemy Core schema + portable bulk upsert.

Default backend is SQLite (``data/bioterm.db``). Set ``DATABASE_URL`` to a
``postgresql+psycopg://`` URL to move the exact same schema to Postgres for a
cloud deployment - no code changes needed.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.engine import Engine

from .config import load_settings

metadata = MetaData()

securities = Table(
    "securities", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("name", String(256)),
    Column("exchange", String(32)),
    Column("cik", String(16)),
    Column("is_watchlist", Integer, default=0),
    Column("in_xbi", Integer, default=0),
    Column("in_ibb", Integer, default=0),
    Column("in_seed", Integer, default=0),
    Column("etf_weight", Float),
    Column("updated_at", DateTime),
    # session 10: coverage tier (core = XBI/IBB/seed/watchlist, extended = rest of
    # US-listed biopharma by SIC code) and the SEC industry code
    Column("tier", String(12)),
    Column("sic", String(8)),
)

prices = Table(
    "prices", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("open", Float),
    Column("high", Float),
    Column("low", Float),
    Column("close", Float),
    Column("adj_close", Float),
    Column("volume", Float),
)

technicals = Table(
    "technicals", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("close", Float),
    Column("sma20", Float),
    Column("sma50", Float),
    Column("sma200", Float),
    Column("rsi14", Float),
    Column("macd", Float),
    Column("macd_signal", Float),
    Column("macd_hist", Float),
    Column("atr14", Float),
    Column("bb_upper", Float),
    Column("bb_lower", Float),
    Column("vol_z20", Float),
    Column("pct_52w_range", Float),   # 0 = at 52w low, 1 = at 52w high
    Column("ret_1m", Float),
    Column("ret_3m", Float),
    Column("ret_6m", Float),
)

fundamentals = Table(
    "fundamentals", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("market_cap", Float),
    Column("shares_out", Float),
    Column("float_shares", Float),
    Column("short_percent_float", Float),
    Column("cash", Float),                 # cash + short-term investments (most recent)
    Column("rd_expense_ttm", Float),
    Column("net_income_ttm", Float),
    Column("op_cash_flow_ttm", Float),
    Column("burn_ttm", Float),             # positive number = annual cash burn
    Column("runway_quarters", Float),
    Column("next_earnings_date", Date),
    Column("sources", String(128)),
    Column("updated_at", DateTime),
    # added in session 9 (auto-migrated onto existing databases by migrate())
    Column("short_ratio", Float),            # days to cover
    Column("held_pct_institutions", Float),
    Column("held_pct_insiders", Float),
    Column("beta", Float),
    # session 10: dilution overhang + balance-sheet extras (XBRL / yfinance)
    Column("warrants_out", Float),
    Column("options_out", Float),
    Column("total_debt", Float),
    Column("xbrl_shares_out", Float),
)

clinical_trials = Table(
    "clinical_trials", metadata,
    Column("nct_id", String(24), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("sponsor", String(256)),
    Column("title", Text),
    Column("phase", String(32)),
    Column("status", String(48)),
    Column("study_type", String(32)),
    Column("start_date", Date),
    Column("primary_completion_date", Date),
    Column("completion_date", Date),
    Column("conditions", Text),
    Column("interventions", Text),
    Column("enrollment", Float),
    Column("last_update_post_date", Date),
    Column("url", String(256)),
    Column("fetched_at", DateTime),
)

fda_events = Table(
    "fda_events", metadata,
    Column("id", String(40), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("kind", String(24)),
    Column("application_number", String(32)),
    Column("brand_name", String(256)),
    Column("generic_name", String(256)),
    Column("sponsor_name", String(256)),
    Column("event_date", Date),
    Column("description", Text),
    Column("url", String(256)),
    Column("fetched_at", DateTime),
)

filings = Table(
    "filings", metadata,
    Column("id", String(64), primary_key=True),   # accession no (dashed)
    Column("ticker", String(16), index=True),
    Column("cik", String(16)),
    Column("form", String(16)),
    Column("filed_date", Date),
    Column("title", Text),
    Column("items", String(256)),
    Column("url", String(256)),
    Column("fetched_at", DateTime),
    Column("source", String(16)),                 # submissions / live (EDGAR current feed)
)

news = Table(
    "news", metadata,
    Column("id", String(40), primary_key=True),   # sha1 of url
    Column("ticker", String(16), index=True),     # primary ticker (may be null)
    Column("tickers_csv", String(256)),           # all matched tickers
    Column("title", Text),
    Column("summary", Text),
    Column("url", String(512)),
    Column("source", String(64)),
    Column("published", DateTime, index=True),
    Column("sentiment", Float),                   # VADER compound [-1, 1]
    Column("event_tags", String(256)),
    Column("event_score", Float),                 # signed sum of matched event weights
    Column("fetched_at", DateTime),
)

catalysts = Table(
    "catalysts", metadata,
    Column("id", String(48), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("type", String(32)),
    Column("title", Text),
    Column("date", Date, index=True),
    Column("months_away", Float),
    Column("confidence", String(16)),
    Column("source", String(48)),
    Column("url", String(256)),
    Column("created_at", DateTime),
)

scores = Table(
    "scores", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("asof", Date, primary_key=True),
    Column("focus_score", Float, index=True),
    Column("momentum", Float),
    Column("catalyst", Float),
    Column("newsflow", Float),
    Column("risk", Float),
    Column("conviction_mult", Float),
    Column("rank", Integer),
    Column("rationale", Text),   # JSON
)

ingest_runs = Table(
    "ingest_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job", String(48)),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
    Column("status", String(16)),
    Column("rows", Integer),
    Column("detail", Text),
)

# one row per ticker per score run - powers day/hour-over-run movers
score_snapshots = Table(
    "score_snapshots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime, index=True),
    Column("ticker", String(16), index=True),
    Column("focus_score", Float),
    Column("rank", Integer),
)

insider_txns = Table(
    "insider_txns", metadata,
    Column("id", String(48), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("filed_date", Date),
    Column("txn_date", Date, index=True),
    Column("owner", String(160)),
    Column("role", String(64)),          # Director / Officer:<title> / 10% owner
    Column("code", String(4)),           # P buy, S sale, M option ex, F tax, A award, G gift…
    Column("acquired_disposed", String(2)),
    Column("shares", Float),
    Column("price", Float),
    Column("value", Float),              # shares * price (signed +buy / -sell)
    Column("url", String(256)),
    Column("fetched_at", DateTime),
    Column("plan_10b5_1", Integer),      # 1 = Form 4 box "made pursuant to a 10b5-1 plan"
)

# append-only record of alerts that fired (from `bioterm alerts`)
alerts_fired = Table(
    "alerts_fired", metadata,
    Column("id", String(48), primary_key=True),
    Column("ts", DateTime, index=True),
    Column("kind", String(24)),
    Column("ticker", String(16), index=True),
    Column("detail", Text),
    Column("weight", Float),
    Column("delivered", Integer, default=0),
)

# ------------------------------------------------------------------ user-editable
# These hold state the dashboard mutates. They are seeded once from the YAML files
# under config/, then the DB is the source of truth (so edits survive on a cloud
# deploy where the filesystem is ephemeral and the Actions runner is a separate
# checkout).

watchlist = Table(
    "watchlist", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("conviction", Integer, default=3),
    Column("thesis", Text),
    Column("molecules", Text),   # JSON array of strings
    Column("added_at", DateTime),
    Column("updated_at", DateTime),
)

manual_catalysts = Table(
    "manual_catalysts", metadata,
    Column("id", String(48), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("type", String(32)),
    Column("date", Date),
    Column("title", Text),
    Column("confidence", String(16)),
    Column("url", String(256)),
    Column("created_at", DateTime),
)

notes = Table(
    "notes", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("body", Text),
    Column("updated_at", DateTime),
)

app_meta = Table(
    "app_meta", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text),       # JSON
    Column("updated_at", DateTime),
)

# ------------------------------------------------------------------ paper trading
# Fully separate from the ingestion pipeline. A portfolio is a starting cash
# balance; positions and equity are *derived* from the trade blotter + EOD prices.

pf_portfolios = Table(
    "pf_portfolios", metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(80)),
    Column("cash_start", Float),
    Column("created_at", DateTime),
)

pf_trades = Table(
    "pf_trades", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("portfolio_id", String(32), index=True),
    Column("ts", DateTime),
    Column("ticker", String(16), index=True),
    Column("side", String(4)),       # BUY / SELL
    Column("qty", Float),
    Column("price", Float),           # simulated fill price
    Column("fees", Float),
    Column("note", Text),
)

# One row per (most recently) checked 10-K/10-Q: does its own text carry a
# going-concern doubt paragraph? id reuses the filing's own accession id, so a
# re-run naturally skips a filing already checked (see edgar.py).
filing_risk_flags = Table(
    "filing_risk_flags", metadata,
    Column("id", String(64), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("form", String(16)),
    Column("filed_date", Date),
    Column("going_concern", Integer, default=0),   # 0/1 - portable across SQLite/Postgres
    Column("checked_at", DateTime),
)

# ------------------------------------------------------------------ smart money (13F)
# Quarterly 13F-HR holdings of a curated set of biotech specialist funds
# (config/institutions.yml). Equity positions only, aggregated per CUSIP.
inst_filers = Table(
    "inst_filers", metadata,
    Column("cik", String(16), primary_key=True),
    Column("name", String(160)),
    Column("short_name", String(64)),
    Column("last_period", Date),
    Column("last_filed", Date),
    Column("checked_at", DateTime),
)

inst_holdings = Table(
    "inst_holdings", metadata,
    Column("id", String(64), primary_key=True),      # cik|period|cusip
    Column("cik", String(16), index=True),
    Column("period", Date, index=True),               # quarter-end the 13F reports on
    Column("filed_date", Date),
    Column("accession", String(32)),
    Column("cusip", String(12), index=True),
    Column("issuer", String(200)),
    Column("title_class", String(64)),
    Column("ticker", String(16), index=True),         # matched universe ticker, if any
    Column("shares", Float),
    Column("value", Float),                           # USD
    Column("fetched_at", DateTime),
)

# CUSIP -> ticker resolutions (name match or OpenFIGI), cached across runs
cusip_map = Table(
    "cusip_map", metadata,
    Column("cusip", String(12), primary_key=True),
    Column("ticker", String(16)),
    Column("issuer", String(200)),
    Column("method", String(16)),                     # name / openfigi / none
    Column("updated_at", DateTime),
)

# ------------------------------------------------------------------ market microstructure
# FINRA Reg SHO daily short-sale volume (consolidated NMS file)
short_volume = Table(
    "short_volume", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("short_volume", Float),
    Column("short_exempt", Float),
    Column("total_volume", Float),
)

# One options snapshot per ticker per day (yfinance chains, front + next expiry)
options_snapshots = Table(
    "options_snapshots", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("spot", Float),
    Column("expiry", Date),
    Column("days_to_expiry", Integer),
    Column("atm_iv", Float),
    Column("iv_back", Float),
    Column("implied_move", Float),        # ATM straddle / spot, front expiry
    Column("call_volume", Float),
    Column("put_volume", Float),
    Column("call_oi", Float),
    Column("put_oi", Float),
    Column("pc_volume_ratio", Float),
    Column("pc_oi_ratio", Float),
    Column("vol_oi_ratio", Float),
    Column("fetched_at", DateTime),
)

# ------------------------------------------------------------------ NLP provenance
# FinBERT scores per headline. news.sentiment holds the best available tone
# (FinBERT once scored, VADER before); this table records which model said what.
news_nlp = Table(
    "news_nlp", metadata,
    Column("id", String(40), primary_key=True),        # news.id
    Column("vader", Float),
    Column("finbert", Float),                          # p(positive) - p(negative)
    Column("label", String(12)),
    Column("confidence", Float),
    Column("model", String(64)),
    Column("scored_at", DateTime),
)

# ------------------------------------------------------------------ per-molecule tracking
molecules = Table(
    "molecules", metadata,
    Column("id", String(48), primary_key=True),        # slug of ticker + name
    Column("ticker", String(16), index=True),
    Column("name", String(120)),
    Column("aliases", Text),                           # JSON list
    Column("indication", String(160)),
    Column("nct_ids", Text),                           # JSON list pinned by the user
    Column("notes", Text),
    Column("created_at", DateTime),
    Column("updated_at", DateTime),
)

# Trials found for a molecule across every sponsor (partners included) -
# kept apart from clinical_trials, which is keyed on the lead sponsor.
molecule_trials = Table(
    "molecule_trials", metadata,
    Column("id", String(80), primary_key=True),        # molecule_id|nct_id
    Column("molecule_id", String(48), index=True),
    Column("ticker", String(16), index=True),
    Column("nct_id", String(24)),
    Column("sponsor", String(256)),
    Column("sponsor_class", String(24)),   # CT.gov leadSponsor.class: INDUSTRY / OTHER / NIH ...
    Column("title", Text),
    Column("phase", String(32)),
    Column("status", String(48)),
    Column("start_date", Date),
    Column("primary_completion_date", Date),
    Column("completion_date", Date),
    Column("conditions", Text),
    Column("interventions", Text),
    Column("enrollment", Float),
    Column("last_update_post_date", Date),
    Column("url", String(256)),
    Column("source", String(16)),                      # pinned / search
    Column("fetched_at", DateTime),
)

molecule_links = Table(
    "molecule_links", metadata,
    Column("id", String(64), primary_key=True),
    Column("molecule_id", String(48), index=True),
    Column("kind", String(16)),                        # news / catalyst / paper
    Column("ref_id", String(64)),
    Column("title", Text),
    Column("date", Date),
    Column("url", String(512)),
    Column("detail", Text),
    Column("created_at", DateTime),
)

molecule_status = Table(
    "molecule_status", metadata,
    Column("molecule_id", String(48), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("n_trials", Integer),
    Column("n_active", Integer),
    Column("top_phase", String(16)),
    Column("next_readout", Date),
    Column("n_news_30d", Integer),
    Column("news_tone_30d", Float),
    Column("papers_total", Integer),
    Column("last_paper_date", Date),
    Column("discovered_aliases", Text),                # JSON: otherNames seen on trial records
    Column("updated_at", DateTime),
)

# ------------------------------------------------------------------ signal engine
# Every detector that fired, per ticker per day - kept as history so the
# signals' own forward returns can be measured (the live track record).
signals = Table(
    "signals", metadata,
    Column("id", String(48), primary_key=True),        # sha1(ticker|code|asof)
    Column("asof", Date, index=True),
    Column("ticker", String(16), index=True),
    Column("side", String(4)),                         # BUY / SELL
    Column("code", String(40)),
    Column("strength", Float),                         # 0..1 after calibration
    Column("title", Text),
    Column("detail", Text),                            # JSON evidence
    Column("ts", DateTime),
)

signal_scores = Table(
    "signal_scores", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("asof", Date, primary_key=True),
    Column("bull", Float),
    Column("bear", Float),
    Column("net", Float),                              # bull - bear, -1..1
    Column("label", String(16)),                       # STRONG BUY ... STRONG SELL
    Column("n_buy", Integer),
    Column("n_sell", Integer),
    Column("close", Float),                            # price when the call was made
    Column("regime", String(16)),
    Column("top", Text),                               # JSON: strongest detectors
    Column("ts", DateTime),
)

# Backtest / event-study / track-record results (JSON), newest per kind wins
backtests = Table(
    "backtests", metadata,
    Column("id", String(48), primary_key=True),        # kind|YYYY-MM-DD
    Column("kind", String(24), index=True),
    Column("ts", DateTime, index=True),
    Column("params", Text),
    Column("results", Text),
)


# ================================================================== session 10
# Platform: versioned migrations + encrypted secrets
schema_migrations = Table(
    "schema_migrations", metadata,
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("name", String(120)),
    Column("applied_at", DateTime),
)

app_secrets = Table(
    "app_secrets", metadata,
    Column("name", String(64), primary_key=True),
    Column("ciphertext", Text),
    Column("hint", String(24)),            # masked tail shown in the UI ("…a1B2")
    Column("updated_at", DateTime),
)

# Real-time layer
halts = Table(
    "halts", metadata,
    Column("id", String(64), primary_key=True),       # symbol|MM/DD/YYYY|HH:MM:SS
    Column("symbol", String(16), index=True),
    Column("ticker", String(16), index=True),         # universe match, if any
    Column("issue_name", String(200)),
    Column("market", String(24)),
    Column("reason", String(12)),                     # Nasdaq reason code (T1, LUDP, H10 ...)
    Column("halt_at", DateTime, index=True),          # UTC
    Column("resumption_date", String(16)),
    Column("resumption_trade_time", String(32)),
    Column("fetched_at", DateTime),
)

# Catalyst intelligence
trial_changes = Table(
    "trial_changes", metadata,
    Column("id", String(48), primary_key=True),
    Column("nct_id", String(24), index=True),
    Column("ticker", String(16), index=True),
    Column("field", String(32)),
    Column("old", Text),
    Column("new", Text),
    Column("kind", String(24)),            # date_slip / date_pull_in / enrollment_complete / halted / ...
    Column("days", Float),                 # size of a date move
    Column("detected_at", DateTime, index=True),
)

catalyst_events = Table(
    "catalyst_events", metadata,
    Column("id", String(64), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("event_date", Date, index=True),
    Column("kind", String(24)),            # approval / crl / topline / pdufa / adcom / readout
    Column("direction", String(8)),        # pos / neg / unknown
    Column("title", Text),
    Column("source", String(24)),
    Column("url", String(512)),
    Column("mcap_bucket", String(8)),
    Column("ret_pre60", Float),
    Column("ret_1d", Float),
    Column("ret_5d", Float),
    Column("ret_21d", Float),
    Column("xret_1d", Float),
    Column("xret_5d", Float),
    Column("computed_at", DateTime),
)

landscape_trials = Table(
    "landscape_trials", metadata,
    Column("id", String(96), primary_key=True),       # condition key|nct
    Column("condition", String(160), index=True),
    Column("nct_id", String(24), index=True),
    Column("sponsor", String(256)),
    Column("sponsor_class", String(24)),
    Column("sponsor_ticker", String(16), index=True),
    Column("phase", String(32)),
    Column("status", String(48)),
    Column("primary_completion_date", Date),
    Column("title", Text),
    Column("interventions", Text),
    Column("fetched_at", DateTime),
)

# Point-in-time snapshots (honest backtests of non-price signals)
fundamental_snapshots = Table(
    "fundamental_snapshots", metadata,
    Column("asof", Date, primary_key=True),
    Column("ticker", String(16), primary_key=True),
    Column("market_cap", Float),
    Column("cash", Float),
    Column("runway_quarters", Float),
    Column("short_percent_float", Float),
    Column("short_ratio", Float),
    Column("held_pct_institutions", Float),
)

catalyst_snapshots = Table(
    "catalyst_snapshots", metadata,
    Column("asof", Date, primary_key=True),
    Column("id", String(48), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("type", String(32)),
    Column("date", Date),
    Column("confidence", String(16)),
    Column("source", String(48)),
)

universe_snapshots = Table(
    "universe_snapshots", metadata,
    Column("asof", Date, primary_key=True),
    Column("ticker", String(16), primary_key=True),
    Column("in_xbi", Integer),
    Column("in_ibb", Integer),
    Column("tier", String(12)),
)

dq_checks = Table(
    "dq_checks", metadata,
    Column("run_at", DateTime, primary_key=True),
    Column("check", String(48), primary_key=True),
    Column("status", String(8)),           # ok / warn / error
    Column("count", Integer),
    Column("detail", Text),                # JSON sample
)

# User workspace state
screens = Table(
    "screens", metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(80)),
    Column("filters", Text),               # JSON list of {field, op, value}
    Column("alert", Integer, default=0),
    Column("members", Text),               # JSON: tickers passing at the last evaluation
    Column("created_at", DateTime),
    Column("updated_at", DateTime),
)

workspaces = Table(
    "workspaces", metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(80)),
    Column("layout", Text),                # JSON
    Column("updated_at", DateTime),
)

molecule_valuations = Table(
    "molecule_valuations", metadata,
    Column("molecule_id", String(48), primary_key=True),
    Column("inputs", Text),                # JSON
    Column("result", Text),                # JSON
    Column("updated_at", DateTime),
)

# Fundamentals & ownership
inst_ownership = Table(
    "inst_ownership", metadata,
    Column("ticker", String(16), primary_key=True),
    Column("period", Date, primary_key=True),
    Column("holders", Integer),
    Column("shares", Float),
    Column("value", Float),
    Column("holders_prev", Integer),
    Column("shares_prev", Float),
    Column("new_holders", Integer),
    Column("exited_holders", Integer),
    Column("top_holders", Text),           # JSON [{name, shares, value, change}]
    Column("computed_at", DateTime),
)

loe_calendar = Table(
    "loe_calendar", metadata,
    Column("id", String(64), primary_key=True),       # appl_type|appl_no
    Column("ticker", String(16), index=True),
    Column("applicant", String(200)),
    Column("trade_name", String(200)),
    Column("ingredient", String(300)),
    Column("appl_no", String(16)),
    Column("approval_date", Date),
    Column("patent_expiry", Date),
    Column("exclusivity_expiry", Date),
    Column("loe_date", Date, index=True),
    Column("fetched_at", DateTime),
)

faers_counts = Table(
    "faers_counts", metadata,
    Column("brand", String(80), primary_key=True),
    Column("quarter", String(8), primary_key=True),   # 2026Q2
    Column("ticker", String(16), index=True),
    Column("reports", Integer),
    Column("serious", Integer),
    Column("fetched_at", DateTime),
)

gov_awards = Table(
    "gov_awards", metadata,
    Column("id", String(80), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("recipient", String(200)),
    Column("agency", String(160)),
    Column("sub_agency", String(160)),
    Column("amount", Float),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("description", Text),
    Column("award_type", String(24)),
    Column("url", String(256)),
    Column("fetched_at", DateTime),
)

etf_flows = Table(
    "etf_flows", metadata,
    Column("etf", String(8), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("nav", Float),
    Column("shares_out", Float),
    Column("aum", Float),
    Column("flow_est", Float),
    Column("fetched_at", DateTime),
)

# AI layer
news_llm = Table(
    "news_llm", metadata,
    Column("id", String(40), primary_key=True),       # news.id or accession
    Column("kind", String(12)),                       # news / filing
    Column("ticker", String(16), index=True),
    Column("event_type", String(32)),
    Column("outcome", String(12)),                    # positive / negative / mixed / neutral
    Column("endpoint_met", Integer),
    Column("drug", String(120)),
    Column("indication", String(200)),
    Column("pdufa_date", Date),
    Column("adcom_date", Date),
    Column("summary", Text),
    Column("confidence", Float),
    Column("model", String(64)),
    Column("scored_at", DateTime),
)

filing_summaries = Table(
    "filing_summaries", metadata,
    Column("accession", String(32), primary_key=True),
    Column("ticker", String(16), index=True),
    Column("form", String(16)),
    Column("filed_date", Date),
    Column("url", String(512)),
    Column("summary", Text),
    Column("model", String(64)),
    Column("created_at", DateTime),
)

briefs = Table(
    "briefs", metadata,
    Column("day", Date, primary_key=True),
    Column("body", Text),                  # markdown
    Column("model", String(64)),
    Column("created_at", DateTime),
)

risk_diffs = Table(
    "risk_diffs", metadata,
    Column("id", String(64), primary_key=True),       # ticker|accession
    Column("ticker", String(16), index=True),
    Column("form", String(16)),
    Column("filed_date", Date),
    Column("prev_accession", String(32)),
    Column("added", Text),                 # JSON list of new risk sentences
    Column("removed", Text),               # JSON list of dropped sentences
    Column("summary", Text),
    Column("url", String(512)),
    Column("created_at", DateTime),
)

llm_usage = Table(
    "llm_usage", metadata,
    Column("day", Date, primary_key=True),
    Column("model", String(64), primary_key=True),
    Column("provider", String(24)),
    Column("calls", Integer),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("cache_read_tokens", Integer),
    Column("cost_usd", Float),
)


_ENGINE: Engine | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        url = load_settings().database_url
        if url.startswith("sqlite"):
            _ENGINE = create_engine(url, future=True,
                                    connect_args={"check_same_thread": False})
        else:
            # Postgres (Neon): pre_ping revives connections dropped by Neon's
            # idle auto-suspend; small pool + recycle keeps it serverless-friendly.
            _ENGINE = create_engine(
                url, future=True, pool_pre_ping=True, pool_size=3, max_overflow=2,
                pool_recycle=300,
                connect_args={"connect_timeout": 15,
                              "keepalives": 1, "keepalives_idle": 30},
            )
    return _ENGINE


def migrate(engine: Engine | None = None) -> list[str]:
    """Bring an existing database up to the current schema, additively.

    ``create_all`` makes missing *tables* but never touches an existing one, so a
    column added to a table here (e.g. fundamentals.short_ratio) would be absent on
    the live Postgres and every write naming it would fail. This adds any missing
    column as nullable - never drops, renames or retypes anything, so it is safe
    to run on every start (the dashboard and each Actions run both call init_db).
    Returns the "table.column" names it added.
    """
    from sqlalchemy import text

    engine = engine or get_engine()
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    added: list[str] = []
    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have or col.primary_key:
                continue
            ddl = col.type.compile(dialect=engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}'))
            added.append(f"{table.name}.{col.name}")
    if added:
        import logging

        logging.getLogger("bioterm.db").info("migrated: added %s", ", ".join(added))
    return added


# ------------------------------------------------------------------ versioned migrations
# ``migrate()`` above only ADDs missing columns. Anything else - backfills, renames,
# type changes, new indexes on old tables - is an ordered, idempotent step here,
# recorded in ``schema_migrations`` so it runs once per database. Steps must be
# safe to re-run (two processes can start at the same moment on a fresh deploy).
MIGRATIONS: list[tuple[int, str, Any]] = []


def migration(version: int, name: str):
    def deco(fn):
        MIGRATIONS.append((version, name, fn))
        return fn
    return deco


def _ensure_index(engine: Engine, table: str, column: str) -> None:
    from sqlalchemy import text

    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    name = f"ix_{table}_{column}"
    if name in {ix["name"] for ix in insp.get_indexes(table)}:
        return
    with engine.begin() as conn:
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ("{column}")'))


@migration(1, "baseline")
def _m001(engine: Engine) -> None:
    pass


@migration(2, "securities.tier = core for existing names")
def _m002(engine: Engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("UPDATE securities SET tier = 'core' WHERE tier IS NULL"))


@migration(3, "indexes for session-10 query paths")
def _m003(engine: Engine) -> None:
    _ensure_index(engine, "filings", "filed_date")
    _ensure_index(engine, "filings", "form")
    _ensure_index(engine, "alerts_fired", "kind")
    _ensure_index(engine, "signals", "asof")
    _ensure_index(engine, "signal_scores", "asof")


def run_migrations(engine: Engine | None = None) -> list[int]:
    from datetime import datetime, timezone

    engine = engine or get_engine()
    done = set(read_sql("SELECT version FROM schema_migrations")["version"].astype(int)) \
        if "schema_migrations" in inspect(engine).get_table_names() else set()
    applied = []
    for version, name, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
        if version in done:
            continue
        fn(engine)
        bulk_upsert(schema_migrations, [{"version": version, "name": name,
                                         "applied_at": datetime.now(timezone.utc)}])
        applied.append(version)
    if applied:
        import logging

        logging.getLogger("bioterm.db").info("migrations applied: %s", applied)
    return applied


def init_db(seed: bool = True) -> list[str]:
    engine = get_engine()
    metadata.create_all(engine)
    migrate(engine)
    run_migrations(engine)
    if seed:
        try:
            from .store import seed_from_yaml

            seed_from_yaml()
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("bioterm.db").warning("yaml seed skipped: %s", exc)
    return sorted(inspect(engine).get_table_names())


def _clean_rows(table: Table, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    cols = set(table.c.keys())
    pk_cols = [c.name for c in table.primary_key.columns]
    cleaned_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for r in rows:
        cleaned = {k: v for k, v in r.items() if k in cols}
        for k, v in list(cleaned.items()):
            if isinstance(v, float) and pd.isna(v):
                cleaned[k] = None
        cleaned_rows.append(cleaned)
        seen_keys.update(cleaned.keys())
    # consistent key set across all rows (multi-VALUES insert needs it)
    normalised = [{k: r.get(k) for k in seen_keys} for r in cleaned_rows]
    # dedup within the batch on the PK (last wins) - ON CONFLICT DO UPDATE cannot
    # touch the same target row twice in one statement
    if all(pk in seen_keys for pk in pk_cols) and pk_cols:
        by_pk = {tuple(r[pk] for pk in pk_cols): r for r in normalised}
        normalised = list(by_pk.values())
    return normalised


def bulk_upsert(
    table: Table,
    rows: Sequence[dict[str, Any]],
    update_only: Sequence[str] | None = None,
) -> int:
    """Insert-or-update ``rows`` keyed on ``table``'s primary key. SQLite + Postgres.

    ``update_only`` restricts which columns are overwritten on conflict - use it
    for partial updates (e.g. backfilling sentiment on existing news rows) so the
    other columns are not clobbered with NULL.
    """
    rows = _clean_rows(table, rows)
    if not rows:
        return 0
    engine = get_engine()
    pk_cols = [c.name for c in table.primary_key.columns]
    dialect = engine.dialect.name

    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as _insert
    elif dialect in ("postgresql", "postgres"):
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:  # pragma: no cover - fallback: naive delete+insert
        return _fallback_upsert(engine, table, rows, pk_cols)

    # both psycopg (Postgres) and sqlite cap bound parameters per statement
    # (65535 / 32766). Chunk so a big batch (news, clinical_trials, filings) fits.
    ncols = max(1, len(rows[0]))
    limit = 60000 if dialect.startswith("postgre") else 30000
    chunk = max(1, min(5000, limit // ncols))

    allowed = set(update_only) if update_only else None
    with engine.begin() as conn:
        for i in range(0, len(rows), chunk):
            batch = rows[i:i + chunk]
            stmt = _insert(table).values(batch)
            # NB: subscript, not getattr - a column named 'items'/'keys'/'values'
            # would otherwise resolve to the collection's method.
            update_cols = {
                c.name: stmt.excluded[c.name]
                for c in table.c
                if c.name not in pk_cols and (allowed is None or c.name in allowed)
            }
            stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)
            conn.execute(stmt)
    return len(rows)


def _fallback_upsert(engine, table, rows, pk_cols) -> int:
    with engine.begin() as conn:
        for r in rows:
            cond = [table.c[k] == r[k] for k in pk_cols]
            conn.execute(table.delete().where(*cond))
        conn.execute(table.insert(), rows)
    return len(rows)


def read_sql(query, params: dict | None = None) -> pd.DataFrame:
    """Run a SQLAlchemy selectable or raw SQL string -> DataFrame.

    Raw strings are wrapped in ``text()`` so ``:name`` params work identically on
    SQLite and Postgres regardless of the pandas version.
    """
    from sqlalchemy import text

    engine = get_engine()
    if isinstance(query, str):
        query = text(query)
    with engine.connect() as conn:
        # Reads run in autocommit: psycopg then sends no BEGIN before the SELECT and
        # no ROLLBACK when the pool takes the connection back - two of the four network
        # round trips a read used to cost (ping, BEGIN, SELECT, ROLLBACK), which from
        # Streamlit Cloud to Neon is most of a cold page load. The pool restores the
        # default isolation on return, so writes (engine.begin()) stay transactional.
        conn.execution_options(isolation_level="AUTOCOMMIT")
        return pd.read_sql(query, conn, params=params)


def table_count(table: Table) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())
