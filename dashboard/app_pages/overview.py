"""Overview - what deserves attention right now."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import catalysts_df, news_df, prev_scores_df, q, scores_df, sentiment_df
from _ui import (card, catalyst_rows, display_name, empty_state, headline_rows, kpi_row,
                 page_header, spark, tone_of)

page_header("Overview", "Biotech & pharma catalyst monitor · 6-month swing horizon")

scores = scores_df()
if scores.empty:
    empty_state("No scores yet",
                "The first ingestion run hasn't landed. Data appears here automatically "
                "as soon as it does.", "hourglass_top")
    st.stop()

prev = prev_scores_df().set_index("ticker")
cats = catalysts_df()
news = news_df(3000)
sent = sentiment_df(14).set_index("ticker")
now = pd.Timestamp.now(tz="UTC")
today = pd.Timestamp.today().normalize()

# ------------------------------------------------------------------ KPIs
horizon = cats[(cats["months_away"] >= -0.2) & (cats["months_away"] <= 6)]
next30 = cats[(cats["date"] >= today) & (cats["date"] <= today + pd.Timedelta(days=30))]
week = horizon["date"].dt.to_period("W").dt.start_time
weekly = week.value_counts().reindex(
    pd.period_range(today, today + pd.Timedelta(weeks=25), freq="W").start_time,
    fill_value=0)

# Trends need a full 30 days of headlines - the cached headline frame is capped
# at the newest 3,000 rows (about a week), which would zero out any "prior
# week". Three narrow columns over 30 days, keyed to the hour so it caches.
_cut = (now - pd.Timedelta(days=30)).floor("h").strftime("%Y-%m-%d %H:%M:%S")
act = q("SELECT published, event_score, sentiment FROM news WHERE published >= :c", {"c": _cut})
act["published"] = pd.to_datetime(act["published"], utc=True, errors="coerce")
act["event"] = pd.to_numeric(act["event_score"], errors="coerce").abs()
act["tone"] = pd.to_numeric(act["sentiment"], errors="coerce")
act["day"] = act["published"].dt.floor("D")
days30 = pd.date_range((now - pd.Timedelta(days=29)).floor("D"), now.floor("D"), freq="D")

hot = act[act["event"] >= 0.8]
hot7 = int((hot["published"] >= now - pd.Timedelta(days=7)).sum())
hot_prev7 = int(((hot["published"] >= now - pd.Timedelta(days=14))
                 & (hot["published"] < now - pd.Timedelta(days=7))).sum())
hot_daily = hot["day"].value_counts().reindex(days30, fill_value=0)

tone_daily = act.groupby("day")["tone"].mean().reindex(days30)
tone_now = act[act["published"] >= now - pd.Timedelta(days=14)]["tone"].mean()
tone_before = act[(act["published"] >= now - pd.Timedelta(days=28))
                  & (act["published"] < now - pd.Timedelta(days=14))]["tone"].mean()
signal = float(sent["signal"].mean()) if not sent.empty else 0.0
word, _ = tone_of(signal)

wl = scores[scores["is_watchlist"] == 1]
wl_top = int((wl["rank"] <= 20).sum())

with kpi_row(4, "overview"):
    st.metric("Catalysts · next 30 days", len(next30),
              delta=f"{len(horizon)} within 6 months", delta_color="off", delta_arrow="off",
              help="Dated catalysts in the next 30 days. The bars show catalysts per week "
                   "across the next six months.",
              border=True, chart_data=spark(weekly), chart_type="bar")
    st.metric("High-signal news · 7 days", hot7,
              delta=hot7 - hot_prev7, delta_description="vs prior week", delta_color="off",
              help="Headlines tagged with a strong biotech event (topline, approval, "
                   "CRL, clinical hold…). Bars: daily count over the last 30 days.",
              border=True, chart_data=spark(hot_daily), chart_type="bar")
    st.metric("Sector sentiment · 14 days", f"{word} {signal:+.2f}",
              delta=None if pd.isna(tone_now) or pd.isna(tone_before)
              else round(float(tone_now - tone_before), 2),
              delta_description="tone vs prior 14 days",
              help="Mean per-name news signal (−1 to +1), blending headline tone with "
                   "event tags. Line: daily headline tone over 30 days.",
              border=True, chart_data=spark(tone_daily), chart_type="area")
    st.metric("Watchlist in top 20", f"{wl_top} of {len(wl)}",
              delta=f"{len(scores)} names tracked", delta_color="off", delta_arrow="off",
              help="How many of your watchlist names rank in the top 20 by Focus Score.",
              border=True)

# ------------------------------------------------------------------ focus table
DRIVERS = ["Catalyst", "Momentum", "News flow", "Funding risk", "Insider buying",
           "Your conviction"]
DRIVER_COLORS = ["gray", "gray", "gray", "red", "green", "primary"]


def _drivers(o: dict) -> list[str]:
    c = (o or {}).get("components", {})
    out = []
    if c.get("catalyst", 0) >= 0.45:
        out.append("Catalyst")
    if c.get("momentum", 0) >= 0.6:
        out.append("Momentum")
    if c.get("newsflow", 0) >= 0.6:
        out.append("News flow")
    if c.get("risk", 0) >= 0.4:
        out.append("Funding risk")
    if (o or {}).get("insider_mult", 1) > 1.02:
        out.append("Insider buying")
    if (o or {}).get("conviction_mult", 1) > 1:
        out.append("Your conviction")
    return out


def _moved(n: int) -> str:
    return f"▲ {n}" if n > 0 else f"▼ {-n}" if n < 0 else "–"


top = scores.head(12).copy()
top["delta"] = [_moved(int(prev.loc[t, "rank"]) - int(r)) if t in prev.index else "–"
                for t, r in zip(top["ticker"], top["rank"])]
top["name"] = top["name"].map(display_name)
top["news"] = top["ticker"].map(lambda t: sent["signal"].get(t) if t in sent.index else None)
top["drivers"] = top["rationale_obj"].map(_drivers)

with card("Stocks in focus", icon_name="leaderboard", meta="Top 12 by Focus Score"):
    st.dataframe(
        top[["rank", "ticker", "name", "focus_score", "delta", "news", "drivers"]],
        hide_index=True,
        column_config={
            "rank": st.column_config.NumberColumn("#", width=40),
            "ticker": st.column_config.TextColumn("Ticker", width=70),
            "name": st.column_config.TextColumn("Company", width="medium"),
            "focus_score": st.column_config.ProgressColumn(
                "Focus", format="%.3f", width=150,
                min_value=float(scores["focus_score"].min()),
                max_value=float(scores["focus_score"].max())),
            "delta": st.column_config.TextColumn(
                "Moved", width=70, help="Rank places moved since the previous run"),
            "news": st.column_config.NumberColumn(
                "News", format="%+.2f", width=70, help="14-day news signal (−1 to +1)"),
            "drivers": st.column_config.MultiselectColumn(
                "Why it ranks", options=DRIVERS, color=DRIVER_COLORS, width="large"),
        },
    )
    st.page_link("app_pages/focus.py", label="Full leaderboard and score breakdown",
                 icon=":material/arrow_forward:")

# ------------------------------------------------------------------ lists
left, right = st.columns(2, gap="medium")

with left:
    recent = news[news["published"] >= now - pd.Timedelta(days=7)]
    hs = recent[pd.to_numeric(recent["event_score"], errors="coerce").abs() >= 0.6]
    hs = hs.sort_values("published", ascending=False).head(8)
    with card("High-signal headlines", icon_name="bolt", meta="Last 7 days"):
        if hs.empty:
            empty_state("Nothing tagged high-signal this week",
                        "Strong event tags (topline, approval, CRL…) will surface here.",
                        "notifications_paused")
        else:
            headline_rows(hs, time_fmt="%b %d")
        st.page_link("app_pages/news.py", label="All news", icon=":material/arrow_forward:")

with right:
    nc = cats[(cats["months_away"] >= -0.3) & (cats["months_away"] <= 6)]
    nc = nc.sort_values("date").head(8)
    with card("Next catalysts", icon_name="event_upcoming", meta="Next 6 months"):
        if nc.empty:
            empty_state("No dated catalysts in the horizon yet",
                        "Trial readouts, FDA actions and earnings appear here as they're "
                        "extracted.", "event_busy")
        else:
            catalyst_rows(nc, title_chars=110)
        st.page_link("app_pages/catalysts.py", label="Catalyst calendar",
                      icon=":material/arrow_forward:")
