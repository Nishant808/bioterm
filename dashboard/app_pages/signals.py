"""Signals - the early-warning board: every name's BUY/SELL call, what changed
since the last session, and the evidence behind each call."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import _live as live
from _shared import backtest_result, signal_board, signal_history, signal_label_history, signals_today
from _ui import (BORDER_STRONG, DETECTORS, MUTED, NEG, POS, SIGNAL_COLORS, SIGNAL_FAMILIES,
                 SIGNAL_LABELS, call_rows, card, chart, detector_name, display_name,
                 empty_state, esc, kpi_row, page_header, plotly_layout, regime_word,
                 signal_badge, signal_rows)

page_header("Signals",
            "Early BUY / SELL detection · price, catalysts, cash, insiders, specialist funds, "
            "news and options flow, combined per name")

board = signal_board()
fired = signals_today()
if board.empty:
    empty_state("No signal run yet",
                "The signal engine runs after every data refresh. Calls appear here once "
                "prices and catalysts have landed.", "hourglass_top")
    st.stop()

asof = pd.to_datetime(board["asof"].iloc[0])
regime = str(board["regime"].dropna().iloc[0]) if board["regime"].notna().any() else "neutral"
r_word, r_col, r_tip = regime_word(regime)
counts = board["label"].value_counts()
changed = board[board["prev_label"].notna() & (board["prev_label"] != board["label"])]
upgrades = changed[changed["net"] > 0]
hist = signal_label_history(120)


def _series(label: str) -> list[float] | None:
    if hist.empty:
        return None
    s = hist[hist["label"] == label].set_index("asof")["n"]
    s = s.reindex(sorted(hist["asof"].unique()), fill_value=0)
    return [float(v) for v in s] if len(s) >= 2 else None


# ------------------------------------------------------------------ KPIs
with kpi_row(5, "signals"):
    st.metric("Sector regime", r_word, delta="XBI trend filter", delta_color="off",
              delta_arrow="off", border=True, help=r_tip)
    st.metric("Strong buy", int(counts.get("STRONG BUY", 0)),
              delta=f"{int(counts.get('BUY', 0))} more at Buy", delta_color="off",
              delta_arrow="off", border=True, chart_data=_series("STRONG BUY"),
              chart_type="bar", help="Names where at least two independent evidence "
                                     "families agree on the upside. Bars: daily count.")
    st.metric("Strong sell", int(counts.get("STRONG SELL", 0)),
              delta=f"{int(counts.get('SELL', 0))} more at Sell", delta_color="off",
              delta_arrow="off", border=True, chart_data=_series("STRONG SELL"),
              chart_type="bar", help="Names where at least two evidence families agree "
                                     "on the downside. Bars: daily count.")
    st.metric("Calls changed", len(changed),
              delta=f"{len(upgrades)} up · {len(changed) - len(upgrades)} down",
              delta_color="off", delta_arrow="off", border=True,
              help="Names whose label differs from the previous signal run")
    st.metric("Detectors firing", len(fired),
              delta=f"{fired['ticker'].nunique() if not fired.empty else 0} names",
              delta_color="off", delta_arrow="off", border=True,
              help=f"Across {len(board)} names on the {asof:%b %d} run")

# ------------------------------------------------------------------ strongest calls
buys = board[board["label"].isin(["STRONG BUY", "BUY"])].sort_values("net", ascending=False)
sells = board[board["label"].isin(["STRONG SELL", "SELL"])].sort_values("net")
left, right = st.columns(2, gap="medium")
with left:
    with card("Strongest buy signals", icon_name="north_east",
              meta=f"{len(buys)} names"):
        if buys.empty:
            empty_state("No buy calls today", "Nothing clears the Buy threshold on this run.",
                        "trending_flat")
        else:
            call_rows(buys.head(10), n_reasons=2)
with right:
    with card("Strongest sell signals", icon_name="south_east",
              meta=f"{len(sells)} names"):
        if sells.empty:
            empty_state("No sell calls today", "Nothing clears the Sell threshold on this run.",
                        "trending_flat")
        else:
            call_rows(sells.head(10), n_reasons=2)

if not changed.empty:
    with card("Changed since the last run", icon_name="swap_vert",
              meta=f"{len(changed)} names · the earliest warnings"):
        rank = {lab: i for i, lab in enumerate(SIGNAL_LABELS)}
        ch = changed.assign(jump=[rank.get(p, 2) - rank.get(c, 2)
                                  for p, c in zip(changed["prev_label"], changed["label"])])
        call_rows(ch.reindex(ch["jump"].abs().sort_values(ascending=False).index).head(12))

# ------------------------------------------------------------------ the board
with card("Signal board", icon_name="table_rows",
          meta=f"Run of {asof:%b %d, %Y} · net = bull − bear"):
    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        side = st.segmented_control("Show", ["All", "Buy side", "Sell side", "Changed"],
                                    default="All", required=True, key="sg_side")
        scope = st.pills("Scope", ["Watchlist"], selection_mode="multi", key="sg_scope")
        fams = st.multiselect("Evidence", list(SIGNAL_FAMILIES),
                              format_func=lambda f: SIGNAL_FAMILIES[f][0], key="sg_fam",
                              placeholder="Any evidence family", width=360)
    view = board.copy()
    if side == "Buy side":
        view = view[view["net"] > 0]
    elif side == "Sell side":
        view = view[view["net"] < 0]
    elif side == "Changed":
        view = view[view["ticker"].isin(changed["ticker"])]
    if scope:
        view = view[view["is_watchlist"] == 1]
    if fams and not fired.empty:
        view = view[view["ticker"].isin(fired[fired["family"].isin(fams)]["ticker"])]
    reasons = fired.groupby("ticker")["code"].apply(
        lambda s: [detector_name(c) for c in s]).to_dict() if not fired.empty else {}
    view = view.assign(
        name=view["name"].map(display_name),
        label_b=view["label"].map(lambda x: [str(x).title()]),
        was=view["prev_label"].map(lambda x: str(x).title() if isinstance(x, str) else "–"),
        reasons=view["ticker"].map(lambda t: reasons.get(t, [])))
    view = view.reset_index(drop=True)
    # live price + today's move from Yahoo (the engine's own close is its input, not
    # what the board shows)
    lq = live.quotes(view["ticker"].tolist())
    view["price"] = view["ticker"].map(lambda t: (lq.get(t) or {}).get("price"))
    view["day"] = view["ticker"].map(lambda t: (lq.get(t) or {}).get("change_pct"))
    lab_opts = [x.title() for x in SIGNAL_LABELS]
    picked = st.dataframe(
        view[["ticker", "name", "label_b", "net", "bull", "bear", "was", "n_buy", "n_sell",
              "reasons", "price", "day"]],
        hide_index=True, height=520, key="sg_board", on_select="rerun",
        selection_mode="single-row",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", width=70, pinned=True),
            "name": st.column_config.TextColumn("Company", width="medium"),
            "label_b": st.column_config.MultiselectColumn(
                "Call", options=lab_opts, width=120,
                color=["green", "green", "gray", "red", "red"]),
            "net": st.column_config.ProgressColumn("Net", format="%+.2f", min_value=-1.0,
                                                   max_value=1.0, width=120),
            "bull": st.column_config.NumberColumn("Bull", format="%.2f", width=60),
            "bear": st.column_config.NumberColumn("Bear", format="%.2f", width=60),
            "was": st.column_config.TextColumn("Previous", width=95),
            "n_buy": st.column_config.NumberColumn("Buy", width=50,
                                                   help="Buy-side detectors firing"),
            "n_sell": st.column_config.NumberColumn("Sell", width=50,
                                                    help="Sell-side detectors firing"),
            "reasons": st.column_config.ListColumn("Evidence", width="large"),
            "price": st.column_config.NumberColumn("Price", format="$%.2f", width=80,
                                                   help="Live · Yahoo Finance"),
            "day": st.column_config.NumberColumn("Today", format="percent", width=75,
                                                 help="Change vs the previous close"),
        })
    st.caption("Select a row to see its evidence below.")
    rows = list(getattr(getattr(picked, "selection", None), "rows", []) or [])
    sel = view.iloc[rows[0]]["ticker"] if rows and rows[0] < len(view) else None
    if sel and st.session_state.get("_sg_last_sel") != sel:
        st.session_state["sg_pick"] = sel
    st.session_state["_sg_last_sel"] = sel

# ------------------------------------------------------------------ maps
mcol, dcol = st.columns([1.1, 1], gap="medium")
with mcol:
    with card("Bull vs bear map", icon_name="scatter_plot",
              meta="Up-left = clean buy · down-right = clean sell"):
        live = board[(board["bull"] > 0) | (board["bear"] > 0)]
        if live.empty:
            empty_state("Every name is quiet", "", "scatter_plot")
        else:
            fig = go.Figure()
            fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1,
                          line=dict(color=BORDER_STRONG, width=1, dash="dot"))
            for lab in SIGNAL_LABELS:
                g = live[live["label"] == lab]
                if g.empty:
                    continue
                fig.add_trace(go.Scatter(
                    x=g["bear"], y=g["bull"], mode="markers", name=lab.title(),
                    marker=dict(size=9 if "STRONG" in lab else 7, color=SIGNAL_COLORS[lab],
                                line=dict(color="#0B0E14", width=1)),
                    customdata=list(zip(g["ticker"], g["net"])),
                    hovertemplate="<b>%{customdata[0]}</b> · net %{customdata[1]:+.2f}"
                                  "<br>bull %{y:.2f} · bear %{x:.2f}<extra></extra>"))
            fig.update_layout(**plotly_layout(height=360, hovermode="closest"))
            fig.update_xaxes(title_text="Bear pressure", range=[-0.02, 1.02],
                             title_font=dict(size=11, color=MUTED))
            fig.update_yaxes(title_text="Bull pressure", range=[-0.02, 1.02],
                             title_font=dict(size=11, color=MUTED))
            chart(fig, key="sg_map")
with dcol:
    with card("What's firing", icon_name="sensors", meta="Detectors on this run"):
        if fired.empty:
            empty_state("No detector fired", "", "sensors_off")
        else:
            cnt = (fired.groupby(["code", "side"]).size().reset_index(name="n")
                   .sort_values("n"))
            cnt["name"] = cnt["code"].map(detector_name)
            fig = go.Figure(go.Bar(
                x=cnt["n"], y=cnt["name"], orientation="h",
                marker=dict(color=[POS if s == "BUY" else NEG for s in cnt["side"]]),
                customdata=cnt["side"], hovertemplate="%{y}: %{x} names (%{customdata})"
                                                      "<extra></extra>"))
            fig.update_layout(**plotly_layout(height=max(220, 24 * len(cnt) + 40),
                                              showlegend=False))
            fig.update_yaxes(showgrid=False, tickfont=dict(size=11))
            chart(fig, key="sg_fired")

# ------------------------------------------------------------------ drill-down
with card("Evidence for one name", icon_name="manage_search"):
    opts = board["ticker"].tolist()
    names = dict(zip(board["ticker"], board["name"]))
    if st.session_state.get("sg_pick") not in opts:
        qp = st.query_params.get("ticker")
        st.session_state["sg_pick"] = qp if qp in opts else opts[0]
    pick = st.selectbox("Ticker", opts, key="sg_pick", width=420,
                        label_visibility="collapsed",
                        format_func=lambda t: f"{t} · {display_name(names.get(t, ''))}")
    row = board[board["ticker"] == pick].iloc[0]
    st.html(f"<div class='bt-hero'><span class='bt-hero-tk'>{esc(pick)}</span>"
            f"{signal_badge(row['label'])}<span class='bt-net'>net {row['net']:+.2f} · "
            f"bull {row['bull']:.2f} · bear {row['bear']:.2f}</span></div>")
    ev = fired[fired["ticker"] == pick].sort_values(["side", "strength"],
                                                    ascending=[True, False])
    ecol, hcol = st.columns([1.2, 1], gap="medium")
    with ecol:
        if ev.empty:
            empty_state("No detector firing for this name", "", "sensors_off")
        else:
            signal_rows(ev, show_ticker=False)
    with hcol:
        h = signal_history(pick)
        if len(h) > 1:
            fig = go.Figure()
            fig.add_hrect(y0=0.25, y1=1.0, fillcolor="rgba(63,185,107,.06)", line_width=0)
            fig.add_hrect(y0=-1.0, y1=-0.25, fillcolor="rgba(229,72,77,.06)", line_width=0)
            fig.add_hline(y=0, line=dict(color=BORDER_STRONG, width=1))
            fig.add_trace(go.Scatter(x=h["asof"], y=h["net"], mode="lines+markers",
                                     name="Net", line=dict(width=2),
                                     customdata=h["label"],
                                     hovertemplate="%{x|%b %d}: %{y:+.2f} · %{customdata}"
                                                   "<extra></extra>"))
            fig.update_layout(**plotly_layout(height=260, showlegend=False,
                                              title="Net signal over time"))
            fig.update_yaxes(range=[-1, 1], tickvals=[-1, -0.25, 0, 0.25, 1])
            chart(fig, key="sg_hist")
        else:
            st.caption("The net-signal history builds up one point per run.")
    st.page_link("app_pages/stock.py", label=f"Open {pick} in Stock detail",
                 icon=":material/arrow_forward:", query_params={"ticker": pick})

# ------------------------------------------------------------------ method
with st.expander("How the calls are made", icon=":material/info:"):
    ev_bt = (backtest_result("events") or {}).get("by_code") or {}
    ref = pd.DataFrame([
        {"Detector": name, "Side": "Sell" if code in {
            "death_cross", "breakdown_sma200", "volume_surge_down", "crash_day",
            "overbought_exhaustion", "distribution", "relative_strength_laggard",
            "sell_the_news_risk", "catalyst_vacuum", "dilution_filing", "runway_crunch",
            "going_concern", "insider_heavy_selling", "specialist_exit", "negative_event",
            "unusual_put_activity", "short_pressure_rising"} else
            ("Either" if code == "sentiment_inflection" else "Buy"),
         "Evidence": SIGNAL_FAMILIES[fam][0], "Looks for": what,
         "Tested events": (ev_bt.get(code) or {}).get("n"),
         "Excess 3M": (ev_bt.get(code) or {}).get("mean_63"),
         "Hit 3M": (ev_bt.get(code) or {}).get("hit_63")}
        for code, (name, fam, what) in DETECTORS.items()])
    st.markdown(
        "Each detector that fires adds evidence with a strength between 0 and 1. The "
        "strengths combine as independent evidence — *bull = 1 − Π(1 − s)* over buy "
        "detectors, *bear* likewise over sell detectors — and **net = bull − bear**. "
        "Strengths are scaled by the sector regime (XBI trend), your watchlist conviction, "
        "company size for catalyst setups, and — for price detectors — by their measured "
        "edge in the backtest. Net ≥ 0.25 is a **Buy**, ≥ 0.55 a **Strong buy** (mirrored "
        "for sells); a *Strong* call also needs at least two independent evidence families "
        "to agree, so price action alone can't produce one.")
    st.dataframe(ref, hide_index=True, column_config={
        "Looks for": st.column_config.TextColumn(width="large"),
        "Excess 3M": st.column_config.NumberColumn(format="percent",
                                                   help="Mean return vs the equal-weight "
                                                        "universe 63 sessions after firing"),
        "Hit 3M": st.column_config.NumberColumn(format="percent",
                                                help="Share of events that went the "
                                                     "called way")})
    st.caption("Tested columns come from the Backtest page (price and volume detectors "
               "only — the other families don't have point-in-time history yet).")
