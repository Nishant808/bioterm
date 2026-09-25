"""Stock detail - one name in depth: price + technicals, pipeline, catalysts,
news sentiment, insiders and filings."""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import _auth
import _live as live
from _shared import (catalysts_df, filings_df, fundamentals_row, insider_txns_df,
                     molecules_df, money, news_df, options_history, pct, q,
                     score_history, scores_df, sentiment_df, sentiment_series, short_flow,
                     short_series, signal_board, signal_history, signals_today, smart_money,
                     trials_df, universe_df)
from _ui import (ACCENT, BORDER_STRONG, CATALYST_TYPES, FAMILIES, GRID, MUTED, NEG,
                 PHASE_COLORS, POS, SMA_COLORS, WARN, card, catalyst_family, catalyst_label,
                 catalyst_title, chart, display_name, empty_state, esc, headline_rows,
                 kpi_row, kv_list, md_safe, page_header, phase_group, plotly_layout,
                 regime_word,
                 signal_badge, signal_rows, spark, tone_of)
from bioterm import store

CATALYST_KEYS = list(CATALYST_TYPES)
TYPE_LABELS = [v[0] for v in CATALYST_TYPES.values()]
TYPE_COLORS = [FAMILIES[catalyst_family(k)][2] for k in CATALYST_TYPES]

page_header("Stock detail",
            "Signals, price, pipeline, catalysts, news, insiders, funds and filings for one name")

uni = universe_df()
scores = scores_df()
if uni.empty:
    empty_state("No universe yet", "The universe builds on the first ingestion run.",
                "hourglass_top")
    st.stop()

# ------------------------------------------------------------------ selector
names = dict(zip(uni["ticker"], uni["name"]))
qs = st.query_params.get("ticker")
options = uni["ticker"].tolist()
default_ix = options.index(qs) if qs in options else (
    options.index(scores.iloc[0]["ticker"]) if not scores.empty else 0)
ticker = st.selectbox("Ticker", options, index=default_ix, label_visibility="collapsed",
                      format_func=lambda t: f"{t} · {display_name(names.get(t, ''))}",
                      width=420)
st.query_params["ticker"] = ticker

meta = uni[uni["ticker"] == ticker].iloc[0]
srow = scores[scores["ticker"] == ticker]
fund = fundamentals_row(ticker)
sig = sentiment_df(14).set_index("ticker")
sg = sig.loc[ticker].to_dict() if ticker in sig.index else {}
wl = next((w for w in store.get_watchlist() if str(w["ticker"]).upper() == ticker), None)
on_wl = wl is not None
rq = fund.get("runway_quarters")
rq_ok = rq is not None and not pd.isna(rq)

# ------------------------------------------------------------------ identity
board = signal_board()
brow = board[board["ticker"] == ticker]
call = brow.iloc[0].to_dict() if not brow.empty else None
badges = []
if call:
    badges.append(signal_badge(call["label"]))
if on_wl:
    badges.append(f"<span class='bt-badge blue'>On watchlist · conviction {int(wl['conviction'])}</span>")
if int(meta.get("in_xbi") or 0) == 1:
    badges.append("<span class='bt-badge'>XBI member</span>")
if rq_ok and rq < 4:
    badges.append("<span class='bt-badge red'>Short cash runway</span>")
_tier = meta.get("tier")
TIER = _tier if isinstance(_tier, str) and _tier else "core"      # NULL / NaN = core
if TIER != "core":
    badges.append("<span class='bt-badge'>Extended coverage</span>" if TIER == "extended"
                  else "<span class='bt-badge'>No longer covered</span>")
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    st.html(f"<div class='bt-hero'><span class='bt-hero-tk'>{esc(ticker)}</span>"
            f"<span class='bt-hero-name'>{esc(display_name(meta['name']))}</span>"
            f"{''.join(badges)}</div>")
    st.space("stretch")
    from bioterm import tearsheet as _ts

    st.download_button("Tear sheet", lambda: _ts.html_page(ticker),
                       f"{ticker}_tearsheet.html", "text/html", icon=":material/description:",
                       type="tertiary", help="Printable one-page summary (print to PDF)",
                       key="ts_html")
    st.download_button("Excel", lambda: _ts.xlsx(ticker), f"{ticker}_bioterm.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/table_view:", type="tertiary", key="ts_xlsx",
                       help="Every section as its own sheet")

if TIER == "extended":
    st.caption(f"Extended-tier name (SEC industry code {meta.get('sic') or '—'}): prices, "
               "fundamentals and filings are tracked; the Focus Score, signals, news and "
               "trial coverage start when you add it to the watchlist.")

# ------------------------------------------------------------------ KPIs
hist = score_history(ticker)
tone_w, _ = tone_of(sg.get("signal"))


@st.fragment(run_every=live.TTL)
def _live_price(tk: str) -> None:
    """Last trade from Yahoo, re-fetched every minute while the page is open."""
    qd = live.quote(tk)
    if not qd:
        st.metric("Last price", "–", border=True, help="No quote from Yahoo Finance")
        return
    chg, pc = qd.get("change"), qd.get("change_pct")
    st.metric("Last price", f"${qd['price']:,.2f}",
              delta=None if pc is None or pd.isna(pc) else f"{chg:+.2f} ({pc * 100:+.2f}%)",
              border=True, help=live.source_note(qd.get("source", "live"), qd.get("asof"),
                                                  qd.get("provider")))


with kpi_row(7, "hero"):
    _live_price(ticker)
    if not srow.empty:
        st.metric("Focus Score", f"{srow.iloc[0]['focus_score']:.3f}",
                  delta=f"Rank #{int(srow.iloc[0]['rank'])}", delta_color="off",
                  delta_arrow="off", border=True,
                  chart_data=spark(hist["focus_score"]) if len(hist) > 1 else None,
                  chart_type="area", help="Line: Focus Score across recent runs")
    st.metric("Market cap", money(fund.get("market_cap")), border=True)
    st.metric("Cash", money(fund.get("cash")), border=True)
    st.metric("Burn / year", money(fund.get("burn_ttm")), border=True)
    st.metric("Cash runway", f"{rq:.1f} quarters" if rq_ok else "–", border=True,
              help="Cash ÷ quarterly burn. Under 4 quarters raises the risk score.")
    st.metric("News · 14 days", f"{tone_w} {sg['signal']:+.2f}" if sg else "No data",
              delta=f"{int(sg['n'])} headlines" if sg else None, delta_color="off",
              delta_arrow="off", border=True)

# ------------------------------------------------------------------ your view
CAN = _auth.can_edit()
view_col, notes_col = st.columns(2, gap="medium")
with view_col:
    with card("Your view", icon_name="psychology",
              meta="Conviction multiplies the Focus Score"):
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            conv = st.segmented_control(
                "Conviction", [1, 2, 3, 4, 5], default=int(wl["conviction"]) if on_wl else 3,
                required=True, help="Your read on whether the science works — 1 is "
                                    "skeptical, 5 is high conviction")
            st.space("stretch")
            if st.button("Update conviction" if on_wl else "Add to watchlist",
                         icon=":material/check:" if on_wl else ":material/bookmark_add:",
                         type="primary", disabled=not CAN):
                store.add_to_watchlist(ticker, conv, wl.get("thesis", "") if on_wl else "")
                st.cache_data.clear()
                st.rerun()
            if on_wl and st.button("Remove", icon=":material/bookmark_remove:",
                                   type="tertiary", disabled=not CAN):
                store.remove_from_watchlist(ticker)
                st.cache_data.clear()
                st.rerun()
        if on_wl:
            thesis = st.text_input("Thesis", value=wl.get("thesis", ""), key=f"th_{ticker}",
                                   placeholder="Why you're watching this", disabled=not CAN)
            if CAN and thesis != wl.get("thesis", ""):
                store.add_to_watchlist(ticker, conv, thesis)
                st.cache_data.clear()
            if wl.get("molecules"):
                st.caption("Tracking: " + " · ".join(wl["molecules"]))
        else:
            st.caption("Add this name to your watchlist to record a thesis and have your "
                       "conviction weight its score.")

with notes_col:
    with card("Research notes", icon_name="edit_note", meta="Visible to the owner only"):
        if _auth.guard("read and write research notes", key="notes"):
            note = st.text_area("Notes", value=store.get_note(ticker), height=96,
                                label_visibility="collapsed", key=f"note_{ticker}",
                                placeholder="Mechanism, trial design, competitive read…")
            if st.button("Save note", key=f"sn_{ticker}", icon=":material/save:"):
                store.set_note(ticker, note)
                st.cache_data.clear()
                st.toast("Note saved", icon=":material/check_circle:")

# ------------------------------------------------------------------ tabs
_TABS = [":material/swap_vert: Signals", ":material/candlestick_chart: Price & technicals",
         ":material/biotech: Pipeline", ":material/event: Catalysts",
         ":material/newspaper: News & sentiment", ":material/groups: Insiders",
         ":material/account_balance: Funds & flow", ":material/savings: Balance sheet",
         ":material/description: SEC filings"]
(tab_sig, tab_px, tab_pipe, tab_cat, tab_news, tab_ins, tab_flow, tab_bs,
 tab_fil) = st.tabs(_TABS, default=next((t for t in _TABS
                                          if t.endswith(st.query_params.get("tab", "\0"))),
                                         None))

# ---- signals
with tab_sig:
    if call is None:
        empty_state("No signal call yet",
                    "The signal engine runs after every refresh once prices have landed.",
                    "swap_vert")
    else:
        r_word, _, r_tip = regime_word(call.get("regime"))
        was = call.get("prev_label")
        with kpi_row(4, "sig"):
            st.metric("Call", str(call["label"]).title(),
                      delta=f"was {str(was).title()}" if isinstance(was, str) and was != call["label"]
                      else "unchanged since last run" if isinstance(was, str) else "first call",
                      delta_color="off", delta_arrow="off", border=True)
            sh = signal_history(ticker)
            st.metric("Net signal", f"{call['net']:+.2f}", delta="bull − bear, −1 to +1",
                      delta_color="off", delta_arrow="off", border=True,
                      chart_data=spark(sh["net"]) if len(sh) > 1 else None, chart_type="line")
            st.metric("Bull / bear", f"{call['bull']:.2f} / {call['bear']:.2f}",
                      delta=f"{int(call['n_buy'])} buy · {int(call['n_sell'])} sell detectors",
                      delta_color="off", delta_arrow="off", border=True)
            st.metric("Sector regime", r_word, delta="XBI trend filter", delta_color="off",
                      delta_arrow="off", border=True, help=r_tip)
        ev = signals_today()
        ev = ev[ev["ticker"] == ticker].sort_values(["side", "strength"], ascending=[True, False])
        if ev.empty:
            empty_state("Nothing firing", "No detector fires for this name on the latest run.",
                        "sensors_off")
        else:
            signal_rows(ev, show_ticker=False)
        st.page_link("app_pages/signals.py", label="Signal board and method",
                     icon=":material/arrow_forward:", query_params={"ticker": ticker})

# ---- price
with tab_px:
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        win = st.segmented_control("Window", ["1D", "5D", "6M", "1Y", "2Y", "5Y"],
                                   default="1Y", required=True, label_visibility="collapsed",
                                   key="px_win")
        st.space("stretch")
        style = st.segmented_control("Chart", ["Pro", "Classic"], default="Pro", required=True,
                                     label_visibility="collapsed", key="px_style",
                                     help="Pro: TradingView Lightweight Charts - scroll to "
                                          "zoom, drag to pan. Classic: Plotly")
    intraday = win in ("1D", "5D")
    # always Yahoo, never the ingested table (that only feeds the engines); the
    # daily history also drives the indicator KPIs whatever window is shown
    daily, px_src = live.history(ticker, "5y" if win in ("2Y", "5Y") else "2y")
    tech = live.indicators(daily)
    if intraday:
        pxdf, px_src = live.history(ticker, {"1D": "1d", "5D": "5d"}[win],
                                    {"1D": "5m", "5D": "15m"}[win])
    else:
        pxdf = daily
    if pxdf.empty:
        empty_state("No price history",
                    "Yahoo Finance returned nothing for this ticker"
                    + (" (intraday bars need the live feed)." if intraday else "."),
                    "show_chart")
    else:
        days = {"6M": 126, "1Y": 252, "2Y": 504, "5Y": 1260}.get(win)
        p = pxdf.tail(days) if days else pxdf
        t = tech[tech["date"] >= p["date"].min()] if not intraday else tech.iloc[0:0]

        if style == "Pro":
            import _charts

            pro = p.merge(t[["date", "sma20", "sma50", "sma200", "rsi14"]], on="date",
                          how="left") if not t.empty else p
            _cat = catalysts_df()
            _cat = _cat[(_cat["ticker"] == ticker) & (_cat["date"] >= p["date"].min())] \
                if not intraday else _cat.iloc[0:0]
            marks = [] if intraday else _charts.signal_markers(
                signal_history(ticker),
                _cat[_cat["date"] <= p["date"].max()])
            _charts.pro_chart(pro, intraday=intraday, markers=marks, height=560,
                              show_rsi=not intraday)
        else:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                                row_heights=[0.62, 0.16, 0.22], vertical_spacing=0.035)
            fig.add_trace(go.Candlestick(
                x=p["date"], open=p["open"], high=p["high"], low=p["low"], close=p["close"],
                name="Price", showlegend=False,
                increasing=dict(line=dict(color=POS, width=1), fillcolor=POS),
                decreasing=dict(line=dict(color=NEG, width=1), fillcolor=NEG)), row=1, col=1)
            if not t.empty:
                for col, color in SMA_COLORS.items():
                    if col in t and t[col].notna().any():
                        fig.add_trace(go.Scatter(
                            x=t["date"], y=t[col], name=f"SMA {col[3:]}", mode="lines",
                            line=dict(width=1.5, color=color),
                            hovertemplate="%{y:.2f}"), row=1, col=1)
            up = p["close"] >= p["open"]
            fig.add_trace(go.Bar(
                x=p["date"], y=p["volume"], name="Volume", showlegend=False,
                marker=dict(color=["rgba(63,185,107,.38)" if u else "rgba(229,72,77,.38)"
                                   for u in up]),
                hovertemplate="%{y:,.0f}"), row=2, col=1)
            if not t.empty and "rsi14" in t:
                fig.add_hrect(y0=30, y1=70, fillcolor="rgba(255,255,255,.025)", line_width=0,
                              row=3, col=1)
                for lvl in (30, 70):
                    fig.add_hline(y=lvl, line=dict(color=BORDER_STRONG, width=1), row=3, col=1)
                fig.add_trace(go.Scatter(x=t["date"], y=t["rsi14"], name="RSI 14", mode="lines",
                                         line=dict(color=ACCENT, width=1.5),
                                         hovertemplate="%{y:.0f}"), row=3, col=1)

            # Catalysts inside the window plus the next 60 days - far-future dates
            # would stretch the time axis and squeeze the price history (they're all
            # listed on the Catalysts tab).
            last_d = p["date"].max()
            ahead = pd.Timedelta(days=60)
            cat = catalysts_df()
            cat = cat[(cat["ticker"] == ticker) & (cat["date"] >= p["date"].min())
                      & (cat["date"] <= last_d + ahead)] if not intraday else cat.iloc[0:0]
            x_end = last_d + (ahead if (cat["date"] > last_d).any() else pd.Timedelta(days=3))
            if not cat.empty:
                for d in cat["date"].unique():
                    fig.add_vline(x=d, line=dict(color="rgba(224,163,62,.35)", width=1),
                                  row=1, col=1)
                top_y = float(p["high"].max()) * 1.035
                fig.add_trace(go.Scatter(
                    x=cat["date"], y=[top_y] * len(cat), mode="markers", name="Catalyst",
                    marker=dict(symbol="triangle-down", size=10, color=WARN,
                                line=dict(color="#0B0E14", width=1.5)),
                    customdata=list(zip(cat["type"].map(catalyst_label),
                                        cat["title"].map(lambda s: catalyst_title(s)[:90]))),
                    hovertemplate="<b>%{customdata[0]}</b><br>%{x|%b %d, %Y}<br>"
                                  "%{customdata[1]}<extra></extra>"), row=1, col=1)

            fig.update_layout(**plotly_layout(
                height=560, hovermode="x unified", xaxis_rangeslider_visible=False,
                legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0,
                            bgcolor="rgba(0,0,0,0)", font=dict(size=11))))
            breaks = [dict(bounds=["sat", "mon"])]
            if intraday:
                breaks.append(dict(bounds=[16, 9.5], pattern="hour"))   # overnight gaps
            fig.update_xaxes(range=[p["date"].min(), x_end if not intraday else p["date"].max()],
                             rangebreaks=breaks, showgrid=False,
                             showspikes=True, spikemode="across", spikesnap="cursor",
                             spikecolor=BORDER_STRONG, spikethickness=1, spikedash="solid")
            fig.update_yaxes(gridcolor=GRID, zeroline=False)
            fig.update_yaxes(title_text="Price", title_font=dict(size=11, color=MUTED), row=1, col=1)
            fig.update_yaxes(title_text="Volume", title_font=dict(size=11, color=MUTED),
                             showticklabels=False, row=2, col=1)
            fig.update_yaxes(title_text="RSI", title_font=dict(size=11, color=MUTED),
                             range=[0, 100], tickvals=[30, 70], row=3, col=1)
            chart(fig, key="price")

        if not tech.empty:
            last = tech.iloc[-1]
            with kpi_row(4, "tech"):
                st.metric("Return 1 month", pct(last.get("ret_1m")),
                          delta=f"3M {pct(last.get('ret_3m'))} · 6M {pct(last.get('ret_6m'))}",
                          delta_color="off", delta_arrow="off", border=True)
                rsi = last.get("rsi14")
                st.metric("RSI (14)", "–" if rsi is None or pd.isna(rsi) else f"{rsi:.0f}",
                          delta=None if rsi is None or pd.isna(rsi) else
                          ("Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"),
                          delta_color="off", delta_arrow="off", border=True)
                vz = last.get("vol_z20")
                st.metric("Volume z-score (20 days)",
                          "–" if vz is None or pd.isna(vz) else f"{vz:+.2f}", border=True)
                st.metric("Position in 52-week range",
                          f"{(last.get('pct_52w_range') or 0) * 100:.0f}%", border=True)
        st.caption(live.source_note(px_src, p["date"].iloc[-1] if intraday else None)
                   + (" · Amber markers are dated catalysts in this window and the next "
                      "60 days — every catalyst is on the Catalysts tab." if not intraday
                      else " · 5-minute bars" if win == "1D" else " · 15-minute bars"))

# ---- pipeline
with tab_pipe:
    mm = molecules_df()
    mm = mm[mm["ticker"] == ticker] if not mm.empty else mm
    if not mm.empty:
        with card("Tracked molecules", icon_name="science", meta="Linked by name and NCT ID"):
            st.dataframe(
                mm.assign(next_readout=mm["next_readout"])[
                    ["name", "aliases", "top_phase", "n_active", "n_trials", "next_readout",
                     "n_news_30d", "papers_total"]],
                hide_index=True, column_config={
                    "name": st.column_config.TextColumn("Molecule"),
                    "aliases": st.column_config.ListColumn("Also known as"),
                    "top_phase": st.column_config.TextColumn("Top phase", width=80),
                    "n_active": st.column_config.NumberColumn("Active trials", width=90),
                    "n_trials": st.column_config.NumberColumn("All trials", width=80),
                    "next_readout": st.column_config.DateColumn("Next readout",
                                                                format="MMM D, YYYY"),
                    "n_news_30d": st.column_config.NumberColumn("News 30d", width=75),
                    "papers_total": st.column_config.NumberColumn("Papers", width=70)})
            st.page_link("app_pages/molecules.py", label="Molecule dossiers",
                         icon=":material/arrow_forward:")
    tr = trials_df(ticker)
    if tr.empty:
        empty_state("No trials found",
                    "No lead-sponsored interventional trials on ClinicalTrials.gov.", "biotech")
    else:
        active = tr[tr["status"].isin(["RECRUITING", "ACTIVE_NOT_RECRUITING",
                                        "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"])]
        tr = tr.assign(group=tr["phase"].map(phase_group))
        upcoming = tr[tr["primary_completion_date"] >= pd.Timestamp.today()]
        nxt = upcoming["primary_completion_date"].min() if not upcoming.empty else None
        with kpi_row(4, "pipe"):
            st.metric("Active trials", len(active), delta=f"{len(tr)} tracked",
                      delta_color="off", delta_arrow="off", border=True)
            st.metric("Phase 3", int((tr["group"] == "Phase 3").sum()), border=True)
            st.metric("Phase 2", int((tr["group"] == "Phase 2").sum()), border=True)
            st.metric("Next primary completion",
                      nxt.strftime("%b %d, %Y") if nxt is not None and pd.notna(nxt) else "–",
                      border=True)

        gantt = tr.dropna(subset=["primary_completion_date", "start_date"]).copy()
        if not gantt.empty:
            gantt = gantt.sort_values("primary_completion_date").tail(25)
            gantt["label"] = gantt["title"].str.slice(0, 60)
            fig = px.timeline(gantt, x_start="start_date", x_end="primary_completion_date",
                              y="label", color="group", color_discrete_map=PHASE_COLORS,
                              category_orders={"group": ["Phase 1", "Phase 2", "Phase 3",
                                                         "Other"]},
                              hover_data={"nct_id": True, "phase": True, "status": True,
                                          "enrollment": True, "group": False, "label": False})
            fig.update_traces(marker_line_width=0, opacity=0.95)
            fig.add_vline(x=pd.Timestamp.today(), line=dict(color=MUTED, width=1))
            fig.update_yaxes(autorange="reversed", title=None, showgrid=False,
                             tickfont=dict(size=11))
            fig.update_xaxes(showgrid=True, gridcolor=GRID)
            fig.update_layout(**plotly_layout(
                height=min(640, 110 + 26 * len(gantt)), legend_title_text=""))
            st.caption("Start → primary completion for the 25 trials finishing soonest. "
                       "The vertical line is today.")
            chart(fig, key="gantt")

        from bioterm.process.pos import area_of, loa

        tr = tr.assign(area=tr["conditions"].map(area_of),
                       pos=[loa(p, c) for p, c in zip(tr["phase"], tr["conditions"])])
        st.dataframe(
            tr[["url", "phase", "pos", "status", "title", "conditions", "interventions",
                "primary_completion_date", "enrollment", "last_update_post_date"]]
            .sort_values("primary_completion_date"),
            hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("Trial", display_text=r"(NCT\d+)",
                                                   width=110),
                "phase": st.column_config.TextColumn("Phase", width=70),
                "pos": st.column_config.ProgressColumn(
                    "Approval prior", min_value=0, max_value=1, format="percent", width=110,
                    help="Historical likelihood of approval from this phase in this disease "
                         "area (BIO/Informa/QLS 2011-2020) - a base rate, not a forecast"),
                "status": st.column_config.TextColumn("Status", width=150),
                "title": st.column_config.TextColumn("Title", width="large"),
                "conditions": st.column_config.TextColumn("Conditions"),
                "interventions": st.column_config.TextColumn("Interventions"),
                "primary_completion_date": st.column_config.DateColumn(
                    "Primary completion", format="MMM D, YYYY"),
                "enrollment": st.column_config.NumberColumn("Enrollment", format="%d"),
                "last_update_post_date": st.column_config.DateColumn(
                    "Last update", format="MMM D, YYYY"),
            })

    ch = q("SELECT detected_at, nct_id, kind, old, new FROM trial_changes WHERE ticker = :t "
           "ORDER BY detected_at DESC LIMIT 20", {"t": ticker})
    if not ch.empty:
        with card("Trial change radar", icon_name="radar",
                  meta="what moved on ClinicalTrials.gov between refreshes"):
            st.dataframe(ch.assign(kind=ch["kind"].str.replace("_", " ")), hide_index=True,
                         width="stretch", column_config={
                             "detected_at": st.column_config.DatetimeColumn(
                                 "Detected", format="MMM D, YYYY"),
                             "nct_id": "Trial", "kind": "Change", "old": "From", "new": "To"})

    from bioterm.process.landscape import peers as _peers, universe_conditions

    _conds = universe_conditions()
    pr = _peers(ticker, _conds)
    mine = sorted(set(_conds[_conds["ticker"] == ticker]["condition"]))[:30]
    lt = q("SELECT condition, sponsor, sponsor_ticker, phase, status, primary_completion_date, "
           "nct_id, title FROM landscape_trials WHERE condition IN "
           f"({','.join(f':c{i}' for i in range(len(mine)))}) "
           "ORDER BY primary_completion_date LIMIT 300",
           {f"c{i}": c for i, c in enumerate(mine)}) if mine else pd.DataFrame()
    if pr or not lt.empty:
        with card("Competitive landscape", icon_name="hub",
                  meta="other Phase 2/3 programmes in the same indications"):
            if pr:
                st.caption("Universe names in the same indications (a peer's readout "
                           "reprices these - read-through alerts watch for it):")
                st.markdown(" · ".join(f"**{t}** ({', '.join(c[:2])})"
                                       for t, c in list(pr.items())[:12]))
            if not lt.empty:
                st.dataframe(lt.drop_duplicates("nct_id").head(60), hide_index=True,
                             width="stretch", column_config={
                                 "condition": "Indication", "sponsor": "Sponsor",
                                 "sponsor_ticker": "Ticker", "phase": "Phase",
                                 "status": "Status",
                                 "primary_completion_date": st.column_config.DateColumn(
                                     "Primary completion", format="MMM YYYY"),
                                 "nct_id": "Trial", "title": st.column_config.TextColumn(
                                     "Title", width="large")})

# ---- catalysts
with tab_cat:
    cat = catalysts_df()
    cat = cat[cat["ticker"] == ticker].sort_values("date")
    if cat.empty:
        empty_state("No dated catalysts yet", "Pin one you know about below.", "event_busy")
    else:
        view = cat.assign(type_badge=cat["type"].map(lambda t: [catalyst_label(t)]),
                          title=cat["title"].map(catalyst_title))
        st.dataframe(
            view[["date", "type_badge", "title", "months_away", "confidence", "source", "url"]],
            hide_index=True,
            column_config={
                "date": st.column_config.DateColumn("Date", format="MMM D, YYYY", width=110),
                "type_badge": st.column_config.MultiselectColumn(
                    "Type", options=TYPE_LABELS, color=TYPE_COLORS, width=160),
                "title": st.column_config.TextColumn("Detail", width="large"),
                "months_away": st.column_config.NumberColumn("Months away", format="%.1f"),
                "confidence": st.column_config.TextColumn("Confidence"),
                "source": st.column_config.TextColumn("Source"),
                "url": st.column_config.LinkColumn("Link", display_text="Open"),
            })

    past = q("SELECT event_date, kind, direction, ret_pre60, ret_1d, ret_21d, title, url "
             "FROM catalyst_events WHERE ticker = :t AND ret_1d IS NOT NULL "
             "ORDER BY event_date DESC LIMIT 30", {"t": ticker})
    try:
        from bioterm.process.outcomes import implied_vs_realized

        ivr = implied_vs_realized(120)
        ivr = ivr[ivr["ticker"] == ticker] if not ivr.empty else ivr
    except Exception:  # noqa: BLE001
        ivr = pd.DataFrame()
    if not ivr.empty and ivr["implied_move"].notna().any():
        with card("Options-implied vs historical moves", icon_name="compare_arrows",
                  meta="implied = ATM straddle to expiry (or back-month IV scaled to the date)"):
            st.dataframe(ivr[["date", "type", "implied_move", "own_median_move", "own_events",
                              "peer_median_move", "peer_events"]], hide_index=True,
                         width="stretch", column_config={
                             "date": st.column_config.DateColumn("Event", format="MMM D"),
                             "type": "Type",
                             "implied_move": st.column_config.NumberColumn(
                                 "Implied ±", format="percent"),
                             "own_median_move": st.column_config.NumberColumn(
                                 "This name's past |move|", format="percent"),
                             "own_events": "n",
                             "peer_median_move": st.column_config.NumberColumn(
                                 "Same-size peers |move|", format="percent"),
                             "peer_events": "n (peers)"})
    if not past.empty:
        with card("Past catalysts and how the stock reacted", icon_name="history",
                  meta="reaction = 2-session move; run-up = 60 sessions before"):
            st.dataframe(past, hide_index=True, width="stretch", column_config={
                "event_date": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
                "kind": "Event", "direction": "Read",
                "ret_pre60": st.column_config.NumberColumn("Run-up", format="percent"),
                "ret_1d": st.column_config.NumberColumn("Reaction", format="percent"),
                "ret_21d": st.column_config.NumberColumn("1 month after", format="percent"),
                "title": st.column_config.TextColumn("Detail", width="large"),
                "url": st.column_config.LinkColumn("Source", display_text="Open")})

    with st.expander("Pin a catalyst you know about", icon=":material/push_pin:",
                     expanded=cat.empty):
        with st.form(f"addcat_{ticker}", clear_on_submit=True, border=False):
            with st.container(horizontal=True, gap="small"):
                c_type = st.selectbox("Type", CATALYST_KEYS, format_func=catalyst_label)
                c_date = st.date_input("Date")
                c_conf = st.segmented_control("Confidence", ["low", "medium", "high"],
                                              default="medium", required=True)
            c_title = st.text_input("What happens", placeholder="e.g. FDA decision on ___ sNDA")
            c_url = st.text_input("Source link (optional)")
            if st.form_submit_button("Add catalyst", type="primary", disabled=not CAN,
                                     icon=":material/add:") and c_title and CAN:
                store.add_manual_catalyst(ticker, c_type, c_date, c_title, c_conf, c_url)
                st.cache_data.clear()
                st.rerun()

    manual = [c for c in store.get_manual_catalysts()
              if str(c.get("ticker", "")).upper() == ticker]
    if manual:
        st.caption("Pinned by you")
        for c in manual:
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(f"**{c['date']}** · {catalyst_label(c['type'])} · "
                            f"{md_safe(c['title'])} "
                            f":gray[({c['confidence']})]")
                st.space("stretch")
                if st.button("Delete", key=f"dc_{c['id']}", icon=":material/delete:",
                             type="tertiary", disabled=not CAN):
                    store.delete_manual_catalyst(c["id"])
                    st.cache_data.clear()
                    st.rerun()

# ---- news & sentiment
with tab_news:
    ser = sentiment_series(ticker, 60)
    with kpi_row(3, "news"):
        st.metric("Signal · 14 days", f"{sg.get('signal', 0):+.2f}" if sg else "–",
                  delta=tone_w if sg else None, delta_color="off", delta_arrow="off",
                  border=True)
        st.metric("Headlines · 14 days", int(sg["n"]) if sg else 0, border=True)
        st.metric("Event tilt", f"{sg.get('tilt', 0):+.1f}" if sg else "–",
                  delta=f"{sg.get('pos', 0)} positive · {sg.get('neg', 0)} negative"
                  if sg else None, delta_color="off", delta_arrow="off", border=True)
    if not ser.empty and len(ser) > 1:
        # Two measures on two scales -> two stacked panels sharing time, never
        # one plot with two y-axes.
        f = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38],
                          vertical_spacing=0.06)
        f.add_hline(y=0, line=dict(color=BORDER_STRONG, width=1), row=1, col=1)
        f.add_trace(go.Scatter(x=ser["day"], y=ser["sent_7d"], name="Tone, 7-day average",
                               mode="lines", line=dict(color=ACCENT, width=2),
                               fill="tozeroy", fillcolor="rgba(91,157,255,.08)",
                               hovertemplate="%{y:+.2f}"), row=1, col=1)
        f.add_trace(go.Bar(x=ser["day"], y=ser["n"], name="Headlines per day",
                           marker=dict(color="#3A4557"), hovertemplate="%{y}"),
                    row=2, col=1)
        f.update_layout(**plotly_layout(height=300, hovermode="x unified", showlegend=False))
        f.update_yaxes(range=[-1, 1], tickvals=[-1, 0, 1], title_text="Tone",
                       title_font=dict(size=11, color=MUTED), row=1, col=1)
        f.update_yaxes(title_text="Headlines", title_font=dict(size=11, color=MUTED),
                       row=2, col=1)
        st.caption("Headline tone (7-day average, −1 to +1) and headline count, last 60 days")
        chart(f, key="sentiment")

    nw = news_df(3000)
    nw = nw[nw["tickers_csv"].fillna("").str.contains(rf"\b{ticker}\b")]
    nw = nw.sort_values("published", ascending=False).head(60)
    if nw.empty:
        empty_state("No recent news matched", "", "newspaper")
    else:
        headline_rows(nw)

# ---- insiders
with tab_ins:
    it = insider_txns_df(ticker)
    if it.empty:
        empty_state("No Form 4 activity pulled",
                    "Insider filings are fetched for the watchlist and the top 60 focus "
                    "names on each full refresh.", "groups")
    else:
        buys, sells = it[it["code"] == "P"], it[it["code"] == "S"]
        w90 = pd.Timestamp.today() - pd.Timedelta(days=90)
        b90 = buys[buys["txn_date"] >= w90]["value"].sum()
        s90 = -sells[sells["txn_date"] >= w90]["value"].sum()
        with kpi_row(3, "insiders"):
            st.metric("Open-market buys · 90 days", money(b90) if b90 else "–",
                      delta=f"{buys[buys['txn_date'] >= w90]['owner'].nunique()} insiders",
                      delta_color="off", delta_arrow="off", border=True)
            st.metric("Open-market sells · 90 days", money(s90) if s90 else "–", border=True)
            st.metric("Net · 90 days", money(b90 - s90), border=True,
                      delta="Net buying" if b90 - s90 > 0 else
                      "Net selling" if b90 - s90 < 0 else None,
                      delta_color="normal" if b90 - s90 >= 0 else "inverse",
                      delta_arrow="off")
        st.caption("Codes — P open-market buy · S sale · M option exercise · F tax withholding "
                   "· A award · G gift")
        st.dataframe(
            it[["txn_date", "owner", "role", "code", "acquired_disposed", "shares",
                "price", "value", "url"]].head(80),
            hide_index=True,
            column_config={
                "txn_date": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
                "owner": st.column_config.TextColumn("Insider"),
                "role": st.column_config.TextColumn("Role"),
                "code": st.column_config.TextColumn("Code", width=60),
                "acquired_disposed": st.column_config.TextColumn("A/D", width=50),
                "value": st.column_config.NumberColumn("Value", format="$%,.0f"),
                "price": st.column_config.NumberColumn("Price", format="$%.2f"),
                "shares": st.column_config.NumberColumn("Shares", format="%,d"),
                "url": st.column_config.LinkColumn("Form 4", display_text="Open")})

# ---- funds & flow
with tab_flow:
    ch, summ = smart_money()
    mine = ch[ch["ticker"] == ticker] if not ch.empty else ch
    sf = short_flow()
    srow_sf = sf[sf["ticker"] == ticker] if not sf.empty else sf
    oh = options_history(ticker)
    with kpi_row(4, "flow"):
        holders = int((mine["shares1"] > 0).sum()) if not mine.empty else 0
        buying = int(mine["status"].isin(["new", "added"]).sum()) if not mine.empty else 0
        selling = int(mine["status"].isin(["trimmed", "exited"]).sum()) if not mine.empty else 0
        st.metric("Specialist funds holding", holders,
                  delta=f"{buying} buying · {selling} selling last quarter", delta_color="off",
                  delta_arrow="off", border=True)
        inst = fund.get("held_pct_institutions")
        st.metric("Institutional ownership",
                  "–" if inst is None or pd.isna(inst) else f"{float(inst) * 100:.0f}%",
                  delta=None if fund.get("held_pct_insiders") is None
                  or pd.isna(fund.get("held_pct_insiders"))
                  else f"insiders {float(fund['held_pct_insiders']) * 100:.1f}%",
                  delta_color="off", delta_arrow="off", border=True)
        spf = fund.get("short_percent_float")
        st.metric("Short interest",
                  "–" if spf is None or pd.isna(spf) else f"{float(spf) * 100:.1f}% of float",
                  delta=None if srow_sf.empty else
                  f"short volume {srow_sf.iloc[0]['ratio_5d'] * 100:.0f}% (5d) vs "
                  f"{srow_sf.iloc[0]['ratio_20d'] * 100:.0f}% (20d)",
                  delta_color="off", delta_arrow="off", border=True,
                  help=None if fund.get("short_ratio") is None or pd.isna(fund.get("short_ratio"))
                  else f"Days to cover: {float(fund['short_ratio']):.1f}")
        o = oh.iloc[-1] if not oh.empty else None
        st.metric("Options-implied move",
                  "–" if o is None or pd.isna(o.get("implied_move"))
                  else f"±{float(o['implied_move']) * 100:.0f}%",
                  delta=None if o is None or pd.isna(pd.to_datetime(o.get("expiry"),
                                                                    errors="coerce"))
                  else f"by {pd.to_datetime(o['expiry']):%b %d} · put/call "
                       f"{'–' if pd.isna(o.get('pc_volume_ratio')) else format(float(o['pc_volume_ratio']), '.2f')}",
                  delta_color="off", delta_arrow="off", border=True,
                  help="At-the-money straddle ÷ spot for the front expiry")
    fcol, scol = st.columns(2, gap="medium")
    with fcol:
        with card("Specialist funds (13F)", icon_name="account_balance"):
            if mine.empty:
                empty_state("No tracked specialist fund reports this name", "",
                            "account_balance")
            else:
                mv = mine.assign(status_b=mine["status"].map(lambda x: [str(x).title()]))
                st.dataframe(
                    mv.sort_values("value1", ascending=False)[
                        ["fund", "status_b", "shares1", "pct_change", "value1"]],
                    hide_index=True, column_config={
                        "fund": st.column_config.TextColumn("Fund", width="medium"),
                        "status_b": st.column_config.MultiselectColumn(
                            "Change", options=["New", "Added", "Held", "Trimmed", "Exited"],
                            color=["green", "green", "gray", "orange", "red"], width=95),
                        "shares1": st.column_config.NumberColumn("Shares", format="compact"),
                        "pct_change": st.column_config.NumberColumn("Change",
                                                                    format="percent"),
                        "value1": st.column_config.NumberColumn("Value", format="compact")})
                st.caption(f"Quarter to {pd.Timestamp(mine['period'].max()):%b %d, %Y} vs "
                           "each fund's previous quarter")
    with scol:
        with card("Short share of volume", icon_name="trending_down", meta="FINRA daily"):
            ss = short_series(ticker)
            if ss.empty or len(ss) < 2:
                empty_state("No short-volume history yet", "", "trending_down")
            else:
                ss["ratio_5"] = ss["ratio"].rolling(5, min_periods=1).mean()
                fig = go.Figure()
                fig.add_trace(go.Bar(x=ss["date"], y=ss["ratio"], name="Daily",
                                     marker=dict(color="#3A4557"),
                                     hovertemplate="%{y:.0%}"))
                fig.add_trace(go.Scatter(x=ss["date"], y=ss["ratio_5"], name="5-day average",
                                         mode="lines", line=dict(color=ACCENT, width=2),
                                         hovertemplate="%{y:.0%}"))
                fig.update_layout(**plotly_layout(height=260, hovermode="x unified"))
                fig.update_yaxes(tickformat=".0%", range=[0, 1])
                chart(fig, key="short_series")
        with card("Short interest trend", icon_name="stacked_line_chart",
                  meta="% of float · daily snapshots"):
            from bioterm.process.snapshots import history as _snap_hist

            try:
                sh = _snap_hist(ticker)
            except Exception:  # noqa: BLE001 - older database without the table
                sh = pd.DataFrame()
            sh = sh.dropna(subset=["short_percent_float"]) if not sh.empty else sh
            if len(sh) < 2:
                st.caption("Builds up from the daily point-in-time snapshots - two or more "
                           "days are needed for a trend.")
            else:
                fig = go.Figure(go.Scatter(x=sh["asof"], y=sh["short_percent_float"],
                                           mode="lines+markers", name="Short % float",
                                           line=dict(color=ACCENT, width=2),
                                           hovertemplate="%{y:.1%}"))
                fig.update_layout(**plotly_layout(height=220, hovermode="x unified"))
                fig.update_yaxes(tickformat=".0%")
                chart(fig, key="short_interest_trend")

# ---- filings
with tab_bs:
    from bioterm import screener as _scr
    from bioterm.process.valuation import sotp

    try:
        _row = _scr.frame().set_index("ticker")
        me = _row.loc[ticker] if ticker in _row.index else None
    except Exception:  # noqa: BLE001
        me = None
    if me is not None:
        with kpi_row(4, "bs"):
            ev = me.get("ev")
            st.metric("Enterprise value", money(ev), border=True,
                      delta="below net cash" if me.get("below_cash") else None,
                      delta_color="off", delta_arrow="off",
                      help="Market cap - cash + debt (XBRL)")
            st.metric("Dilution risk", f"{float(me['dilution_risk']):.2f}", border=True,
                      help="Screen 0-1: short runway, an active shelf, a recent raise, "
                           "warrant/option overhang, insiders' Form 144s")
            wo = me.get("warrant_overhang")
            st.metric("Warrant overhang", "–" if wo is None or pd.isna(wo) else f"{wo:.1%}",
                      border=True, help="Warrants outstanding / shares (XBRL)")
            st.metric("Takeout profile", f"{float(me['takeout_score']):.2f}", border=True,
                      help="Screen 0-1 (bioterm/screener.py) - not a prediction")
        flags = []
        if me.get("shelf_active"):
            flags.append("an S-3 shelf is on file (3 years)")
        if me.get("raised_90d"):
            flags.append("a 424B prospectus supplement in the last 90 days")
        if (me.get("form144_90d") or 0) > 0:
            flags.append(f"{int(me['form144_90d'])} Form 144 filings (insider sale notices) "
                         "in 90 days")
        if flags:
            st.caption("Dilution radar: " + "; ".join(flags) + ".")
    sp = sotp(ticker)
    if sp:
        with card("Sum of the parts", icon_name="calculate",
                  meta="your rNPV inputs (Molecules page) + cash - debt"):
            parts = pd.DataFrame(sp["parts"])
            st.dataframe(parts, hide_index=True, width="stretch", column_config={
                "molecule": "Molecule",
                "rnpv": st.column_config.NumberColumn("rNPV", format="compact"),
                "pos": st.column_config.NumberColumn("PoS", format="percent"),
                "peak_sales": st.column_config.NumberColumn("Peak sales", format="compact")})
            kv_list([("Pipeline rNPV", money(sum(p["rnpv"] for p in sp["parts"])), None),
                     ("Cash - debt", money(sp["cash"] - sp["debt"]), None),
                     ("Equity value", money(sp["equity_value"]), None),
                     ("Per share", f"${sp['per_share']:,.2f}" if sp["per_share"] else "–",
                      None),
                     ("Market cap", money(sp["market_cap"]), None)])
    loe = q("SELECT trade_name, ingredient, appl_no, approval_date, patent_expiry, "
            "exclusivity_expiry, loe_date FROM loe_calendar WHERE ticker = :t "
            "ORDER BY loe_date", {"t": ticker})
    if not loe.empty:
        with card("Marketed drugs and loss of exclusivity", icon_name="medication",
                  meta="FDA Orange Book (BLAs: approval + 12 years, estimated)"):
            st.dataframe(loe, hide_index=True, width="stretch", column_config={
                "trade_name": "Brand", "ingredient": "Ingredient", "appl_no": "Application",
                "approval_date": st.column_config.DateColumn("Approved", format="MMM YYYY"),
                "patent_expiry": st.column_config.DateColumn("Last patent", format="MMM YYYY"),
                "exclusivity_expiry": st.column_config.DateColumn("Exclusivity",
                                                                  format="MMM YYYY"),
                "loe_date": st.column_config.DateColumn("LOE", format="MMM YYYY")})
            fa = q("SELECT brand, quarter, reports FROM faers_counts WHERE ticker = :t "
                   "ORDER BY quarter", {"t": ticker})
            if not fa.empty:
                st.caption("FDA adverse-event reports per quarter (FAERS) - rising counts "
                           "after launch track uptake")
                st.bar_chart(fa, x="quarter", y="reports", color="brand", height=180,
                             x_label="", y_label="reports")
    ga = q("SELECT agency, sub_agency, amount, start_date, end_date, award_type, description, "
           "url FROM gov_awards WHERE ticker = :t ORDER BY amount DESC", {"t": ticker})
    if not ga.empty:
        with card("Government awards", icon_name="account_balance",
                  meta="USAspending.gov · contracts and grants, 5 years"):
            st.dataframe(ga, hide_index=True, width="stretch", column_config={
                "amount": st.column_config.NumberColumn("Amount", format="compact"),
                "start_date": st.column_config.DateColumn("Start", format="MMM YYYY"),
                "end_date": st.column_config.DateColumn("End", format="MMM YYYY"),
                "description": st.column_config.TextColumn("Description", width="large"),
                "url": st.column_config.LinkColumn("", display_text="Open")})
    d13 = q("SELECT form, filed_date, url FROM filings WHERE ticker = :t AND (form LIKE 'SC 13%' "
            "OR form LIKE 'SCHEDULE 13%') ORDER BY filed_date DESC LIMIT 20", {"t": ticker})
    io13 = q("SELECT period, holders, holders_prev, new_holders, exited_holders, shares, value, "
             "top_holders FROM inst_ownership WHERE ticker = :t ORDER BY period DESC LIMIT 1",
             {"t": ticker})
    if not io13.empty or not d13.empty:
        with card("Ownership filings", icon_name="groups",
                  meta="all 13F filers · Schedule 13D (activist) / 13G (passive 5%+)"):
            if not io13.empty:
                r0 = io13.iloc[0]
                hp = r0["holders_prev"]
                st.markdown(f"**{int(r0['holders'])} institutions** held it at "
                            f"{pd.Timestamp(r0['period']):%b %d, %Y}"
                            + (f" ({int(r0['holders']) - int(hp):+d} vs the prior quarter: "
                               f"{int(r0['new_holders'] or 0)} new, "
                               f"{int(r0['exited_holders'] or 0)} exited)" if pd.notna(hp)
                               else ""))
                top = pd.DataFrame(json.loads(r0["top_holders"] or "[]"))
                if not top.empty:
                    st.dataframe(top, hide_index=True, width="stretch", column_config={
                        "name": "Holder", "shares": st.column_config.NumberColumn(
                            "Shares", format="compact"),
                        "value": st.column_config.NumberColumn("Value", format="compact"),
                        "change": "Change vs prior quarter"})
            if not d13.empty:
                st.dataframe(d13, hide_index=True, width="stretch", column_config={
                    "form": "Form", "filed_date": st.column_config.DateColumn(
                        "Filed", format="MMM D, YYYY"),
                    "url": st.column_config.LinkColumn("Document", display_text="Open")})
    if me is None and not sp and loe.empty and ga.empty and d13.empty and io13.empty:
        empty_state("No balance-sheet data yet", "Fundamentals arrive with the next full "
                    "refresh.", "savings")

with tab_fil:
    try:
        gc = q("SELECT form, filed_date, going_concern FROM filing_risk_flags "
               "WHERE ticker = :t ORDER BY filed_date DESC LIMIT 1", {"t": ticker})
    except Exception:  # noqa: BLE001 - table only exists once EDGAR has run
        gc = pd.DataFrame()
    if not gc.empty and int(gc.iloc[0]["going_concern"] or 0) == 1:
        st.warning(f"The latest {gc.iloc[0]['form']} (filed "
                   f"{pd.Timestamp(gc.iloc[0]['filed_date']):%b %d, %Y}) contains "
                   "going-concern language — substantial doubt about continuing operations.",
                   icon=":material/warning:")
    fl = filings_df(ticker)
    if fl.empty:
        empty_state("No filings tracked", "Needs a resolved SEC CIK for this ticker.",
                    "description")
    else:
        st.dataframe(
            fl[["filed_date", "form", "items", "title", "url"]], hide_index=True,
            column_config={
                "filed_date": st.column_config.DateColumn("Filed", format="MMM D, YYYY",
                                                          width=110),
                "form": st.column_config.TextColumn("Form", width=80),
                "items": st.column_config.TextColumn("8-K items", width=110),
                "title": st.column_config.TextColumn("Description", width="large"),
                "url": st.column_config.LinkColumn("Document", display_text="Open")})
        st.caption("8-K = material events · 424B5 / S-1 / S-3 = offerings (dilution) · "
                   "10-K / 10-Q = periodic reports.")
