"""Forward calendar of every dated catalyst in the horizon."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from _shared import (PLOTLY_TEMPLATE, catalysts_df, disclaimer, scores_df,
                     sidebar_freshness)

st.title("Catalyst Calendar")
disclaimer()
sidebar_freshness()

cats = catalysts_df()
if cats.empty:
    st.warning("No catalysts derived yet — run `bioterm score`.")
    st.stop()

scores = scores_df()[["ticker", "focus_score", "rank", "is_watchlist"]]
cats = cats.merge(scores, on="ticker", how="left")

c1, c2, c3 = st.columns(3)
horizon = c1.slider("months ahead", 1, 12, 6)
types = c2.multiselect("catalyst types", sorted(cats["type"].unique()),
                       default=sorted(cats["type"].unique()))
only_wl = c3.toggle("watchlist only", value=False)

view = cats[(cats["months_away"] >= -0.5) & (cats["months_away"] <= horizon)]
view = view[view["type"].isin(types)]
if only_wl:
    view = view[view["is_watchlist"] == 1]
view = view.sort_values("date")

st.caption(f"{len(view)} catalysts · {view['ticker'].nunique()} companies")

# ---------------------------------------------------------------- timeline
if not view.empty:
    fig = px.scatter(
        view, x="date", y="ticker", color="type", symbol="confidence",
        size=view["focus_score"].fillna(0.1).clip(lower=0.05) * 10,
        hover_data=["title", "months_away", "source"],
        template=PLOTLY_TEMPLATE, height=max(320, 22 * view["ticker"].nunique()))
    fig.add_vline(x=pd.Timestamp.today(), line=dict(color="#fff", dash="dot"))
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- month buckets
view = view.assign(month=view["date"].dt.strftime("%Y-%m"))
for month, grp in view.groupby("month"):
    st.subheader(pd.to_datetime(month + "-01").strftime("%B %Y"))
    st.dataframe(
        grp[["date", "ticker", "type", "title", "confidence", "source", "rank", "url"]]
        .rename(columns={"rank": "focus_rank"}),
        hide_index=True, use_container_width=True,
        column_config={
            "url": st.column_config.LinkColumn("src", display_text="↗"),
            "date": st.column_config.DateColumn(format="MMM DD"),
        },
    )
