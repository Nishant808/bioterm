"""Alerts - rules, what's firing now, and the fired-alert history."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import alerts_fired_df, news_df
from _ui import alert_detail, alert_rows, card, empty_state, kpi_row, page_header
from bioterm import alerts as alert_engine
from bioterm import store

page_header("Alerts",
            "Rules run on every fast refresh · new hits are logged, and sent to Telegram "
            "if configured")


@st.cache_data(ttl=120, show_spinner=False)
def firing_now(rules: dict) -> list[dict]:
    """The rules against the latest data - keyed on the rules, so moving a slider
    re-evaluates while a plain revisit is instant (data only changes every refresh)."""
    return alert_engine.evaluate(rules)


rules = alert_engine.get_rules()

with st.expander("Alert rules", icon=":material/tune:", expanded=False):
    with st.container(horizontal=True, gap="large"):
        rules["score_jump"] = st.slider("Focus Score move (absolute, vs last run)",
                                        0.01, 0.30, float(rules["score_jump"]), 0.01)
        rules["catalyst_within_days"] = st.slider("Flag a catalyst within N days", 3, 60,
                                                  int(rules["catalyst_within_days"]))
    tags = news_df(4000)["event_tags"].dropna().astype(str).str.split(",").explode()
    all_tags = sorted({t for t in tags.str.strip() if t})
    base = [t for t in rules["event_tags"] if not all_tags or t in all_tags]
    rules["event_tags"] = st.multiselect("High-signal event tags",
                                         sorted(set(all_tags) | set(rules["event_tags"])),
                                         default=base)
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        rules["watchlist_only"] = st.toggle("Watchlist names only",
                                            value=bool(rules["watchlist_only"]))
        st.space("stretch")
        if st.button("Save rules", type="primary", icon=":material/save:"):
            store.set_meta("alert_rules", rules)
            st.cache_data.clear()
            st.toast("Rules saved — the ingest-fast workflow reads them on each run",
                     icon=":material/check_circle:")

tab_now, tab_hist = st.tabs([":material/notifications_active: Firing now",
                             ":material/history: History"])

with tab_now:
    firing = firing_now(rules)
    if not firing:
        empty_state("Nothing trips the current rules right now",
                    "Loosen a threshold above, or check back after the next refresh.",
                    "notifications_off")
    else:
        kinds = pd.Series([a["kind"] for a in firing]).value_counts()
        with kpi_row(4, "firing"):
            st.metric("Firing", len(firing), border=True)
            st.metric("Score moves", int(kinds.get("score move", 0)), border=True)
            st.metric("Catalysts soon", int(kinds.get("catalyst soon", 0)), border=True)
            st.metric("Headlines", int(kinds.get("headline", 0)), border=True)
        with card("Firing now", icon_name="notifications_active",
                  meta="Strongest signal first"):
            alert_rows(firing)

with tab_hist:
    hist = alerts_fired_df()
    if hist.empty:
        empty_state("No alerts recorded yet",
                    "They accumulate once the ingest-fast workflow (or `bioterm alerts`) has "
                    "run against this database.", "history")
    else:
        hist["ts"] = pd.to_datetime(hist["ts"])
        hist["detail"] = hist["detail"].map(alert_detail)
        n_undelivered = int((hist["delivered"] == 0).sum())
        with kpi_row(2, "hist"):
            st.metric("Recorded", len(hist), help="Newest 300 shown", border=True)
            st.metric("Not delivered", n_undelivered, border=True,
                      help="Delivery = Telegram, when TELEGRAM_* secrets are set on the workflow")
        st.dataframe(
            hist[["ts", "kind", "ticker", "detail", "weight", "delivered"]],
            hide_index=True, height=460,
            column_config={
                "ts": st.column_config.DatetimeColumn("When", format="MMM D, HH:mm", width=120),
                "kind": st.column_config.TextColumn("Kind", width=110),
                "ticker": st.column_config.TextColumn("Ticker", width=72),
                "detail": st.column_config.TextColumn("Detail", width="large"),
                "weight": st.column_config.NumberColumn("Weight", format="%.2f", width=80),
                "delivered": st.column_config.CheckboxColumn("Sent", width=60),
            },
        )

with st.expander("Delivery setup", icon=":material/send:"):
    st.markdown(
        "Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as GitHub Actions secrets "
        "(BotFather → new bot → token; message the bot, then read the chat id from "
        "`api.telegram.org/bot<token>/getUpdates`). Every alert is also stored in the "
        "`alerts_fired` table for you to poll.")
