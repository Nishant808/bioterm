"""Compare - two to four names side by side: rebased price, scores, catalysts,
fundamentals."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import _live as live
from _shared import catalysts_df, fundamentals_row, money, scores_df, sentiment_df
from _ui import (BORDER_STRONG, CATALYST_TYPES, FAMILIES, SERIES, card, catalyst_family,
                 catalyst_label, catalyst_title, chart, display_name, empty_state,
                 page_header, plotly_layout)

TYPE_LABELS = [v[0] for v in CATALYST_TYPES.values()]
TYPE_COLORS = [FAMILIES[catalyst_family(k)][2] for k in CATALYST_TYPES]

page_header("Compare", "Two to four names side by side")

scores = scores_df()
if scores.empty:
    empty_state("No scores yet", "The first ingestion run hasn't landed.", "hourglass_top")
    st.stop()

names = dict(zip(scores["ticker"], scores["name"].map(display_name)))
opts = scores["ticker"].tolist()
with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    picks = st.multiselect("Names to compare", opts, default=list(scores.head(3)["ticker"]),
                           max_selections=4, format_func=lambda t: f"{t} · {names.get(t, '')}",
                           width=640)
    win = st.segmented_control("Window", ["3M", "6M", "1Y", "2Y"], default="6M",
                               required=True)
days = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 520}[win]

if len(picks) < 2:
    empty_state("Pick at least two names", "Choose up to four to compare.", "compare_arrows")
    st.stop()

# Colour follows the name, not its position in the list: removing one pick
# must not repaint the others (validated series order, lowest free slot).
slots: dict[str, int] = st.session_state.setdefault("cmp_slots", {})
for t in list(slots):
    if t not in picks:
        del slots[t]
for t in picks:
    if t not in slots:
        slots[t] = min(set(range(len(SERIES))) - set(slots.values()))
color = {t: SERIES[slots[t]] for t in picks}

# ------------------------------------------------------------------ rebased price
cats = catalysts_df()
with card("Price, rebased to 0% at the start of the window", icon_name="show_chart",
          meta="Amber lines = catalysts in the window and the next 60 days"):
    fig = go.Figure()
    fig.add_hline(y=0, line=dict(color=BORDER_STRONG, width=1))
    first_d, last_d = None, None
    srcs = set()
    for tk in picks:
        hist, src = live.history(tk, "5y" if days > 500 else "2y")
        srcs.add(src)
        p = hist.tail(days)
        if p.empty:
            continue
        first_d = p["date"].min() if first_d is None else min(first_d, p["date"].min())
        last_d = p["date"].max() if last_d is None else max(last_d, p["date"].max())
        base = p["close"].iloc[0]
        chg = (p["close"] / base - 1) * 100
        fig.add_trace(go.Scatter(x=p["date"], y=chg, name=tk, mode="lines",
                                 line=dict(width=2, color=color[tk]),
                                 hovertemplate="%{y:+.1f}%"))
        fig.add_trace(go.Scatter(  # direct label at the line end
            x=[p["date"].iloc[-1]], y=[chg.iloc[-1]], mode="markers+text",
            marker=dict(size=8, color=color[tk], line=dict(color="#0B0E14", width=2)),
            text=[f" {tk} {chg.iloc[-1]:+.0f}%"], textposition="middle right",
            textfont=dict(size=11, color="#B4BCCB"), showlegend=False, hoverinfo="skip"))
    # catalysts inside the window plus the next 60 days - far-future dates would
    # stretch the time axis and squeeze the price lines
    ahead = pd.Timedelta(days=60)
    near = cats[(cats["ticker"].isin(picks)) & (cats["months_away"].between(-0.5, 6))]
    if last_d is not None:
        near = near[(near["date"] >= first_d) & (near["date"] <= last_d + ahead)]
    for d in near["date"].unique():
        fig.add_vline(x=d, line=dict(color="rgba(224,163,62,.35)", width=1))
    fig.update_layout(**plotly_layout(height=400, hovermode="x unified",
                                      margin=dict(l=4, r=90, t=28, b=4),
                                      yaxis=dict(ticksuffix="%", gridcolor="#1A2230",
                                                 zeroline=False)))
    if last_d is not None:
        fig.update_xaxes(range=[first_d, last_d + (ahead if (near["date"] > last_d).any()
                                                   else pd.Timedelta(days=3))])
    chart(fig, key="compare")
    st.caption(live.source_note("live" if srcs == {"live"} else "stored"))

# ------------------------------------------------------------------ side by side
sig = sentiment_df(14).set_index("ticker")
rows = []
for tk in picks:
    s = scores[scores["ticker"] == tk].iloc[0]
    f = fundamentals_row(tk)
    ncat = int((cats["ticker"].eq(tk) & cats["months_away"].between(-0.5, 6)).sum())
    rows.append({
        "": tk,
        "Focus Score": f"{float(s['focus_score']):.3f}",
        "Rank": f"#{int(s['rank'])}",
        "Momentum": f"{float(s['momentum']):.2f}",
        "Catalyst": f"{float(s['catalyst']):.2f}",
        "News flow": f"{float(s['newsflow']):.2f}",
        "News sentiment": f"{float(sig.loc[tk, 'signal']):+.2f}" if tk in sig.index else "–",
        "Risk": f"{float(s['risk']):.2f}",
        "Catalysts ≤ 6 months": str(ncat),
        "Market cap": money(f.get("market_cap")),
        "Cash": money(f.get("cash")),
        "Runway (quarters)": "–" if f.get("runway_quarters") is None
        else f"{float(f['runway_quarters'] or 0):.1f}",
    })
with card("Side by side", icon_name="table_chart"):
    st.dataframe(pd.DataFrame(rows).set_index("").T)

with card("Catalyst calendars", icon_name="event_upcoming", meta="Next 9 months"):
    cc = cats[(cats["ticker"].isin(picks)) & (cats["months_away"].between(-0.5, 9))]
    cc = cc.sort_values("date")
    if cc.empty:
        empty_state("No catalysts in range", "", "event_busy")
    else:
        st.dataframe(
            cc.assign(type_badge=cc["type"].map(lambda t: [catalyst_label(t)]),
                      title=cc["title"].map(catalyst_title))
            [["date", "ticker", "type_badge", "title", "confidence", "source"]],
            hide_index=True,
            column_config={
                "date": st.column_config.DateColumn("Date", format="MMM D, YYYY", width=110),
                "ticker": st.column_config.TextColumn("Ticker", width=72),
                "type_badge": st.column_config.MultiselectColumn(
                    "Type", options=TYPE_LABELS, color=TYPE_COLORS, width=160),
                "title": st.column_config.TextColumn("Detail", width="large"),
                "confidence": st.column_config.TextColumn("Confidence", width=90),
                "source": st.column_config.TextColumn("Source"),
            })
