"""Alert rules + what's firing now + the fired-alert history (with delivery status)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import alerts_fired_df, disclaimer, news_df, sidebar_freshness
from bioterm import alerts as alert_engine
from bioterm import store

st.title("Alerts")
disclaimer()
sidebar_freshness()

rules = alert_engine.get_rules()

with st.expander("⚙️ alert rules", expanded=False):
    rules["score_jump"] = st.slider("Focus-score move (abs, vs last run)", 0.01, 0.30,
                                    float(rules["score_jump"]), 0.01)
    rules["catalyst_within_days"] = st.slider("Flag a catalyst coming within N days",
                                              3, 60, int(rules["catalyst_within_days"]))
    all_tags = sorted({t for _, r in news_df(4000).iterrows()
                       for t in str(r["event_tags"] or "").split(",") if t})
    base = [t for t in rules["event_tags"] if not all_tags or t in all_tags]
    rules["event_tags"] = st.multiselect("High-signal event tags",
                                         sorted(set(all_tags) | set(rules["event_tags"])),
                                         default=base)
    rules["watchlist_only"] = st.toggle("watchlist names only",
                                        value=bool(rules["watchlist_only"]))
    if st.button("💾 save rules", type="primary"):
        store.set_meta("alert_rules", rules)
        st.cache_data.clear()
        st.success("saved — the ingest-fast workflow reads these each run")

tab_now, tab_hist = st.tabs(["🔔 firing now", "🗂 history"])

with tab_now:
    firing = alert_engine.evaluate(rules)
    if not firing:
        st.success("Nothing trips the current rules right now. 🎣")
    else:
        st.caption(f"{len(firing)} firing")
        for a in firing:
            icon = {"score move": "📈", "catalyst soon": "🗓", "headline": "📰"}[a["kind"]]
            st.markdown(f"{icon} **{a['ticker']}** · _{a['kind']}_ — {a['detail']}")

with tab_hist:
    hist = alerts_fired_df()
    if hist.empty:
        st.info("No alerts recorded yet. They accumulate once the `ingest-fast` "
                "workflow (or `bioterm alerts`) has run against this database.")
    else:
        hist["ts"] = pd.to_datetime(hist["ts"])
        n_undelivered = int((hist["delivered"] == 0).sum())
        c1, c2 = st.columns(2)
        c1.metric("recorded (300 max shown)", len(hist))
        c2.metric("not delivered", n_undelivered,
                  help="delivery = Telegram, if TELEGRAM_* secrets are set on the workflow")
        st.dataframe(
            hist[["ts", "kind", "ticker", "detail", "weight", "delivered"]],
            hide_index=True, use_container_width=True, height=460,
            column_config={
                "ts": st.column_config.DatetimeColumn("when", format="MMM DD HH:mm"),
                "delivered": st.column_config.CheckboxColumn("sent"),
            },
        )

st.divider()
st.caption("Delivery: add `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` as GitHub Actions "
           "secrets (BotFather → new bot → token; message the bot, then read chat id "
           "from `api.telegram.org/bot<token>/getUpdates`). Everything else is stored "
           "in the `alerts_fired` table for you to poll.")
