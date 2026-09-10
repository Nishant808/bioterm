"""Merged, filterable news feed across the universe."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from _shared import news_df, scores_df
from _ui import MUTED, NEG, POS, page_setup, sentiment_word
from bioterm import store
from bioterm.config import load_settings

page_setup("News Firehose", "every headline matched to a universe name, newest first")

cfg = load_settings()
rows = int(cfg.get("dashboard", "news_firehose_rows", default=200))
if st.button("↻ refresh feed"):
    st.cache_data.clear()
    st.rerun()

news = news_df(3000)
if news.empty:
    st.warning("No news yet.")
    st.stop()

scores = scores_df()[["ticker", "rank"]].set_index("ticker")
wl_tickers = {w["ticker"].upper() for w in store.get_watchlist()}

f = st.columns([1.4, 1, 1, 1, 0.8])
tickers = f[0].multiselect("tickers", sorted(news["ticker"].dropna().unique()))
sources = f[1].multiselect("sources", sorted(news["source"].dropna().unique()))
signal = f[2].selectbox("event signal", ["all", "positive only", "negative only",
                                         "tagged only"])
hours = f[3].selectbox("window", [24, 48, 72, 168, 336, 720], index=3,
                       format_func=lambda h: f"{h}h" if h < 168 else f"{h // 24}d")
f[4].write("")
f[4].write("")
wl_only = f[4].toggle("watchlist")

view = news.copy()
view = view[view["published"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)]
if wl_only:
    view = view[view["tickers_csv"].fillna("").apply(
        lambda s: any(t in wl_tickers for t in s.split(",")))]
if tickers:
    view = view[view["tickers_csv"].fillna("").apply(
        lambda s: any(t in s.split(",") for t in tickers))]
if sources:
    view = view[view["source"].isin(sources)]
es = pd.to_numeric(view["event_score"], errors="coerce").fillna(0)
if signal == "positive only":
    view = view[es > 0.3]
elif signal == "negative only":
    view = view[es < -0.3]
elif signal == "tagged only":
    view = view[view["event_tags"].fillna("") != ""]
view = view.sort_values("published", ascending=False).head(rows)

# ---- summary bar ----------------------------------------------------------
if not view.empty:
    _s = pd.to_numeric(view["sentiment"], errors="coerce").mean()
    _t = pd.to_numeric(view["event_score"], errors="coerce").sum()
    net = float(np.clip(0.45 * (_s or 0) + 0.55 * np.tanh((_t or 0) / 4), -1, 1))
    word, _ = sentiment_word(net)
    b = st.columns(4)
    b[0].metric("headlines", len(view))
    b[1].metric("mean tone", f"{(_s or 0):+.2f}")
    b[2].metric("event tilt", f"{(_t or 0):+.1f}")
    b[3].metric("net sentiment", word, f"{net:+.2f}")

h1, h2 = st.columns([5, 1])
h1.caption("cache refreshes every 2 min; ↻ forces it")
h2.download_button("⬇ CSV",
                   view[["published", "tickers_csv", "title", "source", "sentiment",
                         "event_tags", "event_score", "url"]].to_csv(index=False),
                   "bioterm_news.csv", "text/csv", use_container_width=True)

for _, r in view.iterrows():
    sv = r["event_score"] or 0
    col = POS if sv > 0.3 else NEG if sv < -0.3 else MUTED
    when = r["published"].strftime("%b %d %H:%M") if pd.notna(r["published"]) else "?"
    rk = scores.loc[r["ticker"], "rank"] if r["ticker"] in scores.index else None
    rank_txt = f" · focus #{int(rk)}" if rk is not None else ""
    tags = f" · {r['event_tags']}" if r["event_tags"] else ""
    st.markdown(
        f"<div class='bt-card'><div class='bt-row'>"
        f"<span class='bt-tk'>{r['tickers_csv'] or r['ticker']}</span>"
        f"<span class='bt-meta'>{when} UTC · {r['source']}</span></div>"
        f"<a href='{r['url']}' target='_blank'>{r['title']}</a>"
        f"<div class='bt-meta'>tone {r['sentiment']:+.2f}"
        f"<span style='color:{col}'>{tags}</span>{rank_txt}</div></div>",
        unsafe_allow_html=True)
