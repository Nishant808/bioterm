"""Paper-trading desk — record simulated buys/sells and watch the book's net worth.

Fully separate from the research pages. Fills are simulated at the last daily
close (or a price you enter). No real orders. Long-only.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import scores_df, universe_df
from _ui import ACCENT, MUTED, NEG, POS, eyebrow, page_setup, plotly_layout, stat_strip
from bioterm import portfolio as pf
from bioterm.db import read_sql

page_setup("Paper-Trading Desk",
           "simulated fills at the last daily close · long-only · no real orders — "
           "for testing strategies")


# self-contained cached readers (kept local so this page never depends on a
# helper symbol that a Streamlit Cloud fast-reboot might not have reloaded yet)
@st.cache_data(ttl=120)
def last_close_all() -> dict:
    df = read_sql(
        "SELECT p.ticker, p.close FROM prices p JOIN "
        "(SELECT ticker, MAX(date) d FROM prices GROUP BY ticker) m "
        "ON p.ticker = m.ticker AND p.date = m.d")
    return dict(zip(df["ticker"], df["close"])) if not df.empty else {}


@st.cache_data(ttl=120)
def price_hist(tickers: tuple[str, ...], start: str) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "close"])
    ph = ",".join(f":t{i}" for i in range(len(tickers)))
    params = {f"t{i}": t for i, t in enumerate(tickers)}
    params["s"] = start
    df = read_sql(f"SELECT ticker, date, close FROM prices "
                  f"WHERE ticker IN ({ph}) AND date >= :s ORDER BY date", params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df

# ------------------------------------------------------------------ portfolio bar
plist = pf.list_portfolios()
if not plist:
    pf.ensure_default()
    plist = pf.list_portfolios()

names = {p["id"]: p["name"] for p in plist}
ids = list(names)
# remember the chosen portfolio in the URL so a reload / bookmark keeps it
_want = st.session_state.pop("_pf_new", None) or st.query_params.get("pf")

pcol = st.columns([2.4, 1, 1, 1])
sel = pcol[0].selectbox("portfolio", ids, format_func=lambda i: names[i],
                        index=ids.index(_want) if _want in ids else 0,
                        label_visibility="collapsed")
st.query_params["pf"] = sel

with pcol[1].popover("＋ new", use_container_width=True):
    nn = st.text_input("name", f"Strategy {chr(65 + len(plist))}", key="pf_new_name")
    nc = st.number_input("starting cash ($)", 1000.0, 100_000_000.0, 100_000.0,
                         step=10_000.0, key="pf_new_cash")
    if st.button("create", type="primary", key="pf_new_go"):
        st.session_state["_pf_new"] = pf.create_portfolio(nn, nc)
        st.rerun()
if pcol[2].button("↺ reset", use_container_width=True,
                  help="wipe all trades in this portfolio, keep the cash setting"):
    pf.reset_portfolio(sel)
    st.rerun()
if pcol[3].button("🗑 delete", use_container_width=True, disabled=len(plist) <= 1):
    pf.delete_portfolio(sel)
    st.query_params.pop("pf", None)
    st.rerun()

port = next(p for p in plist if p["id"] == sel)
cash_start = float(port["cash_start"])
trades = pf.get_trades(sel)          # always read fresh from the DB — never cached
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
    held = tuple(sorted(set(trades["ticker"].str.upper())))
    start = pd.to_datetime(trades["ts"]).min().strftime("%Y-%m-%d")
    ph = price_hist(held, start)
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
        st.caption("no trades yet — your trades are saved to the database and "
                   "persist across sessions")
    else:
        st.caption(f"{len(trades)} trade(s) · saved to the database · "
                   f"portfolio `{sel}`")
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
            pf.delete_trade(last_id)
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

    # NOT wrapped in st.form — so changing the ticker reruns and refreshes the
    # price below (a form would batch the change until submit).
    tk = st.selectbox("ticker", uni, key="pf_tk",
                      index=uni.index(held_now[0]) if held_now else 0)
    side = st.radio("side", ["BUY", "SELL"], horizontal=True, key="pf_side")
    lc = last_px.get(tk)

    # per-ticker price state: seeds from that name's last close, remembers your edits
    _pk = f"pf_px::{tk}"
    if _pk not in st.session_state:
        st.session_state[_pk] = round(float(lc), 2) if lc else 0.0

    if "pf_qty" not in st.session_state:
        st.session_state["pf_qty"] = 100.0
    c1, c2 = st.columns(2)
    qty = c1.number_input("quantity", min_value=0.0, step=10.0, key="pf_qty")
    price = c2.number_input("price ($)", min_value=0.0, step=0.01, key=_pk,
                            help=f"last close for {tk}: "
                                 + (f"${lc:,.2f}" if lc else "n/a — enter one"))
    if lc and abs(price - round(float(lc), 2)) >= 0.01:
        if c2.button(f"↺ use last close ${lc:,.2f}", key="pf_usemkt"):
            st.session_state[_pk] = round(float(lc), 2)
            st.rerun()

    c3, c4 = st.columns(2)
    fees = c3.number_input("fees / slippage ($)", min_value=0.0, value=0.0, step=1.0,
                           key="pf_fees")
    tdate = c4.date_input("trade date", value=pd.Timestamp.today(),
                          max_value=pd.Timestamp.today(), key="pf_tdate",
                          help="backdate to reconstruct a past strategy")
    note = st.text_input("note", placeholder="thesis / trigger", key="pf_note")

    est = qty * price + (fees if side == "BUY" else -fees)
    st.caption(("cost" if side == "BUY" else "proceeds")
               + f" ≈ ${abs(est):,.2f}   ·   cash after ≈ "
               + f"${summ['cash'] + (-est if side == 'BUY' else est):,.0f}")

    if lc is None:
        st.caption("⚠️ no price on file for this ticker — enter one manually")

    if st.button(f"{side} {qty:g} {tk}", type="primary", use_container_width=True,
                 key="pf_go"):
        err = pf.validate_trade(trades, cash_start, tk, side, qty, price, fees)
        if err:
            st.error(err)
        else:
            ts = pd.Timestamp(tdate)
            if ts.normalize() >= pd.Timestamp.today().normalize():
                ts = pd.Timestamp.now(tz="UTC").tz_localize(None)
            pf.add_trade(sel, tk, side, qty, price, fees, note, ts=ts.to_pydatetime())
            st.toast(f"saved: {side} {qty:g} {tk} @ ${price:.2f}")
            st.rerun()
