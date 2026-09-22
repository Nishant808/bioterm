"""News - every headline matched to a tracked name, newest first."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from _shared import news_df, scores_df
from _ui import card, empty_state, headline_rows, kpi_row, page_header, tone_of
from bioterm import store
from bioterm.config import load_settings

WINDOWS = {"24h": 24, "48h": 48, "3d": 72, "7d": 168, "14d": 336, "30d": 720}
SIGNALS = ["All", "Positive", "Negative", "Tagged"]

page_header("News", "Every headline matched to a tracked name, newest first")

cfg = load_settings()
rows = int(cfg.get("dashboard", "news_firehose_rows", default=200))

# The whole ingest lookback (~45 days, a few thousand rows): the 30-day window
# needs it - the 3,000 newest headlines only reach back about a week.
news = news_df(8000)
if news.empty:
    empty_state("No news yet", "Headlines appear after the first ingestion run.", "newspaper")
    st.stop()

scores = scores_df()[["ticker", "rank"]].set_index("ticker")
wl_tickers = {w["ticker"].upper() for w in store.get_watchlist()}

# ------------------------------------------------------------------ filters
with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    window = st.segmented_control("Window", list(WINDOWS), default="7d", required=True)
    signal = st.segmented_control("Event signal", SIGNALS, default="All", required=True,
                                  help="Positive / negative = strong event tags such as "
                                       "topline, approval, CRL, clinical hold")
    wl_only = st.toggle("Watchlist only")
    st.space("stretch")
    if st.button("Refresh", icon=":material/refresh:", type="tertiary",
                 help="Re-read the feed now (it refreshes automatically every 2 minutes)"):
        st.cache_data.clear()
        st.rerun()

with st.container(horizontal=True, gap="small"):
    tickers = st.multiselect("Tickers", sorted(news["ticker"].dropna().unique()),
                             placeholder="All tickers", width=420)
    sources = st.multiselect("Sources", sorted(news["source"].dropna().unique()),
                             placeholder="All sources", width=420)

view = news[news["published"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=WINDOWS[window])]
if wl_only:
    view = view[view["tickers_csv"].fillna("").apply(
        lambda s: any(t in wl_tickers for t in s.split(",")))]
if tickers:
    view = view[view["tickers_csv"].fillna("").apply(
        lambda s: any(t in s.split(",") for t in tickers))]
if sources:
    view = view[view["source"].isin(sources)]
es = pd.to_numeric(view["event_score"], errors="coerce").fillna(0)
if signal == "Positive":
    view = view[es > 0.3]
elif signal == "Negative":
    view = view[es < -0.3]
elif signal == "Tagged":
    view = view[view["event_tags"].fillna("") != ""]
total = len(view)
view = view.sort_values("published", ascending=False).head(rows)

if view.empty:
    empty_state("No headlines match these filters",
                "Widen the window or clear a filter.", "filter_alt_off")
    st.stop()

# ------------------------------------------------------------------ summary
_s = pd.to_numeric(view["sentiment"], errors="coerce").mean()
_t = pd.to_numeric(view["event_score"], errors="coerce").sum()
net = float(np.clip(0.45 * (_s or 0) + 0.55 * np.tanh((_t or 0) / 4), -1, 1))
word, _ = tone_of(net)
with kpi_row(4, "news"):
    st.metric("Headlines", total,
              delta=f"showing newest {len(view)}" if total > len(view) else None,
              delta_color="off", delta_arrow="off", border=True)
    st.metric("Mean tone", f"{(_s or 0):+.2f}", border=True,
              help="Average headline tone (VADER), −1 to +1")
    st.metric("Event tilt", f"{(_t or 0):+.1f}", border=True,
              help="Sum of event-tag weights: positive events add, negative subtract")
    st.metric("Net sentiment", word, delta=f"{net:+.2f}", delta_color="off",
              delta_arrow="off", border=True)

with card("Headlines", icon_name="newspaper", meta=f"Last {window} · newest first"):
    headline_rows(view, show_rank=scores["rank"].to_dict())
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("“+1” means the article also mentions another tracked name — hover the "
                   "ticker to see which.")
        st.space("stretch")
        st.download_button(
            "Export CSV",
            view[["published", "tickers_csv", "title", "source", "sentiment", "event_tags",
                  "event_score", "url"]].to_csv(index=False),
            "bioterm_news.csv", "text/csv", icon=":material/download:", type="tertiary")
