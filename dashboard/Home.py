"""BioTerm — overview."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import (catalysts_df, news_df, prev_scores_df, scores_df,
                     sentiment_df)
from _ui import NEG, POS, eyebrow, page_setup, sentiment_word


def _reasons(o: dict) -> str:
    if not o:
        return ""
    c = o.get("components", {})
    b = []
    if c.get("catalyst", 0) >= 0.45:
        b.append("catalyst")
    if c.get("momentum", 0) >= 0.6:
        b.append("momentum")
    if c.get("newsflow", 0) >= 0.6:
        b.append("news flow")
    if c.get("risk", 0) >= 0.4:
        b.append("⚠ funding risk")
    if o.get("insider_mult", 1) > 1.02:
        b.append("insider buying")
    if o.get("conviction_mult", 1) > 1:
        b.append("your conviction")
    return " · ".join(b)


page_setup("BioTerm",
           "Biotech & pharma catalyst monitor · 6-month swing horizon", "🧬")

scores = scores_df()
if scores.empty:
    st.warning("No scores yet — the first ingest run hasn't landed. Check back shortly.")
    st.stop()

prev = prev_scores_df().set_index("ticker")
cats = catalysts_df()
news = news_df(600)
sent = sentiment_df(14).set_index("ticker")

# ------------------------------------------------------------------ KPI strip
horizon_cats = cats[(cats["months_away"] >= -0.5) & (cats["months_away"] <= 6)]
near_cats = cats[(cats["months_away"] >= -0.2) & (cats["months_away"] <= 1.0)]
recent = news[news["published"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)]
hi_signal = recent[pd.to_numeric(recent["event_score"], errors="coerce").abs() >= 0.8]
net_sent = float(sent["signal"].mean()) if not sent.empty else 0.0
sw, sc = sentiment_word(net_sent)
wl_top = int((scores[scores["is_watchlist"] == 1]["rank"] <= 20).sum())

k = st.columns(4)
k[0].metric("names tracked", len(scores), f"{wl_top} watchlist in top 20")
k[1].metric("catalysts ≤ 6mo", len(horizon_cats), f"{len(near_cats)} within 30d")
k[2].metric("hot news · 7d", len(hi_signal), "strong event tags")
k[3].metric("sector sentiment", sw, f"{net_sent:+.2f}")

st.divider()

# ------------------------------------------------------------------ focus table
eyebrow("Stocks in focus")
top = scores.head(14).copy()
if not prev.empty:
    top["Δ"] = top["ticker"].map(
        lambda t: int(prev.loc[t, "rank"]) - int(top.loc[top["ticker"] == t, "rank"].iloc[0])
        if t in prev.index else 0)
else:
    top["Δ"] = 0
top["sent"] = top["ticker"].map(lambda t: sent.loc[t, "signal"] if t in sent.index else None)
top["why"] = top["rationale_obj"].map(_reasons)
show = top[["rank", "ticker", "name", "focus_score", "Δ", "sent", "catalyst",
            "momentum", "newsflow", "why"]].rename(columns={"focus_score": "focus"})
st.dataframe(
    show, hide_index=True, use_container_width=True,
    column_config={
        "name": st.column_config.TextColumn(width="medium"),
        "focus": st.column_config.ProgressColumn(
            "focus", format="%.3f",
            min_value=float(scores["focus_score"].min()),
            max_value=float(scores["focus_score"].max())),
        "Δ": st.column_config.NumberColumn("Δ rank", format="%d", help="vs previous run"),
        "sent": st.column_config.NumberColumn("news", format="%+.2f",
                                              help="14-day news-sentiment signal (−1…+1)"),
        "catalyst": st.column_config.NumberColumn(format="%.2f"),
        "momentum": st.column_config.NumberColumn(format="%.2f"),
        "newsflow": st.column_config.NumberColumn(format="%.2f"),
        "why": st.column_config.TextColumn(width="large"),
    },
)
st.caption("Full leaderboard + score breakdown on **Stocks in Focus**.")

st.divider()
left, right = st.columns(2, gap="large")

# ------------------------------------------------------------------ headlines
with left:
    eyebrow("High-signal headlines · 7 days")
    hs = recent[pd.to_numeric(recent["event_score"], errors="coerce").abs() >= 0.6]
    hs = hs.sort_values("published", ascending=False).head(12)
    if hs.empty:
        st.caption("nothing tagged high-signal this week")
    for _, r in hs.iterrows():
        col = POS if (r["event_score"] or 0) > 0 else NEG
        when = r["published"].strftime("%b %d") if pd.notna(r["published"]) else ""
        st.markdown(
            f"<div class='bt-card'><div class='bt-row'>"
            f"<span class='bt-tk'>{r['ticker']}</span>"
            f"<span class='bt-meta'>{when} · {r['source']}</span></div>"
            f"<a href='{r['url']}' target='_blank'>{r['title']}</a>"
            f"<div class='bt-meta' style='color:{col}'>{r['event_tags']}</div></div>",
            unsafe_allow_html=True)

# ------------------------------------------------------------------ catalysts
with right:
    eyebrow("Next catalysts")
    nc = cats[(cats["months_away"] >= -0.3) & (cats["months_away"] <= 6)].copy()
    nc = nc.sort_values("date").head(12)
    if nc.empty:
        st.caption("no dated catalysts in the horizon yet")
    for _, r in nc.iterrows():
        st.markdown(
            f"<div class='bt-card'><div class='bt-row'>"
            f"<span><span class='bt-tk'>{r['ticker']}</span> "
            f"<span class='bt-meta'>{r['type']}</span></span>"
            f"<span class='bt-meta'>{r['date']:%b %d %Y} · {r['confidence']}</span></div>"
            f"<div class='bt-meta' style='color:var(--text)'>{str(r['title'])[:120]}</div>"
            f"</div>", unsafe_allow_html=True)
