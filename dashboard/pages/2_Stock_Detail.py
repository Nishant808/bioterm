"""Deep dive on one name: price + technicals, cash runway, pipeline, catalysts,
news sentiment, insiders, filings."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from _shared import (catalysts_df, filings_df, fundamentals_row, insider_txns_df,
                     money, news_df, pct, prices_df, score_history, scores_df,
                     sentiment_df, sentiment_series, technicals_df, trials_df,
                     universe_df)
from _ui import (ACCENT, MUTED, NEG, PHASE_COLORS, POS, SMA_COLORS, WARN,
                 eyebrow, page_setup, plotly_layout, sentiment_word, stat_strip)
from bioterm import store

CATALYST_TYPES = ["pdufa", "adcom", "fda_action", "phase3_readout", "phase2_readout",
                  "phase1_readout", "data_presentation", "earnings", "other"]

page_setup("Stock Detail")

uni = universe_df()
scores = scores_df()
if uni.empty:
    st.warning("No universe yet.")
    st.stop()

# ------------------------------------------------------------------- selector
qs = st.query_params.get("ticker")
options = uni["ticker"].tolist()
default_ix = options.index(qs) if qs in options else (
    options.index(scores.iloc[0]["ticker"]) if not scores.empty else 0)
ticker = st.selectbox("ticker", options, index=default_ix, label_visibility="collapsed")
st.query_params["ticker"] = ticker

meta = uni[uni["ticker"] == ticker].iloc[0]
srow = scores[scores["ticker"] == ticker]
fund = fundamentals_row(ticker)
sig = sentiment_df(14).set_index("ticker")
sg = sig.loc[ticker].to_dict() if ticker in sig.index else {}
wl = next((w for w in store.get_watchlist()
           if str(w["ticker"]).upper() == ticker), None)

st.markdown(f"<div class='bt-brand' style='font-size:1.3rem'>{ticker} "
            f"<span class='bt-meta' style='font-weight:400'>{meta['name']}</span></div>",
            unsafe_allow_html=True)

sw, scv = sentiment_word(sg.get("signal"))
rq = fund.get("runway_quarters")
rq_txt = f"{rq:.1f}Q" if rq and not pd.isna(rq) else "–"
rq_col = POS if (rq and rq >= 8) else NEG if (rq and rq < 4) else None
strip = []
if not srow.empty:
    strip.append(("Focus", f"{srow.iloc[0]['focus_score']:.3f}  #{int(srow.iloc[0]['rank'])}",
                  ACCENT))
strip += [
    ("mkt cap", money(fund.get("market_cap")), None),
    ("cash", money(fund.get("cash")), None),
    ("burn/yr", money(fund.get("burn_ttm")), None),
    ("runway", rq_txt, rq_col),
    ("news", f"{sw} {sg.get('signal', 0):+.2f}" if sg else "n/a", scv),
]
stat_strip(strip)

# ------------------------------------------------------------------- watchlist
on_wl = wl is not None
w1, w2, w3 = st.columns([1.2, 1, 1])
conv = w1.select_slider("your conviction", [1, 2, 3, 4, 5],
                        value=int(wl["conviction"]) if on_wl else 3,
                        help="your read on whether the science works — multiplies Focus")
w2.write("")
if w2.button(("update conviction" if on_wl else "★ add to watchlist"),
             use_container_width=True):
    store.add_to_watchlist(ticker, conv, wl.get("thesis", "") if on_wl else "")
    st.cache_data.clear()
    st.rerun()
w3.write("")
if on_wl and w3.button("remove", use_container_width=True):
    store.remove_from_watchlist(ticker)
    st.cache_data.clear()
    st.rerun()
if on_wl:
    thesis = st.text_input("thesis", value=wl.get("thesis", ""), key=f"th_{ticker}",
                           placeholder="why you're watching this")
    if thesis != wl.get("thesis", ""):
        store.add_to_watchlist(ticker, conv, thesis)
        st.cache_data.clear()
    if wl.get("molecules"):
        st.caption("tracked: " + " · ".join(wl["molecules"]))

hist = score_history(ticker)
if len(hist) > 1:
    hf = go.Figure(go.Scatter(x=hist["ts"], y=hist["focus_score"], mode="lines",
                              line=dict(color=ACCENT, width=2), fill="tozeroy",
                              fillcolor="rgba(91,157,255,.08)"))
    hf.update_layout(**plotly_layout(height=120, title="Focus Score history",
                                     yaxis=dict(gridcolor="rgba(0,0,0,0)")))
    st.plotly_chart(hf, use_container_width=True)

with st.expander("📝 research notes", expanded=bool(store.get_note(ticker))):
    note = st.text_area("notes", value=store.get_note(ticker), height=110,
                        label_visibility="collapsed", key=f"note_{ticker}")
    if st.button("save note", key=f"sn_{ticker}"):
        store.set_note(ticker, note)
        st.cache_data.clear()
        st.toast("saved")

tab_px, tab_pipe, tab_cat, tab_news, tab_ins, tab_fil = st.tabs(
    ["Price & technicals", "Pipeline", "Catalysts", "News & sentiment",
     "Insiders", "SEC filings"])

# ------------------------------------------------------------------- price
with tab_px:
    pxdf = prices_df(ticker)
    tech = technicals_df(ticker)
    if pxdf.empty:
        st.info("no price history — Yahoo returned nothing for this ticker")
    else:
        win = st.radio("window", ["6M", "1Y", "2Y"], horizontal=True, index=1,
                       label_visibility="collapsed")
        days = {"6M": 126, "1Y": 252, "2Y": 520}[win]
        p = pxdf.tail(days)
        t = tech[tech["date"] >= p["date"].min()] if not tech.empty else tech

        fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                            row_heights=[0.62, 0.18, 0.20], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(
            x=p["date"], open=p["open"], high=p["high"], low=p["low"],
            close=p["close"], name="price", showlegend=False,
            increasing_line_color=POS, decreasing_line_color=NEG), row=1, col=1)
        if not t.empty:
            for col, color in SMA_COLORS.items():
                if col in t and t[col].notna().any():
                    fig.add_trace(go.Scatter(x=t["date"], y=t[col], name=col.upper(),
                                             line=dict(width=1, color=color)), row=1, col=1)
            fig.add_trace(go.Bar(x=p["date"], y=p["volume"], name="vol",
                                 marker_color="#3a4557", showlegend=False), row=2, col=1)
            if "rsi14" in t:
                fig.add_trace(go.Scatter(x=t["date"], y=t["rsi14"], name="RSI 14",
                                         line=dict(color=ACCENT, width=1)), row=3, col=1)
                fig.add_hline(y=70, line=dict(color=NEG, dash="dot", width=1), row=3, col=1)
                fig.add_hline(y=30, line=dict(color=POS, dash="dot", width=1), row=3, col=1)
        cat = catalysts_df()
        cat = cat[(cat["ticker"] == ticker) & (cat["date"] >= p["date"].min())]
        for _, cc in cat.iterrows():
            fig.add_vline(x=cc["date"], line=dict(color=WARN, dash="dash", width=1), row=1, col=1)
        fig.update_layout(**plotly_layout(height=580, xaxis_rangeslider_visible=False))
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
        st.plotly_chart(fig, use_container_width=True)

        if not t.empty:
            last = t.iloc[-1]
            g = st.columns(4)
            g[0].metric("1M / 3M / 6M", pct(last.get("ret_1m")),
                        f"{pct(last.get('ret_3m'))} · {pct(last.get('ret_6m'))}")
            g[1].metric("RSI (14)", f"{last.get('rsi14', float('nan')):.0f}")
            g[2].metric("volume z (20d)", f"{last.get('vol_z20', float('nan')):.2f}")
            g[3].metric("52w range", f"{(last.get('pct_52w_range') or 0) * 100:.0f}%")
        st.caption("Amber dashes = dated catalysts.")

# ------------------------------------------------------------------- pipeline
with tab_pipe:
    tr = trials_df(ticker)
    if tr.empty:
        st.info("No lead-sponsored interventional trials found on ClinicalTrials.gov.")
    else:
        active = tr[tr["status"].isin(
            ["RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
             "NOT_YET_RECRUITING"])]
        st.metric("active trials", len(active), f"{len(tr)} tracked")
        gantt = tr.dropna(subset=["primary_completion_date", "start_date"]).copy()
        if not gantt.empty:
            gantt = gantt.sort_values("primary_completion_date").tail(25)
            gantt["label"] = gantt["title"].str.slice(0, 55)
            fig = px.timeline(gantt, x_start="start_date", x_end="primary_completion_date",
                              y="label", color="phase",
                              hover_data=["nct_id", "status", "conditions", "enrollment"],
                              color_discrete_map=PHASE_COLORS)
            fig.add_vline(x=pd.Timestamp.today(), line=dict(color="#fff", dash="dot"))
            fig.update_yaxes(autorange="reversed", title=None)
            fig.update_layout(**plotly_layout(
                height=min(620, 90 + 26 * len(gantt)),
                title="trial timelines (start → primary completion)"))
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(
            tr[["nct_id", "phase", "status", "title", "conditions", "interventions",
                "primary_completion_date", "enrollment", "last_update_post_date"]]
            .sort_values("primary_completion_date"),
            hide_index=True, use_container_width=True,
            column_config={"nct_id": st.column_config.LinkColumn("NCT",
                                                                display_text=r".*/(NCT\d+)$")})

# ------------------------------------------------------------------- catalysts
with tab_cat:
    cat = catalysts_df()
    cat = cat[cat["ticker"] == ticker].sort_values("date")
    if cat.empty:
        st.info("no dated catalysts derived yet — add one below")
    else:
        st.dataframe(
            cat[["date", "type", "title", "months_away", "confidence", "source", "url"]],
            hide_index=True, use_container_width=True,
            column_config={"url": st.column_config.LinkColumn("src", display_text="↗"),
                           "months_away": st.column_config.NumberColumn("mo away",
                                                                       format="%.1f")})
    with st.form(f"addcat_{ticker}", clear_on_submit=True):
        st.markdown("**＋ Pin a catalyst you know about** (PDUFA, AdCom, expected readout)")
        fc = st.columns([1, 1, 1.4])
        c_type = fc[0].selectbox("type", CATALYST_TYPES)
        c_date = fc[1].date_input("date")
        c_conf = fc[2].select_slider("confidence", ["low", "medium", "high"], value="medium")
        c_title = st.text_input("what happens", placeholder="e.g. FDA decision on ___ sNDA")
        c_url = st.text_input("source link (optional)")
        if st.form_submit_button("add catalyst", type="primary") and c_title:
            store.add_manual_catalyst(ticker, c_type, c_date, c_title, c_conf, c_url)
            st.cache_data.clear()
            st.rerun()
    manual = [c for c in store.get_manual_catalysts()
              if str(c.get("ticker", "")).upper() == ticker]
    for c in manual:
        x, y = st.columns([6, 1])
        x.write(f"• **{c['date']}** · {c['type']} · {c['title']}  ({c['confidence']})")
        if y.button("delete", key=f"dc_{c['id']}"):
            store.delete_manual_catalyst(c["id"])
            st.cache_data.clear()
            st.rerun()

# ------------------------------------------------------------------- news & sentiment
with tab_news:
    ser = sentiment_series(ticker, 60)
    s1, s2, s3 = st.columns(3)
    s1.metric("14-day signal", f"{sg.get('signal', 0):+.2f}" if sg else "–", sw)
    s2.metric("headlines (14d)", int(sg["n"]) if sg else 0)
    s3.metric("event tilt", f"{sg.get('tilt', 0):+.1f}" if sg else "–",
              f"{sg.get('pos', 0)}▲ / {sg.get('neg', 0)}▼" if sg else None)
    if not ser.empty and len(ser) > 1:
        f = make_subplots(specs=[[{"secondary_y": True}]])
        f.add_trace(go.Bar(x=ser["day"], y=ser["n"], name="headlines/day",
                           marker_color="#2e3a4d"), secondary_y=True)
        f.add_trace(go.Scatter(x=ser["day"], y=ser["sent_7d"], name="sentiment (7d avg)",
                               line=dict(color=ACCENT, width=2)), secondary_y=False)
        f.add_hline(y=0, line=dict(color=MUTED, width=1))
        f.update_layout(**plotly_layout(height=220, title="news sentiment · 60 days"))
        f.update_yaxes(range=[-1, 1], secondary_y=False)
        f.update_yaxes(showgrid=False, secondary_y=True)
        st.plotly_chart(f, use_container_width=True)

    nw = news_df(3000)
    nw = nw[nw["tickers_csv"].fillna("").str.contains(rf"\b{ticker}\b")]
    nw = nw.sort_values("published", ascending=False).head(60)
    if nw.empty:
        st.info("no recent news matched")
    for _, r in nw.iterrows():
        es = r["event_score"] or 0
        col = POS if es > 0.3 else NEG if es < -0.3 else MUTED
        when = r["published"].strftime("%b %d %H:%M") if pd.notna(r["published"]) else ""
        tags = f" · {r['event_tags']}" if r["event_tags"] else ""
        st.markdown(
            f"<div class='bt-card'><a href='{r['url']}' target='_blank'>{r['title']}</a>"
            f"<div class='bt-meta'>{when} · {r['source']} · "
            f"tone {r['sentiment']:+.2f}<span style='color:{col}'>{tags}</span></div></div>",
            unsafe_allow_html=True)

# ------------------------------------------------------------------- insiders
with tab_ins:
    it = insider_txns_df(ticker)
    if it.empty:
        st.info("no Form 4 activity pulled (insiders are fetched for the watchlist + "
                "top-60 focus names each full refresh)")
    else:
        buys, sells = it[it["code"] == "P"], it[it["code"] == "S"]
        w90 = pd.Timestamp.today() - pd.Timedelta(days=90)
        b90 = buys[buys["txn_date"] >= w90]["value"].sum()
        s90 = -sells[sells["txn_date"] >= w90]["value"].sum()
        g = st.columns(3)
        g[0].metric("open-market buys (90d)", money(b90) if b90 else "–",
                    f"{buys[buys['txn_date'] >= w90]['owner'].nunique()} insiders")
        g[1].metric("open-market sells (90d)", money(s90) if s90 else "–")
        g[2].metric("net (90d)", money(b90 - s90),
                    delta_color="normal" if b90 - s90 >= 0 else "inverse")
        st.caption("codes — **P** open-market buy · **S** sale · M option exercise · "
                   "F tax withhold · A award · G gift")
        st.dataframe(
            it[["txn_date", "owner", "role", "code", "acquired_disposed", "shares",
                "price", "value", "url"]].head(80),
            hide_index=True, use_container_width=True,
            column_config={
                "value": st.column_config.NumberColumn("$ value", format="$%,.0f"),
                "price": st.column_config.NumberColumn(format="$%.2f"),
                "shares": st.column_config.NumberColumn(format="%,d"),
                "url": st.column_config.LinkColumn("form 4", display_text="↗")})

# ------------------------------------------------------------------- filings
with tab_fil:
    fl = filings_df(ticker)
    if fl.empty:
        st.info("no filings tracked (needs a resolved SEC CIK)")
    else:
        st.dataframe(fl[["filed_date", "form", "items", "title", "url"]],
                     hide_index=True, use_container_width=True,
                     column_config={"url": st.column_config.LinkColumn("doc",
                                                                      display_text="↗")})
        st.caption("8-K = material events · 424B5 / S-1 / S-3 = offerings (dilution).")
