"""Ranked leaderboard with a full, expandable score decomposition per name."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import (PLOTLY_TEMPLATE, disclaimer, prev_scores_df, scores_df,
                     sidebar_freshness)
from bioterm import store

st.title("Stocks in Focus")
disclaimer()
sidebar_freshness()

scores = scores_df()
if scores.empty:
    st.warning("No scores yet — run the pipeline first.")
    st.stop()

prev = prev_scores_df().set_index("ticker")

# ------------------------------------------------------------------- filters
f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
only_wl = f1.toggle("watchlist only", value=False)
only_xbi = f2.toggle("XBI members only", value=False)
min_cat = f3.slider("min catalyst score", 0.0, 1.0, 0.0, 0.05)
search = f4.text_input("filter by ticker / name", "")

df = scores.copy()
if only_wl:
    df = df[df["is_watchlist"] == 1]
if only_xbi:
    df = df[df["in_xbi"] == 1]
if min_cat > 0:
    df = df[df["catalyst"] >= min_cat]
if search:
    s = search.lower()
    df = df[df["ticker"].str.lower().str.contains(s) | df["name"].str.lower().str.contains(s)]

df = df.reset_index(drop=True)
if not prev.empty:
    df["Δrank"] = df["ticker"].map(
        lambda t: int(prev.loc[t, "rank"]) - int(df.loc[df["ticker"] == t, "rank"].iloc[0])
        if t in prev.index else 0)
else:
    df["Δrank"] = 0

cap1, cap2 = st.columns([4, 1])
cap1.caption(f"{len(df)} names")
table = df[["rank", "ticker", "name", "focus_score", "momentum", "catalyst",
            "newsflow", "risk", "conviction_mult", "Δrank"]].rename(
    columns={"focus_score": "focus", "conviction_mult": "conv"})
cap2.download_button("⬇ CSV", table.to_csv(index=False), "bioterm_focus.csv",
                     "text/csv", use_container_width=True)
st.dataframe(
    table, hide_index=True, use_container_width=True, height=460,
    column_config={
        "focus": st.column_config.ProgressColumn(
            "focus", format="%.3f",
            min_value=float(scores["focus_score"].min()),
            max_value=float(scores["focus_score"].max())),
        "momentum": st.column_config.NumberColumn(format="%.2f"),
        "catalyst": st.column_config.NumberColumn(format="%.2f"),
        "newsflow": st.column_config.NumberColumn(format="%.2f"),
        "risk": st.column_config.NumberColumn(format="%.2f"),
        "conv": st.column_config.NumberColumn(format="%.1f×"),
    },
)

st.divider()

# ------------------------------------------------------------------- decomposition
st.subheader("Score decomposition")
pick = st.selectbox("pick a name", df["ticker"].tolist())
row = df[df["ticker"] == pick].iloc[0]
obj = row["rationale_obj"] or {}
comp = obj.get("components", {})
w = obj.get("weights", {})

cc1, cc2 = st.columns([1, 1])
with cc1:
    contrib = {
        "momentum": w.get("momentum", 0) * comp.get("momentum", 0),
        "catalyst": w.get("catalyst", 0) * comp.get("catalyst", 0),
        "newsflow": w.get("newsflow", 0) * comp.get("newsflow", 0),
        "risk": -w.get("risk", 0) * comp.get("risk", 0),
    }
    fig = go.Figure(go.Bar(
        x=list(contrib.values()), y=list(contrib.keys()), orientation="h",
        marker_color=["#26a69a" if v >= 0 else "#ef5350" for v in contrib.values()],
        text=[f"{v:+.3f}" for v in contrib.values()], textposition="outside",
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE, height=260, margin=dict(l=10, r=10, t=30, b=10),
        title=f"{pick} — weighted contributions (× conviction {obj.get('conviction_mult', 1):.2f})",
        xaxis_title="contribution to Focus Score",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.metric("Focus Score", f"{row['focus_score']:.3f}", f"rank #{int(row['rank'])}")

with cc2:
    md = obj.get("momentum_detail", {})
    st.markdown("**Momentum inputs**")
    st.write({
        "return 1m": md.get("ret_1m"), "return 3m": md.get("ret_3m"),
        "return 6m": md.get("ret_6m"), "volume z (20d)": md.get("vol_z20"),
        "position in 52w range": md.get("pct_52w_range"),
    })
    nd = obj.get("news_detail", {})
    if nd:
        st.markdown("**News flow (14d)**")
        st.write(nd)
    rd = obj.get("risk_detail", {})
    if rd:
        st.markdown("**Risk overlay**")
        st.write({**rd, "runway_quarters": obj.get("runway_quarters")})

cd = obj.get("catalyst_detail", [])
if cd:
    st.markdown("**Catalyst ledger (contribution-ranked)**")
    st.dataframe(pd.DataFrame(cd), hide_index=True, use_container_width=True)

act1, act2 = st.columns([1, 3])
_on_wl = pick in {w["ticker"].upper() for w in store.get_watchlist()}
if act1.button("★ on watchlist" if _on_wl else "★ add to watchlist", disabled=_on_wl):
    store.add_to_watchlist(pick, 3)
    st.cache_data.clear()
    st.toast(f"{pick} added to watchlist")
    st.rerun()
act2.page_link("pages/2_Stock_Detail.py", label=f"→ open {pick} detail", icon="🔬")
