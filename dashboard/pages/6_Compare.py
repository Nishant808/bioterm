"""Side-by-side comparison of 2-4 names: normalized price, score, catalysts, fundamentals."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import (catalysts_df, fundamentals_row, money, prices_df, scores_df,
                     sentiment_df)
from _ui import WARN, eyebrow, page_setup, plotly_layout

page_setup("Compare", "2–4 names side by side")

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
    fig.add_vline(x=c["date"], line=dict(color=WARN, dash="dot", width=1))
fig.update_layout(**plotly_layout(
    height=400, yaxis_title="% change",
    title="price, rebased to 0% at start of window · amber = catalysts ≤6mo"))
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- score + fundamentals
sig = sentiment_df(14).set_index("ticker")
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
        "news flow": round(float(s["newsflow"]), 2),
        "news sentiment": round(float(sig.loc[tk, "signal"]), 2) if tk in sig.index else None,
        "risk": round(float(s["risk"]), 2),
        "catalysts ≤6mo": ncat,
        "market cap": money(f.get("market_cap")),
        "cash": money(f.get("cash")),
        "runway (Q)": None if f.get("runway_quarters") is None
        else round(float(f["runway_quarters"] or 0), 1),
    })
st.dataframe(pd.DataFrame(rows).set_index("ticker").T, use_container_width=True)

eyebrow("catalyst calendars")
cc = catalysts_df()
cc = cc[(cc["ticker"].isin(picks)) & (cc["months_away"].between(-0.5, 9))].sort_values("date")
if cc.empty:
    st.caption("no catalysts in range")
else:
    st.dataframe(cc[["date", "ticker", "type", "title", "confidence", "source"]],
                 hide_index=True, use_container_width=True)
