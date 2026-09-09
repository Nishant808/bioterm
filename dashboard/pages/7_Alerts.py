"""Alert rules + a preview of what currently fires. Delivery (email/Telegram) is
a later feature; today this is a fast triage list you check when you open BioTerm.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import (catalysts_df, disclaimer, news_df, prev_scores_df, scores_df,
                     sidebar_freshness)
from bioterm import store

st.title("Alerts")
disclaimer()
sidebar_freshness()

RULE_KEY = "alert_rules"
defaults = {
    "score_jump": 0.05,           # abs focus-score change vs previous run
    "catalyst_within_days": 21,   # a catalyst enters this window
    "event_tags": ["topline", "meets primary endpoint", "approval", "complete response letter",
                   "clinical hold", "breakthrough therapy", "priority review"],
    "watchlist_only": False,
}
rules = {**defaults, **(store.get_meta(RULE_KEY, {}) or {})}

with st.expander("⚙️ alert rules", expanded=False):
    rules["score_jump"] = st.slider("Focus-score move (abs, vs last run)", 0.01, 0.30,
                                    float(rules["score_jump"]), 0.01)
    rules["catalyst_within_days"] = st.slider("Flag when a catalyst comes within N days",
                                              3, 60, int(rules["catalyst_within_days"]))
    all_tags = sorted({t for _, r in news_df(4000).iterrows()
                       for t in str(r["event_tags"] or "").split(",") if t})
    rules["event_tags"] = st.multiselect("High-signal event tags", all_tags or defaults["event_tags"],
                                         default=[t for t in rules["event_tags"] if not all_tags or t in all_tags])
    rules["watchlist_only"] = st.toggle("watchlist names only", value=bool(rules["watchlist_only"]))
    if st.button("💾 save rules", type="primary"):
        store.set_meta(RULE_KEY, rules)
        st.cache_data.clear()
        st.success("saved")

wl = {w["ticker"].upper() for w in store.get_watchlist()}
scores = scores_df()
prev = prev_scores_df().set_index("ticker")
cats = catalysts_df()
news = news_df(4000)

alerts: list[dict] = []

# 1. score jumps
if not prev.empty:
    for _, r in scores.iterrows():
        if rules["watchlist_only"] and r["ticker"] not in wl:
            continue
        if r["ticker"] in prev.index:
            delta = float(r["focus_score"]) - float(prev.loc[r["ticker"], "focus_score"])
            if abs(delta) >= rules["score_jump"]:
                alerts.append({"kind": "score move", "ticker": r["ticker"],
                               "detail": f"Focus {delta:+.3f} → {r['focus_score']:.3f} (rank #{int(r['rank'])})",
                               "weight": abs(delta)})

# 2. near catalysts
near = cats[(cats["months_away"] >= -0.2) &
            (cats["months_away"] <= rules["catalyst_within_days"] / 30.0)]
for _, c in near.iterrows():
    if rules["watchlist_only"] and c["ticker"] not in wl:
        continue
    alerts.append({"kind": "catalyst soon", "ticker": c["ticker"],
                   "detail": f"{c['type']} · {c['date']:%Y-%m-%d} ({c['months_away']:.1f} mo) — {c['title'][:90]}",
                   "weight": 1.0 / (1 + max(0.0, float(c["months_away"])))})

# 3. high-signal headlines (last 3 days)
recent = news[news["published"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3)]
for _, n in recent.iterrows():
    tagset = {t for t in str(n["event_tags"] or "").split(",") if t}
    hit = tagset & set(rules["event_tags"])
    if not hit:
        continue
    if rules["watchlist_only"] and (n["ticker"] or "").upper() not in wl:
        continue
    alerts.append({"kind": "headline", "ticker": n["ticker"],
                   "detail": f"{', '.join(hit)} — {n['title'][:100]}",
                   "weight": abs(float(n["event_score"] or 0))})

if not alerts:
    st.success("Nothing trips the current rules. 🎣")
else:
    df = pd.DataFrame(alerts).sort_values("weight", ascending=False)
    st.caption(f"{len(df)} alerts")
    for _, a in df.iterrows():
        icon = {"score move": "📈", "catalyst soon": "🗓", "headline": "📰"}[a["kind"]]
        st.markdown(f"{icon} **{a['ticker']}** · _{a['kind']}_ — {a['detail']}")

st.divider()
st.caption("Roadmap: push these to email / Telegram on a schedule. The rule config "
           "above is already persisted (DB `app_meta`), so a delivery worker can read it.")
