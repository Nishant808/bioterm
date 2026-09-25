"""Market - the sector at a glance: a live heatmap of the universe, breadth,
the biggest movers with why they moved, trading halts and the SEC filings of the
last day."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import _live as live
from _shared import q
from _ui import (ACCENT, NEG, POS, SURFACE_2, card, chart, empty_state, esc, kpi_row,
                 page_header, plotly_layout, safe_url)

page_header("Market", "Live heatmap · breadth · movers and why they moved · halts · "
                      "filings of the last day")

BUCKETS = [(200e9, "Mega cap"), (10e9, "Large cap"), (2e9, "Mid cap"), (3e8, "Small cap"),
           (0, "Micro cap")]


@st.cache_data(ttl=300, show_spinner=False)
def _universe() -> pd.DataFrame:
    return q("SELECT s.ticker, s.name, f.market_cap FROM securities s "
             "LEFT JOIN fundamentals f ON f.ticker = s.ticker "
             "WHERE s.tier IS NULL OR s.tier = 'core'")


@st.cache_data(ttl=300, show_spinner=False)
def _tech() -> pd.DataFrame:
    return q("SELECT ticker, close, sma50, sma200, pct_52w_range FROM technicals "
             "WHERE date = (SELECT MAX(date) FROM technicals)")


@st.cache_data(ttl=120, show_spinner=False)
def _why(ticker: str) -> list[dict]:
    from bioterm.realtime import why

    return why(ticker, hours=36, limit=3)


uni = _universe()
if uni.empty:
    empty_state("No universe yet", "The first data refresh builds it.", "grid_view")
    st.stop()

with st.spinner("Loading live quotes…"):
    quotes = live.quotes(uni["ticker"].tolist() + ["XBI", "IBB"])
df = uni.assign(price=uni["ticker"].map(lambda t: (quotes.get(t) or {}).get("price")),
                chg=uni["ticker"].map(lambda t: (quotes.get(t) or {}).get("change_pct")),
                src=uni["ticker"].map(lambda t: (quotes.get(t) or {}).get("source")))
df = df.dropna(subset=["chg"])
live_share = (df["src"] == "live").mean() if not df.empty else 0

tech = _tech()
adv, dec = int((df["chg"] > 0).sum()), int((df["chg"] < 0).sum())
xbi, ibb = quotes.get("XBI") or {}, quotes.get("IBB") or {}
with kpi_row(4, "mkt"):
    st.metric("XBI", f"{xbi.get('price', float('nan')):,.2f}" if xbi else "—",
              delta=f"{xbi['change_pct']:+.2%}" if xbi.get("change_pct") == xbi.get("change_pct")
              and xbi else None, border=True, help=live.source_note(xbi.get("source", "stored"),
                                                                     xbi.get("asof"),
                                                                     xbi.get("provider")))
    st.metric("Advancers / decliners", f"{adv} / {dec}",
              delta=f"{(adv - dec) / max(1, adv + dec):+.0%} net breadth", delta_color="normal",
              border=True)
    if not tech.empty:
        above = (tech["close"] > tech["sma50"]).mean()
        st.metric("Above 50-day average", f"{above:.0%}",
                  delta=f"{(tech['close'] > tech['sma200']).mean():.0%} above 200-day",
                  delta_color="off", border=True)
    else:
        st.metric("Above 50-day average", "—", border=True)
    hi = int((tech["pct_52w_range"] >= 0.98).sum()) if not tech.empty else 0
    lo = int((tech["pct_52w_range"] <= 0.02).sum()) if not tech.empty else 0
    st.metric("At 52-week high / low", f"{hi} / {lo}", border=True,
              help="From the last stored daily close")

st.caption(("Live quotes · " if live_share > 0.5 else "Live feed unavailable - last stored "
            "closes · ") + live.market_state()[1])

# ------------------------------------------------------------------ heatmap
with card("Heatmap", icon_name="grid_view",
          meta="size = market cap · colour = today's move (±8% saturates)"):
    h = df.dropna(subset=["market_cap"]).copy()
    if h.empty:
        st.caption("Market caps arrive with the next full refresh.")
    else:
        h["bucket"] = h["market_cap"].map(
            lambda m: next(lab for thr, lab in BUCKETS if m >= thr))
        order = [lab for _, lab in BUCKETS]
        parents = [b for b in order if b in set(h["bucket"])]
        caps = h.groupby("bucket")["market_cap"].sum()
        wchg = h.groupby("bucket").apply(
            lambda g: (g["chg"] * g["market_cap"]).sum() / g["market_cap"].sum(),
            include_groups=False)
        ids = parents + h["ticker"].tolist()
        labels = parents + h["ticker"].tolist()
        par = [""] * len(parents) + h["bucket"].tolist()
        vals = [float(caps[b]) for b in parents] + h["market_cap"].astype(float).tolist()
        col = [float(wchg[b]) for b in parents] + h["chg"].astype(float).tolist()
        text = [f"{wchg[b]:+.1%}" for b in parents] + \
            [f"{c:+.1%}" for c in h["chg"]]
        hover = [f"{b}<br>cap-weighted {wchg[b]:+.2%}" for b in parents] + \
            [f"<b>{r.ticker}</b> · {esc(str(r.name))[:40]}<br>${r.price:,.2f} · {r.chg:+.2%}"
             f"<br>cap ${r.market_cap / 1e9:,.1f}B" for r in h.itertuples()]
        fig = go.Figure(go.Treemap(
            ids=ids, labels=labels, parents=par, values=vals, branchvalues="total",
            text=text, texttemplate="<b>%{label}</b><br>%{text}", hovertext=hover,
            hoverinfo="text", marker=dict(
                colors=col, cmin=-0.08, cmax=0.08, cmid=0,
                colorscale=[[0, NEG], [0.5, SURFACE_2], [1, POS]],
                line=dict(width=1, color="#0B0E14"), showscale=False),
            tiling=dict(pad=2), pathbar=dict(visible=False),
            textfont=dict(family="Inter, sans-serif", size=12)))
        fig.update_layout(**plotly_layout(height=520, margin=dict(l=0, r=0, t=4, b=0)))
        chart(fig, key="mkt_heat")

# ------------------------------------------------------------------ movers
c1, c2 = st.columns(2, gap="medium")


def _movers(sub: pd.DataFrame, title: str, icon: str) -> None:
    with card(title, icon_name=icon):
        if sub.empty:
            st.caption("No moves yet today.")
            return
        rows = []
        for r in sub.itertuples():
            why = _why(r.ticker)
            reason = why[0]["text"] if why else "No headline, filing or halt found yet"
            url = safe_url(why[0].get("url")) if why else ""
            reason_html = (f"<a href='{url}' target='_blank' rel='noopener'>{esc(reason[:150])}"
                           f"</a>" if url else esc(reason[:150]))
            color = POS if r.chg > 0 else NEG
            rows.append(
                "<div class='bt-row'><div class='bt-row-l'>"
                f"<a class='bt-tk' href='Stock_Detail?ticker={esc(r.ticker)}' target='_self'>"
                f"{esc(r.ticker)}</a></div><div class='bt-row-m'><div class='bt-row-h'>"
                f"<b style='color:{color}'>{r.chg:+.1%}</b><span class='bt-src'>"
                f"${r.price:,.2f}</span></div><div class='bt-row-s wrap'>{reason_html}"
                "</div></div></div>")
        st.html("<div class='bt-list'>" + "".join(rows) + "</div>")


with c1:
    _movers(df[df["chg"] > 0].nlargest(8, "chg"), "Top gainers", "trending_up")
with c2:
    _movers(df[df["chg"] < 0].nsmallest(8, "chg"), "Top decliners", "trending_down")

# ------------------------------------------------------------------ halts + filings
c3, c4 = st.columns(2, gap="medium")
with c3:
    with card("Trading halts", icon_name="block", meta="universe names · last 2 days"):
        from bioterm.ingest.halts import label as halt_label

        cut = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        hl = q("SELECT ticker, reason, halt_at, resumption_trade_time FROM halts "
               "WHERE ticker IS NOT NULL AND halt_at >= :c ORDER BY halt_at DESC LIMIT 20",
               {"c": cut})
        if hl.empty:
            st.caption("No halts in the universe in the last two days.")
        else:
            hl["when"] = pd.to_datetime(hl["halt_at"], utc=True).dt.tz_convert(
                "America/New_York").dt.strftime("%b %d %H:%M ET")
            hl["reason"] = hl["reason"].map(lambda c: f"{halt_label(c)} ({c})")
            st.dataframe(hl[["ticker", "reason", "when", "resumption_trade_time"]],
                         hide_index=True, width="stretch",
                         column_config={"resumption_trade_time": "Resumed"})
with c4:
    with card("SEC filings, last 24 hours", icon_name="description",
              meta="8-K · 6-K · 424B · S-3 · 13D/G"):
        fl = q("SELECT f.ticker, f.form, f.items, f.url, f.fetched_at, s.summary FROM filings f "
               "LEFT JOIN filing_summaries s ON s.accession = f.id "
               "WHERE f.filed_date >= :d AND f.form IN ('8-K','8-K/A','6-K','424B5','424B3',"
               "'424B4','S-3','S-3ASR','SC 13D','SC 13D/A','SC 13G','SCHEDULE 13D',"
               "'SCHEDULE 13G','SCHEDULE 13D/A') ORDER BY f.fetched_at DESC LIMIT 25",
               {"d": (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")})
        if fl.empty:
            st.caption("No filings in the last day yet.")
        else:
            rows = []
            for r in fl.itertuples():
                summ = str(r.summary).split("\n")[0].lstrip("- ") \
                    if isinstance(r.summary, str) else (f"items {r.items}" if r.items else "")
                u = safe_url(r.url)
                form = (f"<a href='{u}' target='_blank' rel='noopener'>{esc(r.form)}</a>"
                        if u else esc(r.form))
                rows.append("<div class='bt-row'><div class='bt-row-l'><span class='bt-tk'>"
                            f"{esc(r.ticker)}</span></div><div class='bt-row-m'>"
                            f"<div class='bt-row-h'><b>{form}</b></div>"
                            f"<div class='bt-row-s wrap'>{esc(summ[:200])}</div></div></div>")
            st.html("<div class='bt-list'>" + "".join(rows) + "</div>")

# ------------------------------------------------------------------ XBI intraday
with card("XBI · 5 days", icon_name="show_chart"):
    xh, src = live.history("XBI", "5d", "15m")
    if xh.empty:
        xh, src = live.history("XBI", "3mo", "1d")
    if xh.empty:
        st.caption("No XBI prices available.")
    else:
        fig = go.Figure(go.Scatter(x=xh["date"], y=xh["close"], mode="lines",
                                   line=dict(color=ACCENT, width=1.6),
                                   hovertemplate="%{x|%b %d %H:%M} · %{y:,.2f}<extra></extra>"))
        fig.update_layout(**plotly_layout(height=240))
        if src == "live" and len(xh) > 60:        # intraday: hide nights and weekends
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                          dict(bounds=[16, 9.5], pattern="hour")])
        chart(fig, key="mkt_xbi")
        st.caption(live.source_note(src, xh["date"].iloc[-1]) if src == "live"
                   else live.source_note(src))
