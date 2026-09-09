"""Shared helpers for the Streamlit dashboard: cached DB reads + formatting."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# make `bioterm` importable when Streamlit runs this file directly
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bioterm.config import load_settings  # noqa: E402
from bioterm.db import read_sql  # noqa: E402

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
def prev_scores_df() -> pd.DataFrame:
    asofs = q("SELECT DISTINCT asof FROM scores ORDER BY asof DESC LIMIT 2")
    if len(asofs) < 2:
        return pd.DataFrame(columns=["ticker", "focus_score", "rank"])
    prev = asofs.iloc[1]["asof"]
    return q("SELECT ticker, focus_score, rank FROM scores WHERE asof = :a", {"a": prev})


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


@st.cache_data(ttl=300)
def universe_df() -> pd.DataFrame:
    return q("SELECT * FROM securities ORDER BY ticker")


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


def runway_badge(q_left) -> str:
    if q_left is None or pd.isna(q_left):
        return "runway: unknown"
    q_left = float(q_left)
    tag = "🟢" if q_left >= 8 else "🟡" if q_left >= 4 else "🔴"
    return f"{tag} runway ≈ {q_left:.1f} quarters"


def disclaimer() -> None:
    st.caption(
        "⚠️ BioTerm is a **monitoring & screening** tool, not investment advice. "
        "The Focus Score ranks *attention*, not conviction — you supply the judgement "
        "on the science. Data: yfinance · SEC EDGAR · ClinicalTrials.gov · openFDA · RSS."
    )


def sidebar_freshness() -> None:
    stt = ingest_status()
    if stt.empty:
        st.sidebar.info("No ingest runs yet. Run `bioterm ingest`.")
        return
    last = pd.to_datetime(stt["finished_at"]).max()
    st.sidebar.caption(f"data as of **{last:%Y-%m-%d %H:%M} UTC**")
    # flag only jobs whose *most recent* run errored
    latest = stt.sort_values("started_at").groupby("job").last()
    errs = latest[latest["status"] == "error"].index.tolist()
    if errs:
        st.sidebar.warning("latest run failed for: " + ", ".join(errs))
