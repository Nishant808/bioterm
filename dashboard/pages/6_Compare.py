"""Side-by-side comparison of 2-4 names: normalized price, score, catalysts, fundamentals."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import (PLOTLY_TEMPLATE, catalysts_df, disclaimer, fundamentals_row,
                     money, prices_df, scores_df, sidebar_freshness)

st.title("Compare")
disclaimer()
sidebar_freshness()

scores = scores_df()
if scores.empty:
    st.warning("No scores yet.")
    st.stop()

opts = scores["ticker"].tolist()
default = [t for t in scores.head(3)["ticker"]]
picks = st.multiselect("names to compare (2–4)", opts, default=default, max_selections=4)
win = st.radio("window", ["3M", "6M", "1Y", "2Y"], horizontal=True, index=1)
days = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 520}[win]

if len(picks) < 2:
    st.info("pick at least two.")
    st.stop()

# ---------------------------------------------------------------- normalized price
fig = go.Figure()
for tk in picks:
    p = prices_df(tk).tail(days)
    if p.empty:
        continue
    base = p["close"].iloc[0]
    fig.add_trace(go.Scatter(x=p["date"], y=(p["close"] / base - 1) * 100, name=tk,
                             mode="lines"))
cats = catalysts_df()
cats = cats[(cats["ticker"].isin(picks)) & (cats["months_away"].between(-0.5, 6))]
for _, c in cats.iterrows():
    fig.add_vline(x=c["date"], line=dict(color="#ffd54f", dash="dot", width=1))
fig.update_layout(template=PLOTLY_TEMPLATE, height=420, legend=dict(orientation="h"),
                  margin=dict(l=10, r=10, t=30, b=10),
                  title=f"price, rebased to 0% at start of window · gold = catalysts ≤6mo",
                  yaxis_title="% change")
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- score + fundamentals
rows = []
for tk in picks:
    s = scores[scores["ticker"] == tk].iloc[0]
    f = fundamentals_row(tk)
    ncat = int((catalysts_df()["ticker"].eq(tk) &
                catalysts_df()["months_away"].between(-0.5, 6)).sum())
    rows.append({
        "ticker": tk,
        "focus": round(float(s["focus_score"]), 3),
        "rank": int(s["rank"]),
        "momentum": round(float(s["momentum"]), 2),
        "catalyst": round(float(s["catalyst"]), 2),
        "newsflow": round(float(s["newsflow"]), 2),
        "risk": round(float(s["risk"]), 2),
        "catalysts ≤6mo": ncat,
        "market cap": money(f.get("market_cap")),
        "cash": money(f.get("cash")),
        "runway (Q)": None if f.get("runway_quarters") is None else round(float(f["runway_quarters"] or 0), 1),
    })
st.dataframe(pd.DataFrame(rows).set_index("ticker").T, use_container_width=True)

# ---------------------------------------------------------------- catalyst timelines
st.subheader("catalyst calendars")
cc = catalysts_df()
cc = cc[(cc["ticker"].isin(picks)) & (cc["months_away"].between(-0.5, 9))].sort_values("date")
if cc.empty:
    st.caption("no catalysts in range")
else:
    st.dataframe(cc[["date", "ticker", "type", "title", "confidence", "source"]],
                 hide_index=True, use_container_width=True)
