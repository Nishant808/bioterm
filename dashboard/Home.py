"""BioTerm — Home / overview."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import (catalysts_df, disclaimer, news_df, prev_scores_df,
                     scores_df, sidebar_freshness)


def _why(obj: dict) -> str:
    if not obj:
        return ""
    comp = obj.get("components", {})
    bits = []
    if comp.get("catalyst", 0) >= 0.4:
        bits.append("catalyst-rich")
    if comp.get("momentum", 0) >= 0.6:
        bits.append("momentum")
    if comp.get("newsflow", 0) >= 0.6:
        bits.append("news flow")
    if comp.get("risk", 0) >= 0.4:
        bits.append("⚠ funding risk")
    if obj.get("conviction_mult", 1) > 1:
        bits.append("your conviction")
    return ", ".join(bits)


st.title("🧬 BioTerm")
st.markdown("**Biotech / pharma catalyst-monitoring terminal** · 6-month swing horizon")
disclaimer()
sidebar_freshness()

scores = scores_df()
if scores.empty:
    st.warning("No scores yet. Run `bioterm init-db && bioterm universe && "
               "bioterm ingest && bioterm score`, then refresh.")
    st.stop()

prev = prev_scores_df().set_index("ticker")
cats = catalysts_df()
news = news_df(400)

# ---------------------------------------------------------------- KPI row
c1, c2, c3, c4 = st.columns(4)
c1.metric("universe", len(scores))
horizon_cats = cats[(cats["months_away"] >= -1) & (cats["months_away"] <= 6)]
c2.metric("catalysts ≤ 6mo", len(horizon_cats))
hi_signal = news[pd.to_numeric(news["event_score"], errors="coerce").abs() >= 0.8]
c3.metric("high-signal headlines", len(hi_signal), help="recent news with a strong event tag")
wl = scores[scores["is_watchlist"] == 1]
c4.metric("watchlist in top 20", int((wl["rank"] <= 20).sum()))

st.divider()
left, right = st.columns([3, 2])

# ---------------------------------------------------------------- Stocks in focus
with left:
    st.subheader("Stocks in focus")
    top = scores.head(12).copy()
    if not prev.empty:
        top["Δrank"] = top.apply(
            lambda r: (int(prev.loc[r["ticker"], "rank"]) - int(r["rank"]))
            if r["ticker"] in prev.index else 0, axis=1)
    else:
        top["Δrank"] = 0
    top["why"] = top["rationale_obj"].map(_why)
    show = top[["rank", "ticker", "name", "focus_score", "Δrank", "why"]].rename(
        columns={"focus_score": "score"})
    st.dataframe(
        show, hide_index=True, use_container_width=True,
        column_config={
            "score": st.column_config.ProgressColumn(
                "score", min_value=float(scores["focus_score"].min()),
                max_value=float(scores["focus_score"].max()), format="%.3f"),
            "Δrank": st.column_config.NumberColumn("Δrank", help="rank change vs last run"),
        },
    )
    st.caption("Open **Stocks in Focus** for the full leaderboard + score decomposition.")

# ---------------------------------------------------------------- Movers
with right:
    st.subheader("Today's score movers")
    if prev.empty:
        st.info("Need two ingest runs to compute movers.")
    else:
        m = scores[["ticker", "name", "focus_score", "rank"]].copy()
        m = m.join(prev["focus_score"].rename("prev"), on="ticker")
        m["Δ"] = m["focus_score"] - m["prev"]
        m = m.dropna(subset=["prev"])
        up = m.sort_values("Δ", ascending=False).head(5)
        dn = m.sort_values("Δ").head(5)
        st.markdown("**▲ rising**")
        st.dataframe(up[["ticker", "name", "Δ"]], hide_index=True,
                     use_container_width=True,
                     column_config={"Δ": st.column_config.NumberColumn(format="%+.3f")})
        st.markdown("**▼ falling**")
        st.dataframe(dn[["ticker", "name", "Δ"]], hide_index=True,
                     use_container_width=True,
                     column_config={"Δ": st.column_config.NumberColumn(format="%+.3f")})

st.divider()

# ---------------------------------------------------------------- Headlines + calendar
h1, h2 = st.columns(2)
with h1:
    st.subheader("High-signal headlines")
    hs = news[pd.to_numeric(news["event_score"], errors="coerce").abs() >= 0.6]
    hs = hs.sort_values("published", ascending=False).head(15)
    if hs.empty:
        st.caption("nothing tagged high-signal in the current window")
    for _, r in hs.iterrows():
        tag = "🟢" if r["event_score"] > 0 else "🔴"
        when = r["published"].strftime("%b %d") if pd.notna(r["published"]) else ""
        st.markdown(
            f"{tag} **[{r['ticker']}]** [{r['title']}]({r['url']})  \n"
            f"<span style='color:#888'>{when} · {r['source']} · {r['event_tags']}</span>",
            unsafe_allow_html=True,
        )

with h2:
    st.subheader("Next catalysts")
    nc = cats[(cats["months_away"] >= -0.5) & (cats["months_away"] <= 6)].copy()
    nc = nc.sort_values("date").head(15)
    if nc.empty:
        st.caption("no dated catalysts in the horizon yet")
    for _, r in nc.iterrows():
        st.markdown(
            f"**{r['date']:%b %d %Y}** · `{r['ticker']}` · **{r['type']}** "
            f"<span style='color:#888'>({r['confidence']})</span>  \n"
            f"<span style='color:#aaa'>{r['title'][:110]}</span>",
            unsafe_allow_html=True,
        )
