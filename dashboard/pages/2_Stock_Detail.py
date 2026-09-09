"""Deep dive on one name: price+technicals, cash runway, pipeline, catalysts, news."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from _shared import (PLOTLY_TEMPLATE, catalysts_df, disclaimer, filings_df,
                     fundamentals_row, money, news_df, pct, prices_df,
                     runway_badge, scores_df, sidebar_freshness, technicals_df,
                     trials_df, universe_df)
from bioterm.config import load_settings

st.title("Stock Detail")
disclaimer()
sidebar_freshness()

uni = universe_df()
scores = scores_df()
if uni.empty:
    st.warning("No universe — run `bioterm universe`.")
    st.stop()

# ------------------------------------------------------------------- selector
qs = st.query_params.get("ticker")
options = uni["ticker"].tolist()
default_ix = options.index(qs) if qs in options else (
    options.index(scores.iloc[0]["ticker"]) if not scores.empty else 0)
ticker = st.selectbox("ticker", options, index=default_ix)
st.query_params["ticker"] = ticker

meta = uni[uni["ticker"] == ticker].iloc[0]
srow = scores[scores["ticker"] == ticker]
fund = fundamentals_row(ticker)
wl = next((w for w in load_settings().watchlist
           if str(w["ticker"]).upper() == ticker), None)

h1, h2, h3, h4, h5 = st.columns(5)
h1.subheader(f"{ticker}")
h1.caption(meta["name"])
if not srow.empty:
    h2.metric("Focus Score", f"{srow.iloc[0]['focus_score']:.3f}",
              f"rank #{int(srow.iloc[0]['rank'])}")
h3.metric("market cap", money(fund.get("market_cap")))
h4.metric("cash", money(fund.get("cash")))
h5.metric("ann. burn", money(fund.get("burn_ttm")))
st.caption(runway_badge(fund.get("runway_quarters")))
if wl:
    st.info(f"**On your watchlist — conviction {wl.get('conviction')}/5.** "
            f"{wl.get('thesis', '')}")
    if wl.get("molecules"):
        st.caption("tracked programs: " + " · ".join(wl["molecules"]))

tab_px, tab_pipe, tab_cat, tab_news, tab_fil = st.tabs(
    ["📈 Price & technicals", "🧪 Pipeline", "🗓 Catalysts", "📰 News", "📄 SEC filings"])

# ------------------------------------------------------------------- price
with tab_px:
    pxdf = prices_df(ticker)
    tech = technicals_df(ticker)
    if pxdf.empty:
        st.info("no price history — yfinance returned nothing for this ticker")
    else:
        win = st.radio("window", ["6M", "1Y", "2Y"], horizontal=True, index=1)
        days = {"6M": 126, "1Y": 252, "2Y": 520}[win]
        p = pxdf.tail(days)
        t = tech[tech["date"] >= p["date"].min()] if not tech.empty else tech

        fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                            row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(
            x=p["date"], open=p["open"], high=p["high"], low=p["low"], close=p["close"],
            name="price", showlegend=False), row=1, col=1)
        if not t.empty:
            for col, color in (("sma20", "#42a5f5"), ("sma50", "#ab47bc"),
                               ("sma200", "#ffa726")):
                if col in t and t[col].notna().any():
                    fig.add_trace(go.Scatter(x=t["date"], y=t[col], name=col,
                                             line=dict(width=1)), row=1, col=1)
            fig.add_trace(go.Bar(x=p["date"], y=p["volume"], name="vol",
                                 marker_color="#546e7a", showlegend=False), row=2, col=1)
            if "rsi14" in t:
                fig.add_trace(go.Scatter(x=t["date"], y=t["rsi14"], name="RSI14",
                                         line=dict(color="#00b8d4", width=1)), row=3, col=1)
                fig.add_hline(y=70, line=dict(color="#ef5350", dash="dot", width=1), row=3, col=1)
                fig.add_hline(y=30, line=dict(color="#26a69a", dash="dot", width=1), row=3, col=1)
        # mark catalysts on the price axis
        cat = catalysts_df()
        cat = cat[(cat["ticker"] == ticker) & (cat["date"] >= p["date"].min())]
        for _, cc in cat.iterrows():
            fig.add_vline(x=cc["date"], line=dict(color="#ffd54f", dash="dash", width=1), row=1, col=1)
        fig.update_layout(template=PLOTLY_TEMPLATE, height=640, showlegend=True,
                          margin=dict(l=10, r=10, t=20, b=10),
                          xaxis_rangeslider_visible=False, legend=dict(orientation="h"))
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
        st.plotly_chart(fig, use_container_width=True)

        if not t.empty:
            last = t.iloc[-1]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("1M / 3M / 6M", f"{pct(last.get('ret_1m'))}",
                      f"{pct(last.get('ret_3m'))} · {pct(last.get('ret_6m'))}")
            m2.metric("RSI(14)", f"{last.get('rsi14', float('nan')):.0f}")
            m3.metric("vol z-score (20d)", f"{last.get('vol_z20', float('nan')):.2f}")
            m4.metric("52w range position",
                      f"{(last.get('pct_52w_range') or 0) * 100:.0f}%")
        st.caption("Dashed gold lines mark dated catalysts.")

# ------------------------------------------------------------------- pipeline
with tab_pipe:
    tr = trials_df(ticker)
    if tr.empty:
        st.info("No lead-sponsored interventional trials found on ClinicalTrials.gov "
                "for this sponsor name.")
    else:
        active = tr[tr["status"].isin(
            ["RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
             "NOT_YET_RECRUITING"])]
        st.metric("active trials", len(active), f"{len(tr)} total tracked")

        gantt = tr.dropna(subset=["primary_completion_date", "start_date"]).copy()
        if not gantt.empty:
            gantt = gantt.sort_values("primary_completion_date").tail(25)
            gantt["label"] = gantt["title"].str.slice(0, 55)
            fig = px.timeline(
                gantt, x_start="start_date", x_end="primary_completion_date",
                y="label", color="phase", template=PLOTLY_TEMPLATE,
                hover_data=["nct_id", "status", "conditions", "enrollment"],
                color_discrete_map={"P3": "#ef5350", "P2/P3": "#ef5350", "P2": "#ffa726",
                                    "P1/P2": "#ffca28", "P1": "#42a5f5"})
            fig.add_vline(x=pd.Timestamp.today(), line=dict(color="#fff", dash="dot"))
            fig.update_yaxes(autorange="reversed", title=None)
            fig.update_layout(height=min(640, 90 + 26 * len(gantt)),
                              margin=dict(l=10, r=10, t=30, b=10),
                              title="trial timelines (start → primary completion)",
                              legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            tr[["nct_id", "phase", "status", "title", "conditions", "interventions",
                "primary_completion_date", "enrollment", "last_update_post_date"]]
            .sort_values("primary_completion_date"),
            hide_index=True, use_container_width=True,
            column_config={"nct_id": st.column_config.LinkColumn(
                "NCT", display_text=r".*/(NCT\d+)$")},
        )

# ------------------------------------------------------------------- catalysts
with tab_cat:
    cat = catalysts_df()
    cat = cat[cat["ticker"] == ticker].sort_values("date")
    if cat.empty:
        st.info("no dated catalysts derived for this name")
    else:
        st.dataframe(
            cat[["date", "type", "title", "months_away", "confidence", "source", "url"]],
            hide_index=True, use_container_width=True,
            column_config={"url": st.column_config.LinkColumn("src", display_text="↗")})

# ------------------------------------------------------------------- news
with tab_news:
    nw = news_df(2000)
    nw = nw[nw["tickers_csv"].fillna("").str.contains(rf"\b{ticker}\b")]
    nw = nw.sort_values("published", ascending=False).head(60)
    if nw.empty:
        st.info("no recent news matched")
    for _, r in nw.iterrows():
        icon = "🟢" if (r["event_score"] or 0) > 0.3 else "🔴" if (r["event_score"] or 0) < -0.3 else "•"
        when = r["published"].strftime("%b %d %H:%M") if pd.notna(r["published"]) else ""
        tags = f" · `{r['event_tags']}`" if r["event_tags"] else ""
        st.markdown(f"{icon} [{r['title']}]({r['url']})  \n"
                    f"<span style='color:#888'>{when} · {r['source']} · "
                    f"sentiment {r['sentiment']:+.2f}{tags}</span>", unsafe_allow_html=True)

# ------------------------------------------------------------------- filings
with tab_fil:
    fl = filings_df(ticker)
    if fl.empty:
        st.info("no filings tracked (needs a resolved SEC CIK)")
    else:
        st.dataframe(fl[["filed_date", "form", "items", "title", "url"]],
                     hide_index=True, use_container_width=True,
                     column_config={"url": st.column_config.LinkColumn("doc", display_text="↗")})
        st.caption("Forms tracked: 8-K (material events), 424B5 / S-1 / S-3 (offerings = dilution).")
