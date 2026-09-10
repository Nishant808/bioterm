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
# Bridge it into the environment *before* bioterm.config reads it.
try:
    for _k in ("DATABASE_URL", "BIOTERM_SEC_USER_AGENT", "GH_DISPATCH_TOKEN",
               "GH_REPO", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # noqa: BLE001 - no secrets file locally is fine
    pass

from bioterm.config import load_settings  # noqa: E402
from bioterm.db import init_db, read_sql  # noqa: E402

# Make sure tables exist (harmless if they already do) - covers a fresh cloud DB
# before the first Actions run has landed.
try:
    init_db()
except Exception:  # noqa: BLE001
    pass

PLOTLY_TEMPLATE = "plotly_dark"
ACCENT = "#00b8d4"
POS = "#26a69a"
NEG = "#ef5350"

st.set_page_config(page_title="BioTerm", page_icon="🧬", layout="wide")


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
def prices_df(ticker: str) -> pd.DataFrame:
    df = q("SELECT * FROM prices WHERE ticker = :t ORDER BY date", {"t": ticker})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=120)
def technicals_df(ticker: str) -> pd.DataFrame:
    df = q("SELECT * FROM technicals WHERE ticker = :t ORDER BY date", {"t": ticker})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
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
