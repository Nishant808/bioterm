"""Merged, filterable news feed across the universe."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import disclaimer, news_df, scores_df, sidebar_freshness
from bioterm import store
from bioterm.config import load_settings

st.title("News Firehose")
disclaimer()
sidebar_freshness()

cfg = load_settings()
rows = int(cfg.get("dashboard", "news_firehose_rows", default=200))
if st.button("↻ refresh feed"):
    st.cache_data.clear()
    st.rerun()

news = news_df(3000)
if news.empty:
    st.warning("No news yet — run `bioterm ingest --only news,sentiment`.")
    st.stop()

scores = scores_df()[["ticker", "rank"]].set_index("ticker")
wl_tickers = {w["ticker"].upper() for w in store.get_watchlist()}

f1, f2, f3, f4, f5 = st.columns([1.4, 1, 1, 1, 0.8])
tickers = f1.multiselect("tickers", sorted(news["ticker"].dropna().unique()))
sources = f2.multiselect("sources", sorted(news["source"].dropna().unique()))
sentiment = f3.selectbox("event signal", ["all", "positive only", "negative only",
                                          "tagged only"])
hours = f4.selectbox("window", [24, 48, 72, 168, 336, 720], index=3,
                     format_func=lambda h: f"{h}h" if h < 168 else f"{h // 24}d")
f5.write("")
f5.write("")
wl_only = f5.toggle("watchlist")

view = news.copy()
cut = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
view = view[view["published"] >= cut]
if wl_only:
    view = view[view["tickers_csv"].fillna("").apply(
        lambda s: any(t in wl_tickers for t in s.split(",")))]
if tickers:
    view = view[view["tickers_csv"].fillna("").apply(
        lambda s: any(f"{t}" in s.split(",") for t in tickers))]
if sources:
    view = view[view["source"].isin(sources)]
es = pd.to_numeric(view["event_score"], errors="coerce").fillna(0)
if sentiment == "positive only":
    view = view[es > 0.3]
elif sentiment == "negative only":
    view = view[es < -0.3]
elif sentiment == "tagged only":
    view = view[view["event_tags"].fillna("") != ""]

view = view.sort_values("published", ascending=False).head(rows)
h1, h2 = st.columns([4, 1])
h1.caption(f"{len(view)} headlines (cache refreshes every 2 min; ↻ forces it)")
h2.download_button(
    "⬇ CSV",
    view[["published", "tickers_csv", "title", "source", "sentiment", "event_tags",
          "event_score", "url"]].to_csv(index=False),
    "bioterm_news.csv", "text/csv", use_container_width=True)

for _, r in view.iterrows():
    score_val = r["event_score"] or 0
    icon = "🟢" if score_val > 0.3 else "🔴" if score_val < -0.3 else "⚪"
    when = r["published"].strftime("%b %d %H:%M") if pd.notna(r["published"]) else "?"
    rk = scores.loc[r["ticker"], "rank"] if r["ticker"] in scores.index else None
    rank_txt = f" · focus #{int(rk)}" if rk is not None else ""
    tags = f" · `{r['event_tags']}`" if r["event_tags"] else ""
    st.markdown(
        f"{icon} **[{r['tickers_csv'] or r['ticker']}]** [{r['title']}]({r['url']})  \n"
        f"<span style='color:#888'>{when} UTC · {r['source']} · "
        f"sentiment {r['sentiment']:+.2f}{tags}{rank_txt}</span>",
        unsafe_allow_html=True,
    )
