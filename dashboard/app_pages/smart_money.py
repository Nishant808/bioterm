"""Smart money & flow - what biotech specialist funds did last quarter (13F),
and where short sellers and options traders are leaning right now."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import inst_filers_df, money, options_latest, short_flow, smart_money
from _ui import (MUTED, NEG, POS, WARN, card, chart, display_name, empty_state, kpi_row,
                 page_header, plotly_layout)

page_header("Smart money & flow",
            "Specialist-fund 13F positions, FINRA short volume and options positioning")

ch, summ = smart_money()
filers = inst_filers_df()
sf = short_flow()
opt = options_latest()

STATUS = ["New", "Added", "Held", "Trimmed", "Exited"]
STATUS_COLORS = ["green", "green", "gray", "orange", "red"]

# ------------------------------------------------------------------ KPIs
period = pd.to_datetime(summ["period"]).max() if not summ.empty else None
buying = summ[summ["net_flow"] > 0] if not summ.empty else summ
selling = summ[summ["net_flow"] < 0] if not summ.empty else summ
press = sf[(sf["delta"] >= 0.08) & (sf["ratio_5d"] >= 0.5)] if not sf.empty else sf
unusual = opt[pd.to_numeric(opt.get("vol_oi_ratio"), errors="coerce") >= 1.5] \
    if not opt.empty else opt
with kpi_row(4, "smart"):
    st.metric("Specialist funds tracked", len(filers),
              delta=f"Quarter to {period:%b %d, %Y}" if period is not None and pd.notna(period)
              else "Waiting for 13F data", delta_color="off", delta_arrow="off", border=True,
              help="Dedicated biotech investors (Baker Bros, RA Capital, Perceptive…). "
                   "13F filings land up to 45 days after quarter end.")
    st.metric("Names with net specialist buying", len(buying),
              delta=f"{len(selling)} with net selling", delta_color="off", delta_arrow="off",
              border=True, help="New + added positions minus trimmed + exited, across funds")
    st.metric("Short pressure rising", len(press),
              delta=f"{len(sf)} names with short-volume data", delta_color="off",
              delta_arrow="off", border=True,
              help="FINRA short share of volume ≥ 50% this week and 8+ points above its "
                   "20-day average")
    st.metric("Unusual options volume", len(unusual),
              delta=f"{len(opt)} chains scanned", delta_color="off", delta_arrow="off",
              border=True, help="Front-month volume at least 1.5× open interest")

tab_funds, tab_short, tab_opt = st.tabs([
    ":material/account_balance: Specialist funds (13F)",
    ":material/trending_down: Short volume",
    ":material/stacked_line_chart: Options"])

# ------------------------------------------------------------------ 13F
with tab_funds:
    if summ.empty:
        empty_state("No 13F holdings yet",
                    "Specialist-fund filings are pulled on the daily full refresh.",
                    "account_balance")
    else:
        def _table(df: pd.DataFrame, key: str) -> None:
            v = df.assign(issuer=df["issuer"].map(display_name),
                          ticker=df["ticker"].fillna("–"))
            st.dataframe(
                v[["ticker", "issuer", "holders", "new", "added", "trimmed", "exited",
                   "value", "funds_buying", "funds_selling"]],
                hide_index=True, key=key,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker", width=70),
                    "issuer": st.column_config.TextColumn("Issuer", width="medium"),
                    "holders": st.column_config.NumberColumn(
                        "Holders", width=70, help="Tracked funds holding it now"),
                    "new": st.column_config.NumberColumn("New", width=50),
                    "added": st.column_config.NumberColumn("Added", width=55),
                    "trimmed": st.column_config.NumberColumn("Trimmed", width=65),
                    "exited": st.column_config.NumberColumn("Exited", width=55),
                    "value": st.column_config.NumberColumn("Value held", format="compact",
                                                           width=90),
                    "funds_buying": st.column_config.ListColumn("Buying", width="medium"),
                    "funds_selling": st.column_config.ListColumn("Selling", width="medium"),
                })

        bcol, scol = st.columns(2, gap="medium")
        with bcol:
            with card("Where specialists are buying", icon_name="north_east",
                      meta=f"{len(buying)} names"):
                if buying.empty:
                    empty_state("No net buying this quarter", "", "trending_flat")
                else:
                    _table(buying.head(40), "sm_buy")
        with scol:
            with card("Where they're selling", icon_name="south_east",
                      meta=f"{len(selling)} names"):
                if selling.empty:
                    empty_state("No net selling this quarter", "", "trending_flat")
                else:
                    _table(selling.sort_values("net_flow").head(40), "sm_sell")

        with card("Most widely held", icon_name="groups",
                  meta="Crowding: how many tracked specialists own each name"):
            crowd = summ[summ["holders"] > 0].sort_values(["holders", "value"],
                                                          ascending=False).head(25)
            fig = go.Figure(go.Bar(
                x=crowd["key"], y=crowd["holders"],
                marker=dict(color=[POS if n > 0 else NEG if n < 0 else MUTED
                                   for n in crowd["net_flow"]]),
                customdata=list(zip(crowd["issuer"].map(display_name),
                                    crowd["value"].map(money), crowd["net_flow"])),
                hovertemplate="<b>%{x}</b> · %{customdata[0]}<br>%{y} funds · "
                              "%{customdata[1]} held<br>net flow %{customdata[2]:+d}"
                              "<extra></extra>"))
            fig.update_layout(**plotly_layout(height=300, showlegend=False))
            fig.update_yaxes(title_text="Funds holding", title_font=dict(size=11, color=MUTED))
            chart(fig, key="sm_crowd")
            st.caption("Bar colour: green = more funds buying than selling last quarter, "
                       "red = the reverse, grey = unchanged.")

        with card("One fund's book", icon_name="account_balance_wallet"):
            funds = sorted(ch["fund"].dropna().unique().tolist())
            fund = st.selectbox("Fund", funds, key="sm_fund", width=420,
                                label_visibility="collapsed")
            fb = ch[ch["fund"] == fund].copy()
            fb["status_b"] = fb["status"].map(lambda s: [str(s).title()])
            fb["issuer"] = fb["issuer"].map(display_name)
            fb = fb.sort_values("value1", ascending=False)
            p1 = pd.to_datetime(fb["period"]).max()
            p0 = pd.to_datetime(fb["prev_period"]).max()
            st.caption(f"Quarter to {p1:%b %d, %Y}"
                       + (f" vs {p0:%b %d, %Y}" if pd.notna(p0) else " (first quarter on file)")
                       + f" · {int((fb['shares1'] > 0).sum())} positions · "
                         f"{money(fb['value1'].sum())} reported")
            st.dataframe(
                fb[["ticker", "issuer", "status_b", "shares1", "pct_change", "value1"]],
                hide_index=True, height=420,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker", width=70),
                    "issuer": st.column_config.TextColumn("Issuer", width="medium"),
                    "status_b": st.column_config.MultiselectColumn(
                        "Change", options=STATUS, color=STATUS_COLORS, width=95),
                    "shares1": st.column_config.NumberColumn("Shares", format="compact"),
                    "pct_change": st.column_config.NumberColumn(
                        "Share change", format="percent"),
                    "value1": st.column_config.NumberColumn("Value", format="compact"),
                })
        st.caption("13F reports long equity positions only (no shorts, no cash) as of quarter "
                   "end and lands up to 45 days later — treat it as confirmation of where "
                   "informed capital sits, not a timing signal on its own.")

# ------------------------------------------------------------------ short volume
with tab_short:
    if sf.empty:
        empty_state("No short-volume data yet",
                    "FINRA Reg SHO daily files are pulled on the daily full refresh.",
                    "trending_down")
    else:
        v = sf.sort_values("delta", ascending=False).copy()
        with card("Short share of daily volume", icon_name="trending_down",
                  meta="FINRA consolidated NMS files · 5 vs 20 sessions"):
            top = v.head(30).iloc[::-1]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=top["ratio_20d"], y=top["ticker"], orientation="h",
                                 name="20-day", marker=dict(color="#3A4557"),
                                 hovertemplate="%{y} 20-day: %{x:.0%}<extra></extra>"))
            fig.add_trace(go.Scatter(x=top["ratio_5d"], y=top["ticker"], mode="markers",
                                     name="Last 5 days",
                                     marker=dict(size=9, color=[
                                         NEG if d >= 0.08 else WARN if d > 0 else POS
                                         for d in top["delta"]]),
                                     hovertemplate="%{y} 5-day: %{x:.0%}<extra></extra>"))
            fig.update_layout(**plotly_layout(height=max(300, 18 * len(top) + 60),
                                              barmode="overlay"))
            fig.update_xaxes(tickformat=".0%", range=[0, 1])
            fig.update_yaxes(showgrid=False, tickfont=dict(size=11))
            chart(fig, key="sm_short")
            st.caption("Dots: this week's short share of volume (red = jumped 8+ points vs "
                       "the 20-day bar). Around 40-50% is normal market-making; a sudden, "
                       "sustained jump is what matters.")
        st.dataframe(v, hide_index=True, column_config={
            "ticker": st.column_config.TextColumn("Ticker", width=70),
            "ratio_5d": st.column_config.ProgressColumn("Short share · 5 days", format="percent",
                                                        min_value=0.0, max_value=1.0),
            "ratio_20d": st.column_config.NumberColumn("20 days", format="percent"),
            "delta": st.column_config.NumberColumn("Change", format="percent"),
            "days": st.column_config.NumberColumn("Sessions on file", width=90)})

# ------------------------------------------------------------------ options
with tab_opt:
    if opt.empty:
        empty_state("No options snapshots yet",
                    "Chains for the watchlist, the top focus names and names with a binary "
                    "catalyst ahead are pulled on the daily full refresh.", "stacked_line_chart")
    else:
        o = opt.copy()
        for c in ("implied_move", "atm_iv", "pc_volume_ratio", "pc_oi_ratio", "vol_oi_ratio"):
            o[c] = pd.to_numeric(o[c], errors="coerce")
        with card("Options positioning", icon_name="stacked_line_chart",
                  meta="Front expiry ≥ 5 days out"):
            st.dataframe(
                o.sort_values("vol_oi_ratio", ascending=False)[
                    ["ticker", "expiry", "days_to_expiry", "implied_move", "atm_iv", "iv_back",
                     "call_volume", "put_volume", "pc_volume_ratio", "pc_oi_ratio",
                     "vol_oi_ratio"]],
                hide_index=True, height=480,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker", width=70),
                    "expiry": st.column_config.DateColumn("Expiry", format="MMM D"),
                    "days_to_expiry": st.column_config.NumberColumn("Days", width=55),
                    "implied_move": st.column_config.NumberColumn(
                        "Implied move", format="percent",
                        help="ATM straddle ÷ spot: the move the market prices by expiry"),
                    "atm_iv": st.column_config.NumberColumn("ATM IV", format="percent"),
                    "iv_back": st.column_config.NumberColumn(
                        "Back IV", format="percent",
                        help="A front IV well above the back month prices an event before "
                             "the front expiry"),
                    "call_volume": st.column_config.NumberColumn("Call vol", format="compact"),
                    "put_volume": st.column_config.NumberColumn("Put vol", format="compact"),
                    "pc_volume_ratio": st.column_config.NumberColumn("P/C vol", format="%.2f"),
                    "pc_oi_ratio": st.column_config.NumberColumn("P/C OI", format="%.2f"),
                    "vol_oi_ratio": st.column_config.NumberColumn(
                        "Vol / OI", format="%.2f",
                        help="Today's volume ÷ open interest - above 1.5 is fresh positioning"),
                })
        st.caption("Snapshot from Yahoo Finance chains (delayed). Implied move shows what a "
                   "catalyst is priced for; unusual call or put volume feeds the signal engine.")

# ------------------------------------------------------------------ whole market + filings
from _shared import q  # noqa: E402

wm = q("SELECT ticker, period, holders, holders_prev, new_holders, exited_holders, value "
       "FROM inst_ownership WHERE period = (SELECT MAX(period) FROM inst_ownership)")
d13 = q("SELECT ticker, form, filed_date, url FROM filings WHERE (form LIKE 'SC 13%' OR form "
        "LIKE 'SCHEDULE 13%') AND filed_date >= :c ORDER BY filed_date DESC LIMIT 60",
        {"c": (pd.Timestamp.today() - pd.Timedelta(days=45)).strftime("%Y-%m-%d")})
c_wm, c_13 = st.columns(2, gap="medium")
with c_wm:
    with card("All 13F filers - biggest changes", icon_name="groups",
              meta="SEC Form 13F data sets · holders per name vs the prior quarter"):
        if wm.empty:
            st.caption("Loads from the SEC's quarterly 13F data sets on the next full refresh.")
        else:
            wm["change"] = wm["holders"] - wm["holders_prev"]
            st.dataframe(wm.sort_values("change", ascending=False).head(25)[
                ["ticker", "holders", "change", "new_holders", "exited_holders", "value"]],
                hide_index=True, width="stretch", column_config={
                    "holders": "Holders", "change": st.column_config.NumberColumn(
                        "Δ holders", format="%+d"),
                    "new_holders": "New", "exited_holders": "Exited",
                    "value": st.column_config.NumberColumn("Value", format="compact")})
            st.caption(f"Quarter ending {pd.Timestamp(wm['period'].iloc[0]):%b %d, %Y}.")
with c_13:
    with card("Schedule 13D / 13G filings", icon_name="how_to_reg",
              meta="last 45 days · 13D = activist intent, 13G = passive 5%+"):
        if d13.empty:
            st.caption("None in the last 45 days.")
        else:
            st.dataframe(d13, hide_index=True, width="stretch", column_config={
                "ticker": "Ticker", "form": "Form",
                "filed_date": st.column_config.DateColumn("Filed", format="MMM D"),
                "url": st.column_config.LinkColumn("", display_text="Open")})

# ------------------------------------------------------------------ sector flows
from bioterm.ingest.etf import next_rebalance, rebalance_pressure  # noqa: E402

fl = q("SELECT date, nav, shares_out, aum, flow_est FROM etf_flows WHERE etf = 'XBI' "
       "ORDER BY date")
with card("XBI creations & redemptions", icon_name="swap_horiz",
          meta=f"daily Δ shares × NAV · next quarterly rebalance {next_rebalance():%b %d, %Y}"):
    if fl.empty:
        st.caption("Loads from SPDR's NAV history on the next full refresh.")
    else:
        fl["date"] = pd.to_datetime(fl["date"])
        fl = fl.tail(180)
        fl["flow_m"] = fl["flow_est"] / 1e6
        fig = go.Figure(go.Bar(x=fl["date"], y=fl["flow_m"],
                               marker_color=[POS if v >= 0 else NEG for v in fl["flow_m"]],
                               hovertemplate="%{x|%b %d}: %{y:+,.0f}M<extra></extra>"))
        fig.update_layout(**plotly_layout(height=220, bargap=0.15))
        chart(fig, key="xbi_flows")
        last = fl.iloc[-1]
        st.caption(f"AUM ${last['aum'] / 1e9:,.2f}B · 20-day net flow "
                   f"{fl['flow_est'].tail(20).sum() / 1e6:+,.0f}M")
    rp = rebalance_pressure()
    if not rp.empty:
        st.caption("Rebalance pressure - names furthest from XBI's equal weight (estimate; "
                   "the index also applies liquidity caps). Positive = the fund buys.")
        st.dataframe(rp[["ticker", "weight", "target", "drift", "trade_usd", "days_of_volume"]],
                     hide_index=True, width="stretch", column_config={
                         "weight": st.column_config.NumberColumn("Weight", format="percent"),
                         "target": st.column_config.NumberColumn("Equal weight",
                                                                 format="percent"),
                         "drift": st.column_config.NumberColumn("Drift", format="percent"),
                         "trade_usd": st.column_config.NumberColumn("Implied trade",
                                                                    format="compact"),
                         "days_of_volume": st.column_config.NumberColumn("Days of volume",
                                                                         format="%.1f")})
