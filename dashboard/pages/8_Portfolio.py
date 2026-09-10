"""Paper-trading desk — record simulated buys/sells and watch the book's net worth.

Fully separate from the research pages. Fills are simulated at the last daily
close (or a price you enter). No real orders. Long-only.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import last_close_all, price_hist, scores_df, universe_df
from _ui import ACCENT, MUTED, NEG, POS, eyebrow, page_setup, plotly_layout, stat_strip
from bioterm import portfolio as pf
from bioterm import store

page_setup("Paper-Trading Desk",
           "simulated fills at the last daily close · long-only · no real orders — "
           "for testing strategies")

# ------------------------------------------------------------------ portfolio bar
plist = store.pf_list()
if not plist:
    store.pf_ensure_default()
    plist = store.pf_list()

pcol = st.columns([2.4, 1, 1, 1])
names = {p["id"]: p["name"] for p in plist}
sel = pcol[0].selectbox("portfolio", list(names), format_func=lambda i: names[i],
                        label_visibility="collapsed")
with pcol[1].popover("＋ new", use_container_width=True):
    nn = st.text_input("name", "Strategy B", key="pf_new_name")
    nc = st.number_input("starting cash ($)", 1000.0, 100_000_000.0, 100_000.0,
                         step=10_000.0, key="pf_new_cash")
    if st.button("create", type="primary", key="pf_new_go"):
        newid = store.pf_create(nn, nc)
        st.cache_data.clear()
        st.session_state["_pf_sel"] = newid
        st.rerun()
if pcol[2].button("↺ reset", use_container_width=True,
                  help="wipe all trades in this portfolio, keep the cash setting"):
    store.pf_reset(sel)
    st.cache_data.clear()
    st.rerun()
if pcol[3].button("🗑 delete", use_container_width=True, disabled=len(plist) <= 1):
    store.pf_delete(sel)
    st.cache_data.clear()
    st.rerun()

port = next(p for p in plist if p["id"] == sel)
cash_start = float(port["cash_start"])
trades = store.pf_get_trades(sel)
last_px = last_close_all()
summ = pf.mark_to_market(trades, last_px, cash_start)

# ------------------------------------------------------------------ equity strip
ret = summ["total_return"]
ret_col = POS if ret > 0 else NEG if ret < 0 else None
stat_strip([
    ("net worth", f"${summ['equity']:,.0f}", ACCENT),
    ("total return", f"{ret * 100:+.2f}%", ret_col),
    ("P&L", f"${summ['total_pnl']:+,.0f}", ret_col),
    ("cash", f"${summ['cash']:,.0f}", None),
    ("invested", f"${summ['invested']:,.0f}", None),
    ("realised", f"${summ['realized_pnl']:+,.0f}", None),
    ("unrealised", f"${summ['unrealized_pnl']:+,.0f}", None),
    ("positions", str(summ["n_positions"]), None),
])

# ------------------------------------------------------------------ equity curve
if not trades.empty:
    held = tuple(sorted(pf.positions(trades)["ticker"].tolist() +
                        trades["ticker"].str.upper().unique().tolist()))
    start = pd.to_datetime(trades["ts"]).min().strftime("%Y-%m-%d")
    ph = price_hist(tuple(set(held)), start)
    curve = pf.equity_curve(trades, ph, cash_start)
    if len(curve) >= 3:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=curve["date"], y=curve["equity"], name="net worth",
                                 line=dict(color=ACCENT, width=2), fill="tozeroy",
                                 fillcolor="rgba(91,157,255,.07)"))
        fig.add_hline(y=cash_start, line=dict(color=MUTED, dash="dot", width=1),
                      annotation_text="start", annotation_position="right")
        rng = float(curve["equity"].max() - curve["equity"].min())
        fig.update_layout(**plotly_layout(
            height=260, title="portfolio net worth",
            yaxis=dict(tickprefix="$", gridcolor="#26303f",
                       range=[curve["equity"].min() - rng * .3 - 1,
                              curve["equity"].max() + rng * .3 + 1])))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("net-worth chart appears once trades span a few days")

st.divider()
book_col, ticket_col = st.columns([1.6, 1], gap="large")

# ------------------------------------------------------------------ positions
with book_col:
    eyebrow("Positions")
    pos = summ["positions"]
    if pos.empty:
        st.caption("no open positions — place a trade →")
    else:
        sc = scores_df().set_index("ticker")["rank"].to_dict()
        show = pos.assign(
            focus=pos["ticker"].map(lambda t: sc.get(t)),
            ret=pd.to_numeric(pos["return_pct"], errors="coerce") * 100,
            wt=pos["weight"] * 100,
        )[["ticker", "qty", "avg_cost", "last", "mkt_value", "unrealized_pnl",
           "ret", "wt", "focus"]]
        st.dataframe(
            show, hide_index=True, use_container_width=True,
            column_config={
                "qty": st.column_config.NumberColumn(format="%.0f"),
                "avg_cost": st.column_config.NumberColumn("avg cost", format="$%.2f"),
                "last": st.column_config.NumberColumn(format="$%.2f"),
                "mkt_value": st.column_config.NumberColumn("mkt value", format="$%,.0f"),
                "unrealized_pnl": st.column_config.NumberColumn("unreal. P&L", format="$%+,.0f"),
                "ret": st.column_config.NumberColumn("return", format="%+.1f%%"),
                "wt": st.column_config.ProgressColumn("weight", format="%.0f%%",
                                                     min_value=0.0, max_value=100.0),
                "focus": st.column_config.NumberColumn("focus #", format="%d"),
            })

    eyebrow("Blotter")
    if trades.empty:
        st.caption("no trades yet")
    else:
        tb = trades.copy()
        tb["ts"] = pd.to_datetime(tb["ts"])
        tb["value"] = tb["qty"] * tb["price"]
        st.dataframe(
            tb[["ts", "ticker", "side", "qty", "price", "fees", "value", "note"]]
            .sort_values("ts", ascending=False),
            hide_index=True, use_container_width=True, height=260,
            column_config={
                "ts": st.column_config.DatetimeColumn("time", format="MMM DD HH:mm"),
                "price": st.column_config.NumberColumn(format="$%.2f"),
                "fees": st.column_config.NumberColumn(format="$%.0f"),
                "value": st.column_config.NumberColumn(format="$%,.0f"),
            })
        last_id = int(tb.sort_values("ts").iloc[-1]["id"])
        if st.button("↶ undo last trade"):
            store.pf_delete_trade(last_id)
            st.cache_data.clear()
            st.rerun()
        st.download_button("⬇ CSV", tb.to_csv(index=False),
                           f"{sel}_blotter.csv", "text/csv")

# ------------------------------------------------------------------ trade ticket
with ticket_col:
    eyebrow("Trade ticket")
    uni = universe_df()["ticker"].tolist()
    held_now = pf.positions(trades)
    held_now = held_now[held_now["qty"] > 1e-9]["ticker"].tolist()

    with st.form("pf_ticket", clear_on_submit=False):
        tk = st.selectbox("ticker", uni,
                          index=uni.index(held_now[0]) if held_now else 0)
        side = st.radio("side", ["BUY", "SELL"], horizontal=True)
        lc = last_px.get(tk)
        c1, c2 = st.columns(2)
        qty = c1.number_input("quantity", min_value=0.0, value=100.0, step=10.0)
        price = c2.number_input("price ($)", min_value=0.0,
                                value=round(float(lc), 2) if lc else 0.0, step=0.01,
                                help="defaults to the last daily close — edit to "
                                     "simulate a specific entry")
        c3, c4 = st.columns(2)
        fees = c3.number_input("fees / slippage ($)", min_value=0.0, value=0.0, step=1.0)
        tdate = c4.date_input("trade date", value=pd.Timestamp.today(),
                              max_value=pd.Timestamp.today(),
                              help="backdate to reconstruct a past strategy")
        note = st.text_input("note", placeholder="thesis / trigger")
        est = qty * price + (fees if side == "BUY" else -fees)
        st.caption(("cost" if side == "BUY" else "proceeds")
                   + f" ≈ ${abs(est):,.2f}   ·   cash after ≈ "
                   + f"${summ['cash'] + (-est if side == 'BUY' else est):,.0f}")
        go_trade = st.form_submit_button(f"{side} {tk}", type="primary",
                                         use_container_width=True)

    if go_trade:
        err = pf.validate_trade(trades, cash_start, tk, side, qty, price, fees)
        if err:
            st.error(err)
        else:
            ts = pd.Timestamp(tdate)
            if ts.normalize() >= pd.Timestamp.today().normalize():
                ts = pd.Timestamp.now(tz="UTC").tz_localize(None)
            store.pf_add_trade(sel, tk, side, qty, price, fees, note,
                               ts=ts.to_pydatetime())
            st.cache_data.clear()
            st.toast(f"{side} {qty:g} {tk} @ ${price:.2f}")
            st.rerun()

    if lc is None:
        st.caption("⚠️ no price on file for this ticker yet — enter one manually")
