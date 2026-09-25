"""Stocks in focus - the ranked leaderboard with a full per-name score breakdown."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import prev_scores_df, scores_df, sentiment_df, signal_board
from _ui import (ACCENT, CATALYST_TYPES, FAMILIES, NEG, TEXT_2, card, catalyst_family,
                 catalyst_label, catalyst_title, chart, display_name, empty_state, kpi_row,
                 kv_list, page_header, plotly_layout, tone_of)
import _auth
from bioterm import store


def _pct(x, unsigned: bool = False) -> str:
    if x is None or pd.isna(x):
        return "–"
    v = float(x) * 100
    return f"{v:.0f}%" if unsigned else f"{v:+.1f}%"


def _f(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{float(x):.2f}"


page_header("Stocks in focus",
            "Ranked by how much attention a name deserves · Focus = conviction × insider × "
            "(momentum + catalyst + news flow) − risk")

scores = scores_df()
if scores.empty:
    empty_state("No scores yet", "The first ingestion run hasn't landed.", "hourglass_top")
    st.stop()

prev = prev_scores_df().set_index("ticker")
sent = sentiment_df(14).set_index("ticker")

# ------------------------------------------------------------------ filters
with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    search = st.text_input("Search", placeholder="Search ticker or company",
                           icon=":material/search:", label_visibility="collapsed", width=300)
    scope = st.pills("Scope", ["Watchlist", "XBI members"], selection_mode="multi",
                     label_visibility="collapsed",
                     help="Watchlist = your names; XBI = small/mid-cap biotech ETF members. "
                          "Both selected = names in both.")
    min_cat = st.slider("Minimum catalyst score", 0.0, 1.0, 0.0, 0.05, width=260)

df = scores.copy()
if "Watchlist" in (scope or []):
    df = df[df["is_watchlist"] == 1]
if "XBI members" in (scope or []):
    df = df[df["in_xbi"] == 1]
if min_cat > 0:
    df = df[df["catalyst"] >= min_cat]
if search:
    s = search.lower()
    df = df[df["ticker"].str.lower().str.contains(s, regex=False)
            | df["name"].str.lower().str.contains(s, regex=False)]
df = df.reset_index(drop=True)

df["Δ"] = [int(prev.loc[t, "rank"]) - int(r) if t in prev.index else 0
           for t, r in zip(df["ticker"], df["rank"])]
df["news"] = df["ticker"].map(lambda t: sent["signal"].get(t) if t in sent.index else None)
df["company"] = df["name"].map(display_name)
_calls = signal_board().set_index("ticker")["label"].to_dict()
df["call"] = df["ticker"].map(lambda t: [str(_calls[t]).title()] if t in _calls else [])

table = df[["rank", "ticker", "company", "focus_score", "Δ", "call", "news", "momentum",
            "catalyst", "newsflow", "risk", "conviction_mult"]]

with card("Leaderboard", icon_name="leaderboard",
          meta=f"{len(df)} of {len(scores)} names"):
    if df.empty:
        empty_state("No names match these filters", "Clear the search or scope to see the "
                    "full list.", "filter_alt_off")
    else:
        st.dataframe(
            table, hide_index=True, height=440,
            column_config={
                "rank": st.column_config.NumberColumn("#", width=44),
                "ticker": st.column_config.TextColumn("Ticker", width=72),
                "company": st.column_config.TextColumn("Company", width="medium"),
                "focus_score": st.column_config.ProgressColumn(
                    "Focus", format="%.3f", width=150,
                    min_value=float(scores["focus_score"].min()),
                    max_value=float(scores["focus_score"].max())),
                "Δ": st.column_config.NumberColumn(
                    "Δ rank", format="%d", width=70,
                    help="Places moved since the previous run (positive = climbed)"),
                "call": st.column_config.MultiselectColumn(
                    "Signal", width=105,
                    options=["Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"],
                    color=["green", "green", "gray", "red", "red"],
                    help="The signal engine's current call - see the Signals page"),
                "news": st.column_config.NumberColumn(
                    "News", format="%+.2f", width=70, help="14-day news signal (−1 to +1)"),
                "momentum": st.column_config.NumberColumn("Momentum", format="%.2f"),
                "catalyst": st.column_config.NumberColumn("Catalyst", format="%.2f"),
                "newsflow": st.column_config.NumberColumn("News flow", format="%.2f"),
                "risk": st.column_config.NumberColumn("Risk", format="%.2f"),
                "conviction_mult": st.column_config.NumberColumn(
                    "Conviction", format="%.1f×", help="Your watchlist conviction multiplier"),
            },
        )
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("Sub-scores run 0–1. Risk is subtracted; conviction and insider buying "
                   "multiply.")
        st.space("stretch")
        st.download_button("Export CSV", table.to_csv(index=False), "bioterm_focus.csv",
                           "text/csv", icon=":material/download:", type="tertiary")

if df.empty:
    st.stop()

# ------------------------------------------------------------------ breakdown
with card("Score breakdown", icon_name="donut_large"):
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        pick = st.selectbox("Name", df["ticker"].tolist(), label_visibility="collapsed",
                            format_func=lambda t: f"{t} · {df.loc[df['ticker'] == t, 'company'].iloc[0]}",
                            width=380)
        st.space("stretch")
        _on_wl = pick in {x["ticker"].upper() for x in store.get_watchlist()}
        if st.button("On watchlist" if _on_wl else "Add to watchlist",
                     icon=":material/bookmark_added:" if _on_wl else ":material/bookmark_add:",
                     disabled=_on_wl or not _auth.can_edit(),
                     help=None if _auth.can_edit() else "Unlock to edit the watchlist"):
            store.add_to_watchlist(pick, 3)
            st.cache_data.clear()
            st.rerun()
        st.page_link("app_pages/stock.py", label=f"Open {pick}", icon=":material/open_in_new:",
                     query_params={"ticker": pick})

    row = df[df["ticker"] == pick].iloc[0]
    obj = row["rationale_obj"] or {}
    comp = obj.get("components", {})
    w = obj.get("weights", {})

    left, right = st.columns([1.15, 1], gap="large")
    with left:
        with kpi_row(3, "breakdown"):
            st.metric("Focus Score", f"{row['focus_score']:.3f}", border=True)
            st.metric("Rank", f"#{int(row['rank'])}",
                      delta=int(row["Δ"]) if row["Δ"] else None,
                      delta_description="places since last run" if row["Δ"] else None,
                      border=True)
            mult = obj.get("conviction_mult", 1) * obj.get("insider_mult", 1)
            st.metric("Multiplier", f"×{mult:.2f}",
                      help="Your conviction × insider-buying multiplier, applied to the "
                           "weighted sum before risk is subtracted.", border=True)

        contrib = [
            ("Catalyst", w.get("catalyst", 0) * comp.get("catalyst", 0)),
            ("Momentum", w.get("momentum", 0) * comp.get("momentum", 0)),
            ("News flow", w.get("newsflow", 0) * comp.get("newsflow", 0)),
            ("Risk", -w.get("risk", 0) * comp.get("risk", 0)),
        ]
        labels = [c[0] for c in contrib]
        vals = [round(c[1], 3) + 0.0 for c in contrib]  # + 0.0 turns -0.0 into 0.0
        fig = go.Figure(go.Bar(
            x=vals, y=labels, orientation="h", width=0.55,
            marker=dict(color=[ACCENT if v >= 0 else NEG for v in vals]),
            text=[f"{v:+.3f}" for v in vals], textposition="outside",
            textfont=dict(size=11, color=TEXT_2), cliponaxis=False,
            hovertemplate="%{y}: %{x:+.3f}<extra></extra>"))
        span = max(0.05, max(abs(v) for v in vals)) * 1.35
        fig.update_layout(**plotly_layout(
            height=200, margin=dict(l=4, r=24, t=8, b=4),
            xaxis=dict(range=[-span, span], zeroline=True, zerolinecolor="#334055",
                       zerolinewidth=1, showgrid=False, showticklabels=False),
            yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=12))))
        st.caption("Weighted contribution of each component to the Focus Score")
        chart(fig, key="contrib")

    with right:
        md = obj.get("momentum_detail", {})
        nd = obj.get("news_detail", {})
        rd = obj.get("risk_detail", {})
        sig = sent.loc[pick] if pick in sent.index else None
        tw, tc = tone_of(sig["signal"] if sig is not None else None)
        runway = obj.get("runway_quarters")
        kv_list([
            ("Momentum", None, None),
            ("Return 1 / 3 / 6 months",
             f"{_pct(md.get('ret_1m'))} · {_pct(md.get('ret_3m'))} · {_pct(md.get('ret_6m'))}",
             None),
            ("Volume z-score (20 days)", _f(md.get("vol_z20")), None),
            ("Position in 52-week range", _pct(md.get("pct_52w_range"), unsigned=True), None),
            ("News flow", None, None),
            ("Sentiment (14 days)",
             tw + (f"  {sig['signal']:+.2f}" if sig is not None else ""), tc),
            ("Headlines (14 days)", str(int(sig["n"])) if sig is not None else "–", None),
            ("Event tilt", _f(nd.get("event_score_sum")), None),
            ("Risk", None, None),
            ("Cash runway (quarters)", _f(runway),
             NEG if runway is not None and not pd.isna(runway) and runway < 4 else None),
            ("Dilution filing (75 days)", "Yes" if rd.get("dilution_filing") else "No",
             NEG if rd.get("dilution_filing") else None),
            ("Going-concern doubt (latest 10-K/10-Q)",
             "Yes" if rd.get("going_concern") else "No",
             NEG if rd.get("going_concern") else None),
            ("Negative news (21 days)", _f(rd.get("negative_news")), None),
        ])

    cd = obj.get("catalyst_detail", [])
    if cd:
        cdf = pd.DataFrame(cd)
        cdf["date"] = pd.to_datetime(cdf["date"], errors="coerce")
        cdf["type_badge"] = cdf["type"].map(lambda t: [catalyst_label(t)])
        cdf["title"] = cdf["title"].map(catalyst_title)
        all_labels = [v[0] for v in CATALYST_TYPES.values()]
        st.caption("Catalysts counted in this score")
        st.dataframe(
            cdf[["date", "type_badge", "months_away", "confidence", "contrib", "title"]],
            hide_index=True,
            column_config={
                "date": st.column_config.DateColumn("Date", format="MMM D, YYYY", width=110),
                "type_badge": st.column_config.MultiselectColumn(
                    "Type", options=all_labels, width=160,
                    color=[FAMILIES[f][2] for f in (catalyst_family(k) for k in CATALYST_TYPES)]),
                "months_away": st.column_config.NumberColumn("Months away", format="%.1f",
                                                             width=100),
                "confidence": st.column_config.TextColumn("Confidence", width=100),
                "contrib": st.column_config.NumberColumn("Contribution", format="%.3f",
                                                         width=100),
                "title": st.column_config.TextColumn("Detail", width="large"),
            })
