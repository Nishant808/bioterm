"""Shared helpers for the Streamlit dashboard: cached DB reads + formatting."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# make `bioterm` importable when Streamlit runs this file directly
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# On Streamlit Community Cloud the DB URL comes in via st.secrets, not the env.
# Bridge it into the environment *before* bioterm.config reads it. API keys and
# webhooks are normally stored from the Settings page (encrypted in the DB); a
# value in secrets takes precedence over the stored one.
_BRIDGE = ("DATABASE_URL", "BIOTERM_SEC_USER_AGENT", "GH_DISPATCH_TOKEN", "GH_REPO",
           "BIOTERM_ADMIN_PASSWORD", "BIOTERM_SECRET_KEY", "BIOTERM_OWNER_EMAILS",
           "BIOTERM_LIVE_PRICES", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
           "FINNHUB_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SLACK_WEBHOOK_URL",
           "DISCORD_WEBHOOK_URL", "NTFY_TOPIC", "NTFY_SERVER", "NTFY_TOKEN", "SMTP_HOST",
           "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TO")
try:
    for _k in _BRIDGE:
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # noqa: BLE001 - no secrets file locally is fine
    pass

from bioterm.db import init_db, read_sql  # noqa: E402

# Make sure tables exist (harmless if they already do) - covers a fresh cloud DB
# before the first Actions run has landed.
try:
    init_db()
except Exception:  # noqa: BLE001
    pass

# Page config (title, icon, layout) is set by the router in Home.py on every
# run - a call here would only ever run once per process, since this module is
# cached in sys.modules after the first import.


# --------------------------------------------------------------------- caching
@st.cache_data(ttl=120)
def q(sql: str, params: dict | None = None) -> pd.DataFrame:
    return read_sql(sql, params)


@st.cache_data(ttl=120)
def scores_df() -> pd.DataFrame:
    df = q(
        "SELECT s.*, u.name, u.is_watchlist, u.in_xbi FROM scores s "
        "JOIN securities u ON u.ticker = s.ticker "
        "WHERE s.asof = (SELECT MAX(asof) FROM scores) ORDER BY s.rank"
    )
    if not df.empty:
        df["rationale_obj"] = df["rationale"].map(_loads)
    return df


@st.cache_data(ttl=120)
def prev_scores_df(min_age_hours: int = 6) -> pd.DataFrame:
    """The score snapshot to diff 'movers' against: the most recent run at least
    `min_age_hours` old, else the second-most-recent run. All ts comparison stays
    in the DB (avoids naive/aware timestamp mismatches)."""
    cutoff = (pd.Timestamp.now("UTC") - pd.Timedelta(hours=min_age_hours)).strftime(
        "%Y-%m-%d %H:%M:%S")
    df = q(
        "SELECT ticker, focus_score, rank FROM score_snapshots WHERE ts = "
        "(SELECT ts FROM score_snapshots WHERE ts <= :c GROUP BY ts "
        " ORDER BY ts DESC LIMIT 1)", {"c": cutoff})
    if df.empty:
        df = q("SELECT ticker, focus_score, rank FROM score_snapshots WHERE ts = "
               "(SELECT DISTINCT ts FROM score_snapshots ORDER BY ts DESC "
               " LIMIT 1 OFFSET 1)")
    if not df.empty:
        return df
    asofs = q("SELECT DISTINCT asof FROM scores ORDER BY asof DESC LIMIT 2")
    if len(asofs) < 2:
        return pd.DataFrame(columns=["ticker", "focus_score", "rank"])
    return q("SELECT ticker, focus_score, rank FROM scores WHERE asof = :a",
             {"a": asofs.iloc[1]["asof"]})


@st.cache_data(ttl=120)
def score_history(ticker: str) -> pd.DataFrame:
    df = q("SELECT ts, focus_score, rank FROM score_snapshots WHERE ticker = :t "
           "ORDER BY ts", {"t": ticker})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=120)
def catalysts_df() -> pd.DataFrame:
    df = q("SELECT * FROM catalysts ORDER BY date")
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=120)
def news_df(limit: int = 1000) -> pd.DataFrame:
    df = q("SELECT * FROM news ORDER BY published DESC LIMIT :n", {"n": limit})
    if not df.empty:
        df["published"] = pd.to_datetime(df["published"], utc=True, errors="coerce")
    return df




@st.cache_data(ttl=120)
def trials_df(ticker: str) -> pd.DataFrame:
    df = q("SELECT * FROM clinical_trials WHERE ticker = :t", {"t": ticker})
    for c in ("primary_completion_date", "completion_date", "start_date"):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


@st.cache_data(ttl=120)
def fundamentals_row(ticker: str) -> dict:
    df = q("SELECT * FROM fundamentals WHERE ticker = :t", {"t": ticker})
    return {} if df.empty else df.iloc[0].to_dict()


@st.cache_data(ttl=120)
def insider_txns_df(ticker: str) -> pd.DataFrame:
    df = q("SELECT * FROM insider_txns WHERE ticker = :t ORDER BY txn_date DESC",
           {"t": ticker})
    if not df.empty:
        for c in ("txn_date", "filed_date"):
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


@st.cache_data(ttl=120)
def filings_df(ticker: str) -> pd.DataFrame:
    df = q("SELECT * FROM filings WHERE ticker = :t ORDER BY filed_date DESC LIMIT 40",
           {"t": ticker})
    if not df.empty:
        df["filed_date"] = pd.to_datetime(df["filed_date"], errors="coerce")
    return df


@st.cache_data(ttl=120)
def ingest_status() -> pd.DataFrame:
    return q("SELECT job, started_at, finished_at, status, rows FROM ingest_runs "
             "ORDER BY id DESC LIMIT 40")


@st.cache_data(ttl=60)
def alerts_fired_df(limit: int = 300) -> pd.DataFrame:
    return q("SELECT * FROM alerts_fired ORDER BY ts DESC LIMIT :n", {"n": limit})


@st.cache_data(ttl=300)
def universe_df() -> pd.DataFrame:
    return q("SELECT * FROM securities ORDER BY ticker")




# --------------------------------------------------------------- news sentiment
@st.cache_data(ttl=120)
def sentiment_df(days: int = 14) -> pd.DataFrame:
    """Per-ticker news-sentiment factor over the last `days`.

    ``signal`` ∈ [-1, 1] blends VADER tone with the biotech event-tag tilt
    (topline / approval / CRL / clinical hold …). It is the raw driver behind the
    Focus Score's *newsflow* component, surfaced here on its own.
    """
    import numpy as np

    raw = q(
        "SELECT ticker, tickers_csv, published, sentiment, event_score, event_tags "
        "FROM news WHERE published >= :cut",
        {"cut": (pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S")},
    )
    if raw.empty:
        return pd.DataFrame(columns=["ticker", "n", "sent", "tilt", "signal",
                                     "pos", "neg", "last"])
    raw["published"] = pd.to_datetime(raw["published"], utc=True, errors="coerce")
    # explode multi-ticker headlines so each name gets credit
    raw["tk"] = raw["tickers_csv"].fillna(raw["ticker"]).fillna("").str.split(",")
    ex = raw.explode("tk")
    ex["tk"] = ex["tk"].str.strip()
    ex = ex[ex["tk"] != ""]
    ex["sentiment"] = pd.to_numeric(ex["sentiment"], errors="coerce").fillna(0.0)
    ex["event_score"] = pd.to_numeric(ex["event_score"], errors="coerce").fillna(0.0)

    rows = []
    for tk, g in ex.groupby("tk"):
        tilt = float(g["event_score"].sum())
        sent = float(g["sentiment"].mean())
        signal = max(-1.0, min(1.0, 0.45 * sent + 0.55 * np.tanh(tilt / 2.0)))
        rows.append({
            "ticker": tk, "n": int(len(g)),
            "sent": round(sent, 3), "tilt": round(tilt, 2),
            "signal": round(signal, 3),
            "pos": int((g["event_score"] > 0).sum()),
            "neg": int((g["event_score"] < 0).sum()),
            "last": g["published"].max(),
        })
    return pd.DataFrame(rows).sort_values("signal", ascending=False)


@st.cache_data(ttl=120)
def sentiment_series(ticker: str, days: int = 60) -> pd.DataFrame:
    """Daily headline count + 7-day rolling mean sentiment for one ticker."""
    df = q(
        "SELECT published, sentiment, event_score FROM news "
        "WHERE (tickers_csv LIKE :like OR ticker = :t) AND published >= :cut",
        {"like": f"%{ticker}%", "t": ticker,
         "cut": (pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=days)).strftime(
             "%Y-%m-%d %H:%M:%S")},
    )
    if df.empty:
        return df
    df["published"] = pd.to_datetime(df["published"], utc=True, errors="coerce")
    df["day"] = df["published"].dt.floor("D")
    df["sentiment"] = pd.to_numeric(df["sentiment"], errors="coerce")
    daily = df.groupby("day").agg(n=("sentiment", "size"),
                                  sent=("sentiment", "mean"),
                                  tilt=("event_score", "sum")).reset_index()
    daily["sent_7d"] = daily["sent"].rolling(7, min_periods=1).mean()
    return daily


# --------------------------------------------------------------- intelligence
_BOARD_COLS = ["ticker", "asof", "bull", "bear", "net", "label", "n_buy", "n_sell", "close",
               "regime", "top", "name", "is_watchlist", "prev_label", "top_obj"]


@st.cache_data(ttl=120)
def signal_board() -> pd.DataFrame:
    """The latest BUY/SELL call per name, with the previous session's label (so a
    change of call is visible) and the parsed top reasons."""
    df = q(
        "SELECT s.ticker, s.asof, s.bull, s.bear, s.net, s.label, s.n_buy, s.n_sell, "
        "s.close, s.regime, s.top, u.name, u.is_watchlist, p.label AS prev_label "
        "FROM signal_scores s JOIN securities u ON u.ticker = s.ticker "
        "LEFT JOIN signal_scores p ON p.ticker = s.ticker AND p.asof = ("
        "  SELECT MAX(asof) FROM signal_scores WHERE asof < "
        "  (SELECT MAX(asof) FROM signal_scores)) "
        "WHERE s.asof = (SELECT MAX(asof) FROM signal_scores) ORDER BY s.net DESC")
    if df.empty:
        return pd.DataFrame(columns=_BOARD_COLS)
    df["top_obj"] = df["top"].map(lambda s: _loads(s) or [])
    for c in ("bull", "bear", "net", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@st.cache_data(ttl=120)
def signals_today() -> pd.DataFrame:
    """Every detector that fired on the latest signal run (one row per name x code)."""
    df = q("SELECT ticker, side, code, strength, title, detail FROM signals "
           "WHERE asof = (SELECT MAX(asof) FROM signals)")
    if df.empty:
        return pd.DataFrame(columns=["ticker", "side", "code", "strength", "title", "detail",
                                     "family", "detail_obj"])
    df["detail_obj"] = df["detail"].map(lambda s: _loads(s) or {})
    df["family"] = df["detail_obj"].map(lambda d: d.get("family", "event"))
    df["strength"] = pd.to_numeric(df["strength"], errors="coerce")
    return df


@st.cache_data(ttl=120)
def signal_history(ticker: str) -> pd.DataFrame:
    df = q("SELECT asof, bull, bear, net, label, close FROM signal_scores "
           "WHERE ticker = :t ORDER BY asof", {"t": ticker})
    if not df.empty:
        df["asof"] = pd.to_datetime(df["asof"])
    return df


@st.cache_data(ttl=300)
def signal_label_history(days: int = 120) -> pd.DataFrame:
    cut = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    df = q("SELECT asof, label, COUNT(*) AS n FROM signal_scores WHERE asof >= :c "
           "GROUP BY asof, label ORDER BY asof", {"c": cut})
    if not df.empty:
        df["asof"] = pd.to_datetime(df["asof"])
    return df


@st.cache_data(ttl=600)
def backtest_result(kind: str) -> dict:
    """Latest stored backtest of one kind (events / factor / track) + its run time."""
    df = q("SELECT ts, params, results FROM backtests WHERE kind = :k "
           "ORDER BY ts DESC LIMIT 1", {"k": kind})
    if df.empty:
        return {}
    out = _loads(df.iloc[0]["results"]) or {}
    out["_ts"] = str(df.iloc[0]["ts"])
    out["_params"] = _loads(df.iloc[0]["params"]) or {}
    return out


@st.cache_data(ttl=600)
def smart_money() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-fund position changes, per-security summary) from the specialist
    13F filings - latest quarter vs each fund's own previous quarter."""
    from bioterm.process import smart_money as sm

    ch = sm.fund_changes()
    return ch, sm.ticker_summary(ch)


@st.cache_data(ttl=600)
def inst_filers_df() -> pd.DataFrame:
    return q("SELECT cik, name, short_name, last_period, last_filed FROM inst_filers "
             "ORDER BY name")


@st.cache_data(ttl=600)
def short_flow() -> pd.DataFrame:
    """Per ticker: FINRA short share of volume, 5-day vs 20-day."""
    from bioterm.ingest.short_volume import short_ratio_trend

    cut = (pd.Timestamp.today() - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    return short_ratio_trend(q("SELECT ticker, date, short_volume, total_volume "
                               "FROM short_volume WHERE date >= :c", {"c": cut}))


@st.cache_data(ttl=600)
def short_series(ticker: str) -> pd.DataFrame:
    df = q("SELECT date, short_volume, short_exempt, total_volume FROM short_volume "
           "WHERE ticker = :t ORDER BY date", {"t": ticker})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["ratio"] = df["short_volume"] / df["total_volume"].where(df["total_volume"] > 0)
    return df


@st.cache_data(ttl=600)
def options_latest() -> pd.DataFrame:
    """The most recent options snapshot per ticker."""
    return q("SELECT o.* FROM options_snapshots o JOIN ("
             "  SELECT ticker, MAX(date) d FROM options_snapshots GROUP BY ticker) m "
             "ON o.ticker = m.ticker AND o.date = m.d")


@st.cache_data(ttl=600)
def options_history(ticker: str) -> pd.DataFrame:
    df = q("SELECT * FROM options_snapshots WHERE ticker = :t ORDER BY date", {"t": ticker})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=120)
def molecules_df() -> pd.DataFrame:
    """Tracked molecules joined to their derived status row."""
    df = q("SELECT m.id, m.ticker, m.name, m.aliases, m.indication, m.nct_ids, m.notes, "
           "s.n_trials, s.n_active, s.top_phase, s.next_readout, s.n_news_30d, "
           "s.news_tone_30d, s.papers_total, s.last_paper_date, s.discovered_aliases, "
           "s.updated_at FROM molecules m LEFT JOIN molecule_status s ON s.molecule_id = m.id "
           "ORDER BY m.ticker, m.name")
    if df.empty:
        return df
    for c in ("aliases", "nct_ids", "discovered_aliases"):
        df[c] = df[c].map(lambda s: _loads(s) if isinstance(s, str) else [])
        df[c] = df[c].map(lambda v: v if isinstance(v, list) else [])
    for c in ("next_readout", "last_paper_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


@st.cache_data(ttl=120)
def molecule_trials_df(molecule_id: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM molecule_trials"
    df = q(sql + " WHERE molecule_id = :m", {"m": molecule_id}) if molecule_id else q(sql)
    for c in ("start_date", "primary_completion_date", "completion_date",
              "last_update_post_date"):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


@st.cache_data(ttl=120)
def molecule_links_df(molecule_id: str) -> pd.DataFrame:
    df = q("SELECT kind, ref_id, title, date, url, detail FROM molecule_links "
           "WHERE molecule_id = :m ORDER BY date DESC", {"m": molecule_id})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["detail_obj"] = df["detail"].map(lambda s: _loads(s) or {})
    return df


def _loads(s):
    try:
        return json.loads(s) if s else {}
    except (TypeError, ValueError):
        return {}


# --------------------------------------------------------------------- format
def pct(x, digits: int = 1) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x * 100:+.{digits}f}%"


def money(x) -> str:
    if x is None or pd.isna(x):
        return "–"
    x = float(x)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.2f}{unit}"
    return f"${x:.0f}"


def trigger_workflow(which: str = "ingest-fast.yml") -> tuple[bool, str]:
    """Fire a GitHub Actions workflow_dispatch. Needs GH_DISPATCH_TOKEN + GH_REPO
    ('owner/repo') in secrets/env; returns (ok, message)."""
    import os

    import requests

    token = os.environ.get("GH_DISPATCH_TOKEN")
    repo = os.environ.get("GH_REPO")
    if not token or not repo:
        return False, "set GH_DISPATCH_TOKEN + GH_REPO secrets to enable this"
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/{which}/dispatches",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"ref": "main"}, timeout=15)
        if r.status_code == 204:
            return True, f"{which} dispatched — data updates in a few minutes"
        return False, f"GitHub returned {r.status_code}: {r.text[:200]}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
