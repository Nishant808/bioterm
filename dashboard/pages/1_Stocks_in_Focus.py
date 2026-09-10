"""Ranked leaderboard with a full, expandable score decomposition per name."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import prev_scores_df, scores_df, sentiment_df
from _ui import (MUTED, NEG, POS, eyebrow, page_setup, plotly_layout,
                 sentiment_word)
from bioterm import store


def _p(x, unsigned: bool = False) -> str:
    if x is None or pd.isna(x):
        return "–"
    v = float(x) * 100
    return f"{v:.0f}%" if unsigned else f"{v:+.1f}%"


def _f(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{float(x):.2f}"


page_setup("Stocks in Focus",
           "ranked by how much attention a name deserves — score = "
           "conviction × insider × (momentum + catalyst + news flow) − risk")

scores = scores_df()
if scores.empty:
    st.warning("No scores yet — the first ingest run hasn't landed.")
    st.stop()

prev = prev_scores_df().set_index("ticker")
sent = sentiment_df(14).set_index("ticker")

# ------------------------------------------------------------------- filters
f1, f2, f3, f4 = st.columns([1, 1, 1.3, 2])
only_wl = f1.toggle("watchlist", value=False, help="watchlist names only")
only_xbi = f2.toggle("XBI", value=False, help="XBI (small/mid biotech) members only")
min_cat = f3.slider("min catalyst score", 0.0, 1.0, 0.0, 0.05)
search = f4.text_input("filter", "", placeholder="ticker or company name")

df = scores.copy()
if only_wl:
    df = df[df["is_watchlist"] == 1]
if only_xbi:
    df = df[df["in_xbi"] == 1]
if min_cat > 0:
    df = df[df["catalyst"] >= min_cat]
if search:
    s = search.lower()
    df = df[df["ticker"].str.lower().str.contains(s) |
            df["name"].str.lower().str.contains(s)]
df = df.reset_index(drop=True)

if not prev.empty:
    df["Δ"] = df["ticker"].map(
        lambda t: int(prev.loc[t, "rank"]) - int(df.loc[df["ticker"] == t, "rank"].iloc[0])
        if t in prev.index else 0)
else:
    df["Δ"] = 0
df["news"] = df["ticker"].map(lambda t: sent.loc[t, "signal"] if t in sent.index else None)

table = df[["rank", "ticker", "name", "focus_score", "Δ", "news", "momentum",
            "catalyst", "newsflow", "risk", "conviction_mult"]].rename(
    columns={"focus_score": "focus", "conviction_mult": "conv"})

c1, c2 = st.columns([5, 1])
c1.caption(f"{len(df)} names")
c2.download_button("⬇ CSV", table.to_csv(index=False), "bioterm_focus.csv",
                   "text/csv", use_container_width=True)
st.dataframe(
    table, hide_index=True, use_container_width=True, height=460,
    column_config={
        "name": st.column_config.TextColumn(width="medium"),
        "focus": st.column_config.ProgressColumn(
            "focus", format="%.3f",
            min_value=float(scores["focus_score"].min()),
            max_value=float(scores["focus_score"].max())),
        "Δ": st.column_config.NumberColumn("Δ rank", format="%d"),
        "news": st.column_config.NumberColumn("news", format="%+.2f",
                                              help="14-day news-sentiment signal (−1…+1)"),
        "momentum": st.column_config.NumberColumn(format="%.2f"),
        "catalyst": st.column_config.NumberColumn(format="%.2f"),
        "newsflow": st.column_config.NumberColumn(format="%.2f"),
        "risk": st.column_config.NumberColumn(format="%.2f"),
        "conv": st.column_config.NumberColumn(format="%.1f×"),
    },
)

st.divider()

# ------------------------------------------------------------------- decomposition
eyebrow("Score breakdown")
pick = st.selectbox("name", df["ticker"].tolist(), label_visibility="collapsed")
row = df[df["ticker"] == pick].iloc[0]
obj = row["rationale_obj"] or {}
comp = obj.get("components", {})
w = obj.get("weights", {})
mult = obj.get("conviction_mult", 1) * obj.get("insider_mult", 1)

cc1, cc2 = st.columns([1.1, 1])
with cc1:
    contrib = {
        "momentum": w.get("momentum", 0) * comp.get("momentum", 0),
        "catalyst": w.get("catalyst", 0) * comp.get("catalyst", 0),
        "news flow": w.get("newsflow", 0) * comp.get("newsflow", 0),
        "risk": -w.get("risk", 0) * comp.get("risk", 0),
    }
    fig = go.Figure(go.Bar(
        x=list(contrib.values()), y=list(contrib.keys()), orientation="h",
        marker_color=[POS if v >= 0 else NEG for v in contrib.values()],
        text=[f"{v:+.3f}" for v in contrib.values()], textposition="outside",
        textfont=dict(size=11)))
    _mtxt = f"× conviction {obj.get('conviction_mult', 1):.2f}"
    if obj.get("insider_mult", 1) > 1.001:
        _mtxt += f"  ·  × insider {obj['insider_mult']:.2f}"
    fig.update_layout(**plotly_layout(
        height=230, title=f"weighted contributions  ({_mtxt})",
        xaxis_title=None, yaxis=dict(gridcolor="rgba(0,0,0,0)")))
    st.plotly_chart(fig, use_container_width=True)
    m1, m2 = st.columns(2)
    m1.metric("Focus Score", f"{row['focus_score']:.3f}")
    m2.metric("rank", f"#{int(row['rank'])}",
              f"{row['Δ']:+d}" if row["Δ"] else None)

with cc2:
    md = obj.get("momentum_detail", {})
    nd = obj.get("news_detail", {})
    rd = obj.get("risk_detail", {})
    sig = sent.loc[pick] if pick in sent.index else None
    _sw, _sc = sentiment_word(sig["signal"] if sig is not None else None)

    rows_md = [
        ("Momentum", ""),
        ("return 1 / 3 / 6 mo",
         f"{_p(md.get('ret_1m'))} / {_p(md.get('ret_3m'))} / {_p(md.get('ret_6m'))}"),
        ("volume z-score (20d)", _f(md.get("vol_z20"))),
        ("52-week range position", _p(md.get("pct_52w_range"), unsigned=True)),
        ("News flow", ""),
        ("sentiment (14d)",
         f"{_sw}" + (f"  ({sig['signal']:+.2f})" if sig is not None else "")),
        ("headlines (14d)", str(int(sig["n"])) if sig is not None else "–"),
        ("event tilt", _f(nd.get("event_score_sum"))),
        ("Risk", ""),
        ("cash runway (quarters)", _f(obj.get("runway_quarters"))),
        ("dilution filing (75d)", "yes" if rd.get("dilution_filing") else "no"),
        ("negative news (21d)", _f(rd.get("negative_news"))),
    ]
    st.markdown("<div class='bt-card'>" + "".join(
        (f"<div class='bt-eyebrow' style='margin:.5rem 0 .2rem'>{k}</div>"
         if v == "" else
         f"<div class='bt-row'><span class='bt-meta'>{k}</span>"
         f"<span class='mono'>{v}</span></div>")
        for k, v in rows_md) + "</div>", unsafe_allow_html=True)

cd = obj.get("catalyst_detail", [])
if cd:
    eyebrow("Catalyst ledger")
    cdf = pd.DataFrame(cd)[["date", "type", "months_away", "confidence", "contrib", "title"]]
    st.dataframe(cdf, hide_index=True, use_container_width=True,
                 column_config={"contrib": st.column_config.NumberColumn(format="%.3f"),
                                "months_away": st.column_config.NumberColumn("mo away",
                                                                            format="%.1f")})

a1, a2 = st.columns([1, 3])
_on_wl = pick in {x["ticker"].upper() for x in store.get_watchlist()}
if a1.button("★ on watchlist" if _on_wl else "★ add to watchlist", disabled=_on_wl):
    store.add_to_watchlist(pick, 3)
    st.cache_data.clear()
    st.rerun()
a2.page_link("pages/2_Stock_Detail.py", label=f"open {pick} →", icon="🔬")
