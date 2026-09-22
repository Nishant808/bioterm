"""Paper trading - record simulated buys and sells and watch the book's net worth.

Fully separate from the research pages. Fills are simulated at the last daily
close (or a price you enter). No real orders. Long-only.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import scores_df, universe_df
from _ui import (ACCENT, BORDER_STRONG, card, chart, empty_state, kpi_row, md_safe,
                 page_header, plotly_layout, spark, usd)
from bioterm import portfolio as pf
from bioterm.db import read_sql

page_header("Paper trading",
            "Simulated fills at the last daily close · long-only · no real orders — for "
            "testing strategies")


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


def _get_last_book() -> str | None:
    try:
        df = read_sql("SELECT value FROM app_meta WHERE key = 'pf_last_book'")
    except Exception:  # noqa: BLE001
        return None
    if df.empty:
        return None
    return str(df.iloc[0]["value"]).strip().strip('"') or None


def _set_last_book(pid: str) -> None:
    from datetime import datetime, timezone

    from bioterm.db import app_meta, bulk_upsert
    bulk_upsert(app_meta, [{"key": "pf_last_book", "value": f'"{pid}"',
                            "updated_at": datetime.now(timezone.utc)}])


# ------------------------------------------------------------------ book bar
plist = pf.list_portfolios()
if not plist:
    pf.ensure_default()
    plist = pf.list_portfolios()

names = {p["id"]: p["name"] for p in plist}
ids = list(names)
# restore the last-used book: fresh-create > URL (?pf=) > DB memory > first
_want = (st.session_state.pop("_pf_new", None)
         or st.query_params.get("pf")
         or _get_last_book())

with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    sel = st.selectbox("Book", ids, format_func=lambda i: names[i],
                       index=ids.index(_want) if _want in ids else 0,
                       label_visibility="collapsed", width=320)
    st.space("stretch")
    with st.popover("New book", icon=":material/add:"):
        nn = st.text_input("Name", f"Strategy {chr(65 + len(plist))}", key="pf_new_name")
        nc = st.number_input("Starting cash ($)", 1000.0, 100_000_000.0, 100_000.0,
                             step=10_000.0, key="pf_new_cash")
        if st.button("Create", type="primary", key="pf_new_go", icon=":material/check:"):
            st.session_state["_pf_new"] = pf.create_portfolio(nn, nc)
            st.rerun()
    reset = st.button("Reset", icon=":material/restart_alt:", type="tertiary",
                      help="Wipe all trades in this book, keep its starting cash")
    delete = st.button("Delete", icon=":material/delete:", type="tertiary",
                       disabled=len(plist) <= 1,
                       help="Delete this book (you always keep at least one)")
st.query_params["pf"] = sel
if st.session_state.get("_pf_last_written") != sel:
    _set_last_book(sel)
    st.session_state["_pf_last_written"] = sel
if reset:
    pf.reset_portfolio(sel)
    st.rerun()
if delete:
    pf.delete_portfolio(sel)
    st.query_params.pop("pf", None)
    st.rerun()

port = next(p for p in plist if p["id"] == sel)
cash_start = float(port["cash_start"])
trades = pf.get_trades(sel)          # always read fresh from the DB — never cached
last_px = last_close_all()
summ = pf.mark_to_market(trades, last_px, cash_start)

curve = pd.DataFrame()
if not trades.empty:
    held = tuple(sorted(set(trades["ticker"].str.upper())))
    start = pd.to_datetime(trades["ts"]).min().strftime("%Y-%m-%d")
    ph = price_hist(held, start)
    curve = pf.equity_curve(trades, ph, cash_start)

# ------------------------------------------------------------------ KPIs
ret = summ["total_return"]
with kpi_row(7, "book"):
    pnl = float(summ["total_pnl"])
    st.metric("Net worth", usd(summ["equity"]),
              # ASCII "-" on purpose: Streamlit reads a delta's direction from it
              delta=("-" if pnl < 0 else "+") + f"${abs(pnl):,.0f}",
              delta_description="since start", border=True,
              chart_data=spark(curve["equity"]) if len(curve) >= 3 else None,
              chart_type="area")
    st.metric("Total return", f"{ret * 100:+.2f}%".replace("-", "−"), border=True)
    st.metric("Cash", usd(summ["cash"]), border=True)
    st.metric("Invested", usd(summ["invested"]), border=True)
    st.metric("Realised P&L", usd(summ["realized_pnl"], sign=True), border=True)
    st.metric("Unrealised P&L", usd(summ["unrealized_pnl"], sign=True), border=True)
    st.metric("Positions", str(summ["n_positions"]), border=True)

# ------------------------------------------------------------------ equity curve
if not trades.empty:
    if len(curve) >= 3:
        with card("Net worth", icon_name="show_chart", meta="Daily, marked at the close"):
            fig = go.Figure()
            fig.add_hline(y=cash_start, line=dict(color=BORDER_STRONG, width=1),
                          annotation_text="Start", annotation_position="top left",
                          annotation_font=dict(size=11, color="#8A94A6"))
            fig.add_trace(go.Scatter(x=curve["date"], y=curve["equity"], name="Net worth",
                                     mode="lines", line=dict(color=ACCENT, width=2),
                                     fill="tozeroy", fillcolor="rgba(91,157,255,.08)",
                                     hovertemplate="$%{y:,.0f}<extra></extra>"))
            rng = float(curve["equity"].max() - curve["equity"].min())
            fig.update_layout(**plotly_layout(
                height=260, hovermode="x unified", showlegend=False,
                yaxis=dict(tickprefix="$", gridcolor="#1A2230",
                           range=[curve["equity"].min() - rng * .3 - 1,
                                  curve["equity"].max() + rng * .3 + 1])))
            chart(fig, key="equity")
    else:
        st.caption("The net-worth chart appears once your trades span a few days.")

book_col, ticket_col = st.columns([1.6, 1], gap="medium")

# ------------------------------------------------------------------ positions
with book_col:
    pos = summ["positions"]
    with card("Positions", icon_name="pie_chart", meta=f"{len(pos)} open"):
        if pos.empty:
            empty_state("No open positions", "Place a trade with the ticket on the right.",
                        "account_balance_wallet")
        else:
            sc = scores_df().set_index("ticker")["rank"].to_dict()
            show = pos.assign(
                focus=pos["ticker"].map(lambda t: sc.get(t)),
                ret=pd.to_numeric(pos["return_pct"], errors="coerce") * 100,
                wt=pos["weight"] * 100,
            )[["ticker", "qty", "avg_cost", "last", "mkt_value", "unrealized_pnl",
               "ret", "wt", "focus"]]
            st.dataframe(
                show, hide_index=True,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker", width=72),
                    "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
                    "avg_cost": st.column_config.NumberColumn("Avg cost", format="$%.2f"),
                    "last": st.column_config.NumberColumn("Last", format="$%.2f"),
                    "mkt_value": st.column_config.NumberColumn("Market value",
                                                               format="$%,.0f"),
                    "unrealized_pnl": st.column_config.NumberColumn("Unrealised",
                                                                    format="dollar"),
                    "ret": st.column_config.NumberColumn("Return", format="%+.1f%%"),
                    "wt": st.column_config.ProgressColumn("Weight", format="%.0f%%",
                                                         min_value=0.0, max_value=100.0),
                    "focus": st.column_config.NumberColumn("Focus #", format="%d"),
                })

    with card("Blotter", icon_name="receipt_long",
              meta=f"{len(trades)} trade(s) · saved to the database"):
        if trades.empty:
            empty_state("No trades yet",
                        "Your trades are saved to the database and persist across sessions.",
                        "receipt_long")
        else:
            tb = trades.copy()
            tb["ts"] = pd.to_datetime(tb["ts"])
            tb["value"] = tb["qty"] * tb["price"]
            st.dataframe(
                tb[["ts", "ticker", "side", "qty", "price", "fees", "value", "note"]]
                .sort_values("ts", ascending=False),
                hide_index=True, height=260,
                column_config={
                    "ts": st.column_config.DatetimeColumn("Time", format="MMM D, HH:mm"),
                    "ticker": st.column_config.TextColumn("Ticker", width=72),
                    "side": st.column_config.TextColumn("Side", width=60),
                    "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
                    "price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "fees": st.column_config.NumberColumn("Fees", format="$%.0f"),
                    "value": st.column_config.NumberColumn("Value", format="$%,.0f"),
                    "note": st.column_config.TextColumn("Note", width="medium"),
                })
            last_id = int(tb.sort_values("ts").iloc[-1]["id"])
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                if st.button("Undo last trade", icon=":material/undo:", type="tertiary"):
                    pf.delete_trade(last_id)
                    st.cache_data.clear()
                    st.rerun()
                st.space("stretch")
                st.download_button("Export CSV", tb.to_csv(index=False),
                                   f"{sel}_blotter.csv", "text/csv",
                                   icon=":material/download:", type="tertiary")

# ------------------------------------------------------------------ trade ticket
with ticket_col:
    with card("Trade ticket", icon_name="swap_horiz", meta="Simulated · long-only"):
        uni = universe_df()["ticker"].tolist()
        held_now = pf.positions(trades)
        held_now = held_now[held_now["qty"] > 1e-9]["ticker"].tolist()

        # NOT wrapped in st.form — so changing the ticker reruns and refreshes the
        # price below (a form would batch the change until submit).
        tk = st.selectbox("Ticker", uni, key="pf_tk",
                          index=uni.index(held_now[0]) if held_now else 0)
        side = st.segmented_control("Side", ["BUY", "SELL"], default="BUY", required=True,
                                    key="pf_side", format_func=str.capitalize,
                                    width="stretch")
        lc = last_px.get(tk)

        # per-ticker price state: seeds from that name's last close, remembers your edits
        _pk = f"pf_px::{tk}"
        if _pk not in st.session_state:
            st.session_state[_pk] = round(float(lc), 2) if lc else 0.0

        if "pf_qty" not in st.session_state:
            st.session_state["pf_qty"] = 100.0
        c1, c2 = st.columns(2, gap="small")
        qty = c1.number_input("Quantity", min_value=0.0, step=10.0, key="pf_qty")
        price = c2.number_input("Price ($)", min_value=0.0, step=0.01, key=_pk,
                                help=f"Last close for {tk}: "
                                     + (f"${lc:,.2f}" if lc else "n/a — enter one"))
        if lc and abs(price - round(float(lc), 2)) >= 0.01:
            if st.button(f"Use last close ${lc:,.2f}", key="pf_usemkt",
                         icon=":material/restart_alt:", type="tertiary"):
                st.session_state[_pk] = round(float(lc), 2)
                st.rerun()

        c3, c4 = st.columns(2, gap="small")
        fees = c3.number_input("Fees / slippage ($)", min_value=0.0, value=0.0, step=1.0,
                               key="pf_fees")
        tdate = c4.date_input("Trade date", value=pd.Timestamp.today(),
                              max_value=pd.Timestamp.today(), key="pf_tdate",
                              help="Backdate to reconstruct a past strategy")
        note = st.text_input("Note", placeholder="Thesis or trigger", key="pf_note")

        est = qty * price + (fees if side == "BUY" else -fees)
        after = summ["cash"] + (-est if side == "BUY" else est)
        st.caption(md_safe(("Cost" if side == "BUY" else "Proceeds")
                           + f" ≈ {usd(abs(est), 2)}  ·  cash after ≈ {usd(after)}"))

        if lc is None:
            st.caption(":material/warning: No price on file for this ticker — enter one "
                       "manually.")

        if st.button(f"{side.capitalize()} {qty:g} {tk}", type="primary", width="stretch",
                     key="pf_go", icon=":material/check:"):
            err = pf.validate_trade(trades, cash_start, tk, side, qty, price, fees)
            if err:
                st.error(err, icon=":material/error:")
            else:
                ts = pd.Timestamp(tdate)
                if ts.normalize() >= pd.Timestamp.today().normalize():
                    ts = pd.Timestamp.now(tz="UTC").tz_localize(None)
                pf.add_trade(sel, tk, side, qty, price, fees, note, ts=ts.to_pydatetime())
                st.toast(md_safe(f"Saved: {side.capitalize()} {qty:g} {tk} @ ${price:.2f}"),
                         icon=":material/check_circle:")
                st.rerun()
