"""Backtest - does any of this precede the move? Event study of every price
detector, a point-in-time factor test of the Focus Score's momentum and the
technical signal, and the live record of the engine's own calls."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import backtest_result
from _ui import (BORDER_STRONG, NEG, POS, SERIES, card, chart, detector_name,
                 empty_state, kpi_row, page_header, plotly_layout)

page_header("Backtest",
            "Point-in-time tests of the signals against what biotech stocks did next")

fac = backtest_result("factor")
evs = backtest_result("events")
trk = backtest_result("track")
if not (fac or evs or trk):
    empty_state("No backtest yet",
                "The backtest runs once a day after the full refresh, over up to five years "
                "of prices.", "history")
    st.stop()

H = [int(h) for h in (fac.get("_params") or evs.get("_params") or {}).get("horizons",
                                                                          [21, 63, 126])]
HNAME = {5: "1 week", 21: "1 month", 63: "3 months", 126: "6 months"}


def _pct(x, digits: int = 1) -> str:
    return "–" if x is None or pd.isna(x) else f"{float(x) * 100:+.{digits}f}%"


# ------------------------------------------------------------------ headline numbers
factors = fac.get("factors") or {}
comb = factors.get("combined") or {}
eq = fac.get("equity") or {}
tot = lambda k: (eq.get(k) or [1.0])[-1] - 1  # noqa: E731
with kpi_row(4, "bt"):
    st.metric("Top-quintile edge · 3 months", _pct(comb.get("spread_63")),
              delta="top minus bottom quintile", delta_color="off", delta_arrow="off",
              border=True, help="Momentum + technical signal, ranked weekly: average 63-session "
                                "excess return of the best fifth minus the worst fifth")
    st.metric("Information coefficient · 1 month",
              "–" if comb.get("ic_21") is None else f"{comb['ic_21']:+.3f}",
              delta=None if comb.get("ic_t_21") is None else f"t = {comb['ic_t_21']:.1f}",
              delta_color="off", delta_arrow="off", border=True,
              help="Rank correlation between the signal and the next month's return, "
                   "averaged across weekly snapshots. 0.03-0.05 is useful; above 0.08 is rare")
    st.metric("Top quintile vs universe", _pct(tot("top") - tot("universe")),
              delta=f"{_pct(tot('top'))} vs {_pct(tot('universe'))}", delta_color="off",
              delta_arrow="off", border=True,
              help="Cumulative, non-overlapping monthly rebalance of the top fifth")
    st.metric("Price events tested", f"{int(evs.get('n_events') or 0):,}",
              delta=f"{fac.get('universe', '–')} names · {fac.get('dates', '–')} snapshots",
              delta_color="off", delta_arrow="off", border=True)

# ------------------------------------------------------------------ equity curve
if eq.get("date"):
    with card("Top quintile, rebalanced monthly", icon_name="show_chart",
              meta=f"{pd.Timestamp(eq['date'][0]):%b %Y} – {pd.Timestamp(eq['date'][-1]):%b %Y}"):
        d = pd.to_datetime(eq["date"])
        fig = go.Figure()
        for k, name, col in (("top", "Top quintile (momentum + signal)", SERIES[0]),
                             ("universe", "Equal-weight universe", SERIES[2]),
                             ("xbi", "XBI", SERIES[1])):
            if eq.get(k):
                fig.add_trace(go.Scatter(x=d, y=[(v - 1) for v in eq[k]], name=name,
                                         mode="lines", line=dict(width=2, color=col),
                                         hovertemplate="%{y:+.0%}"))
        fig.add_hline(y=0, line=dict(color=BORDER_STRONG, width=1))
        fig.update_layout(**plotly_layout(height=340, hovermode="x unified"))
        fig.update_yaxes(tickformat="+.0%")
        chart(fig, key="bt_equity")
        st.caption("Each point is the end of a one-month holding period; no costs, no "
                   "slippage. The universe is today's XBI membership, so failed names that "
                   "left the index are missing (survivorship bias flatters every line).")

# ------------------------------------------------------------------ factor table
if factors:
    qcol, tcol = st.columns([1, 1.2], gap="medium")
    with qcol:
        with card("Quintile returns · 3 months", icon_name="bar_chart",
                  meta="Excess vs the universe, lowest → highest rank"):
            fig = go.Figure()
            for i, (k, f) in enumerate(factors.items()):
                qs = f.get("quintiles_63")
                if qs:
                    fig.add_trace(go.Bar(x=[f"Q{j + 1}" for j in range(len(qs))], y=qs,
                                         name=f.get("label", k), marker_color=SERIES[i % 4],
                                         hovertemplate="%{y:+.1%}"))
            fig.add_hline(y=0, line=dict(color=BORDER_STRONG, width=1))
            fig.update_layout(**plotly_layout(height=300, barmode="group"))
            fig.update_yaxes(tickformat="+.0%")
            chart(fig, key="bt_quint")
    with tcol:
        with card("Factor scorecard", icon_name="table_chart"):
            rows = []
            for k, f in factors.items():
                r = {"Factor": f.get("label", k)}
                for h in H:
                    r[f"IC {HNAME.get(h, h)}"] = f.get(f"ic_{h}")
                    r[f"Spread {HNAME.get(h, h)}"] = f.get(f"spread_{h}")
                r["Top beats universe"] = f.get("top_hit_rate")
                rows.append(r)
            tbl = pd.DataFrame(rows)
            cfg = {c: st.column_config.NumberColumn(format="%+.3f") for c in tbl
                   if c.startswith("IC")}
            cfg.update({c: st.column_config.NumberColumn(format="percent") for c in tbl
                        if c.startswith("Spread") or c == "Top beats universe"})
            cfg["Factor"] = st.column_config.TextColumn(width="medium")
            st.dataframe(tbl, hide_index=True, column_config=cfg)
            st.caption("IC = rank correlation of the factor with forward returns. Spread = "
                       "top-quintile minus bottom-quintile excess return. \"Top beats "
                       "universe\" = share of weekly snapshots where it did.")

# ------------------------------------------------------------------ event study
by = evs.get("by_code") or {}
if by:
    with card("What happened after each price signal", icon_name="query_stats",
              meta="Excess return vs the equal-weight universe"):
        ev = pd.DataFrame([{"code": c, **v} for c, v in by.items()])
        ev["name"] = ev["code"].map(detector_name)
        ev["Side"] = ev["side"].map({"BUY": "Buy", "SELL": "Sell"})
        # a SELL works when the stock then lags: show "right-way" edge for both sides
        ev["edge_63"] = [(-m if s == "SELL" else m) if m is not None and pd.notna(m) else None
                         for m, s in zip(ev["mean_63"] if "mean_63" in ev else [None] * len(ev),
                                         ev["side"])]
        ev = ev.sort_values("edge_63", ascending=False, na_position="last")
        e = ev.dropna(subset=["edge_63"]).iloc[::-1]
        if not e.empty:
            fig = go.Figure(go.Bar(
                x=e["edge_63"], y=e["name"] + " (" + e["Side"] + ")", orientation="h",
                marker=dict(color=[POS if v > 0 else NEG for v in e["edge_63"]]),
                customdata=list(zip(e["n"], e.get("hit_63", pd.Series([None] * len(e))),
                                    e.get("t_63", pd.Series([None] * len(e))))),
                hovertemplate="%{y}<br>edge %{x:+.1%} · n=%{customdata[0]} · hit "
                              "%{customdata[1]:.0%} · t=%{customdata[2]}<extra></extra>"))
            fig.add_vline(x=0, line=dict(color=BORDER_STRONG, width=1))
            fig.update_layout(**plotly_layout(height=max(260, 26 * len(e) + 60),
                                              showlegend=False,
                                              title="3-month edge in the called direction"))
            fig.update_xaxes(tickformat="+.0%")
            fig.update_yaxes(showgrid=False, tickfont=dict(size=11))
            chart(fig, key="bt_events")
        cols = ["name", "Side", "n", "tickers"]
        cfg = {"name": st.column_config.TextColumn("Signal", width="medium"),
               "n": st.column_config.NumberColumn("Events"),
               "tickers": st.column_config.NumberColumn("Names")}
        for h in H:
            for key, lab, fmt in ((f"mean_{h}", f"Excess {HNAME.get(h, h)}", "percent"),
                                  (f"hit_{h}", f"Hit {HNAME.get(h, h)}", "percent"),
                                  (f"t_{h}", f"t {HNAME.get(h, h)}", "%.1f")):
                if key in ev:
                    cols.append(key)
                    cfg[key] = st.column_config.NumberColumn(lab, format=fmt)
        st.dataframe(ev[cols], hide_index=True, column_config=cfg)
        st.caption("Hit = share of events that went the called way (up for Buy, down for "
                   "Sell) relative to the universe. |t| above 2 is unlikely to be luck. The "
                   "live engine scales each price detector by this measured edge (needs "
                   "50+ events): buy detectors ×0.5–1.3, sell detectors ×0.75–1.3 — "
                   "survivorship bias here penalises sells, so they're never cut as far.")

# ------------------------------------------------------------------ track record
with card("Live track record", icon_name="fact_check",
          meta="Every call the engine has made, scored against what followed"):
    bl = trk.get("by_label") or {}
    if not bl:
        empty_state("No scored calls yet",
                    "Calls are scored once a week, a month and three months have passed. "
                    "The record fills in as the engine runs day after day.", "hourglass_top")
    else:
        rows = []
        for lab in ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]:
            v = bl.get(lab)
            if not v:
                continue
            rows.append({"Call": lab.title(), "Calls": v.get("n"),
                         **{f"Excess {HNAME.get(h, h)}": v.get(f"x_{h}") for h in (5, 21, 63)},
                         **{f"Hit {HNAME.get(h, h)}": v.get(f"hit_{h}") for h in (5, 21, 63)}})
        tbl = pd.DataFrame(rows)
        st.dataframe(tbl, hide_index=True, column_config={
            c: st.column_config.NumberColumn(format="percent") for c in tbl
            if c.startswith(("Excess", "Hit"))})
        rec = pd.DataFrame(trk.get("recent") or [])
        if not rec.empty:
            rec["asof"] = pd.to_datetime(rec["asof"])
            show = [c for c in ("asof", "ticker", "label", "ret_5", "ret_21", "ret_63",
                                "ret_open") if c in rec]
            st.dataframe(rec[show], hide_index=True, column_config={
                "asof": st.column_config.DateColumn("Called", format="MMM D, YYYY"),
                "ticker": st.column_config.TextColumn("Ticker", width=70),
                "label": st.column_config.TextColumn("Call"),
                "ret_5": st.column_config.NumberColumn("1 week", format="percent"),
                "ret_21": st.column_config.NumberColumn("1 month", format="percent"),
                "ret_63": st.column_config.NumberColumn("3 months", format="percent"),
                "ret_open": st.column_config.NumberColumn("Since call", format="percent")})
        st.caption("One observation per change of call (a label held for weeks counts once). "
                   "Excess is vs the equal-weight universe over the same window.")

with st.expander("What this can and can't tell you", icon=":material/info:"):
    st.markdown(
        "- **Point-in-time:** every feature on a date uses prices up to that date only; "
        "future closes are used purely as the outcome.\n"
        "- **Survivorship bias:** the universe is today's XBI membership. Names that failed "
        "and were dropped are missing, which flatters long-side results.\n"
        "- **What's tested:** price and volume detectors and the momentum factor have years "
        "of history. News, filings, insider, 13F, options and catalyst detectors are only "
        "scored live (the track record) — their history wasn't captured point-in-time.\n"
        "- **Costs:** none are modelled. Small caps have wide spreads; real results are "
        "lower.\n"
        f"- Last run: {pd.Timestamp(fac.get('_ts') or evs.get('_ts') or trk.get('_ts')):%b %d, %Y %H:%M} UTC.")
