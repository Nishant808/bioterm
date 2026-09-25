"""Alert centre - what's firing, the history, the rules, where each kind of alert
goes (Telegram, Slack, Discord, phone push, email), snoozes and the brief."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st

import _auth
from _shared import alerts_fired_df, q
from _ui import (NEG, POS, alert_detail, alert_rows, card, empty_state, kpi_row, md_safe,
                 page_header, status_rows)
from bioterm import alerts as alert_engine
from bioterm import notify, store

page_header("Alerts",
            "Signals, halts, filings, movers, trial changes, catalysts and screens · routed to "
            "Telegram, Slack, Discord, phone push or email")

CAN = _auth.can_edit()


@st.cache_data(ttl=120, show_spinner=False)
def firing_now(rules: dict) -> list[dict]:
    """The rules against the latest data - keyed on the rules, so moving a slider
    re-evaluates while a plain revisit is instant (data only changes every refresh)."""
    return alert_engine.evaluate(rules)


@st.cache_data(ttl=600, show_spinner=False)
def tags_seen() -> list[str]:
    df = q("SELECT DISTINCT event_tags FROM news "
           "WHERE event_tags IS NOT NULL AND event_tags <> ''")
    return sorted({t.strip() for s in df["event_tags"].astype(str)
                   for t in s.split(",") if t.strip()})


rules = alert_engine.get_rules()
conf = notify.configured()

tab_now, tab_hist, tab_rules, tab_route, tab_snooze, tab_brief = st.tabs([
    ":material/notifications_active: Firing now", ":material/history: History",
    ":material/tune: Rules", ":material/alt_route: Routing", ":material/snooze: Snoozes",
    ":material/summarize: Daily brief"])

# ------------------------------------------------------------------ firing now
with tab_now:
    firing = firing_now(rules)
    if not firing:
        empty_state("Nothing trips the current rules right now",
                    "Loosen a threshold on the Rules tab, or check back after the next refresh.",
                    "notifications_off")
    else:
        kinds = pd.Series([a["kind"] for a in firing]).value_counts()
        with kpi_row(5, "firing"):
            st.metric("Firing", len(firing), border=True)
            st.metric("Signals & screens", int(kinds.get("signal", 0) + kinds.get("screen", 0)),
                      border=True)
            st.metric("Halts, filings, movers",
                      int(kinds.get("halt", 0) + kinds.get("filing", 0) + kinds.get("mover", 0)),
                      border=True)
            st.metric("Catalysts & trials",
                      int(kinds.get("catalyst soon", 0) + kinds.get("trial change", 0)
                          + kinds.get("read-through", 0)), border=True)
            st.metric("Headlines & scores",
                      int(kinds.get("headline", 0) + kinds.get("score move", 0)), border=True)
        with card("Firing now", icon_name="notifications_active", meta="strongest first"):
            alert_rows(firing[:120])

# ------------------------------------------------------------------ history
with tab_hist:
    hist = alerts_fired_df()
    if hist.empty:
        empty_state("No alerts recorded yet",
                    "They accumulate once a refresh or the pulse has run against this "
                    "database.", "history")
    else:
        hist["ts"] = pd.to_datetime(hist["ts"])
        hist["detail"] = hist["detail"].map(alert_detail)
        kinds = sorted(hist["kind"].dropna().unique())
        pick = st.pills("Kinds", kinds, selection_mode="multi", default=kinds, key="hist_kinds")
        h = hist[hist["kind"].isin(pick or [])]
        with kpi_row(3, "hist"):
            st.metric("Recorded", len(h), help="Newest 300 shown", border=True)
            st.metric("Delivered", int((h["delivered"] == 1).sum()), border=True)
            st.metric("Kinds", h["kind"].nunique(), border=True)
        st.dataframe(
            h[["ts", "kind", "ticker", "detail", "weight", "delivered"]],
            hide_index=True, height=460, width="stretch",
            column_config={
                "ts": st.column_config.DatetimeColumn("When", format="MMM D, HH:mm", width=120),
                "kind": st.column_config.TextColumn("Kind", width=110),
                "ticker": st.column_config.TextColumn("Ticker", width=72),
                "detail": st.column_config.TextColumn("Detail", width="large"),
                "weight": st.column_config.NumberColumn("Weight", format="%.2f", width=80),
                "delivered": st.column_config.CheckboxColumn("Sent", width=60)})

# ------------------------------------------------------------------ rules
with tab_rules:
    if not CAN:
        _auth.guard("change alert rules", key="rules")
    with st.container(horizontal=True, gap="large"):
        rules["score_jump"] = st.slider("Focus Score move (absolute, vs last run)",
                                        0.01, 0.30, float(rules["score_jump"]), 0.01)
        rules["catalyst_within_days"] = st.slider("Flag a catalyst within N days", 3, 60,
                                                  int(rules["catalyst_within_days"]))
    with st.container(horizontal=True, gap="large"):
        rules["mover_pct"] = st.slider("Live mover alert (absolute move today)", 0.05, 0.50,
                                       float(rules.get("mover_pct", 0.12)), 0.01,
                                       format="%.2f")
        rules["readthrough_pct"] = st.slider("Read-through trigger (a peer's move)", 0.05, 0.60,
                                             float(rules.get("readthrough_pct", 0.2)), 0.01,
                                             format="%.2f")
    rules["filing_alerts"] = st.segmented_control(
        "SEC filing alerts", ["default", "watchlist", "all", "off"],
        default=rules.get("filing_alerts", "default"), required=True,
        format_func={"default": "Dilution & 13D for all, 8-K for watchlist",
                     "watchlist": "Watchlist only", "all": "Every universe name",
                     "off": "Off"}.get)
    all_tags = tags_seen()
    base = [t for t in rules["event_tags"] if not all_tags or t in all_tags]
    rules["event_tags"] = st.multiselect("High-signal headline tags",
                                         sorted(set(all_tags) | set(rules["event_tags"])),
                                         default=base)
    rules["signal_labels"] = st.multiselect(
        "Signal calls to alert on", ["STRONG BUY", "BUY", "SELL", "STRONG SELL"],
        default=[x for x in (rules.get("signal_labels") or [])
                 if x in ("STRONG BUY", "BUY", "SELL", "STRONG SELL")],
        format_func=str.title, help="Fires once when a name's call changes into one of these")
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        rules["watchlist_only"] = st.toggle("Watchlist names only (every kind)",
                                            value=bool(rules["watchlist_only"]))
        st.space("stretch")
        if st.button("Save rules", type="primary", icon=":material/save:", disabled=not CAN):
            store.set_meta("alert_rules", rules)
            st.cache_data.clear()
            st.toast("Rules saved - every refresh and pulse reads them",
                     icon=":material/check_circle:")

# ------------------------------------------------------------------ routing
with tab_route:
    status_rows([(POS if conf.get(ch) else NEG, notify.LABELS[ch],
                  "configured" if conf.get(ch) else "not configured - add it on Settings")
                 for ch in notify.CHANNELS])
    st.page_link("app_pages/settings.py", label="Channel credentials (Settings → Notifications)",
                 icon=":material/settings:")
    st.caption("Tick where each kind of alert goes. A kind with no ticks goes to every "
               "configured channel.")
    rt = notify.routes()
    grid = pd.DataFrame([{"kind": k, **{ch: (ch in rt.get(k, [])) for ch in notify.CHANNELS}}
                         for k in notify.KINDS])
    edited = st.data_editor(
        grid, hide_index=True, width="stretch", disabled=["kind"] if CAN else True,
        key="route_editor",
        column_config={"kind": st.column_config.TextColumn("Alert kind"),
                       **{ch: st.column_config.CheckboxColumn(notify.LABELS[ch])
                          for ch in notify.CHANNELS}})
    if st.button("Save routing", type="primary", icon=":material/save:", disabled=not CAN):
        new = {r["kind"]: [ch for ch in notify.CHANNELS if r[ch]]
               for r in edited.to_dict("records") if any(r[ch] for ch in notify.CHANNELS)}
        notify.set_routes(new)
        st.toast("Routing saved", icon=":material/check_circle:")

# ------------------------------------------------------------------ snoozes
with tab_snooze:
    sn = notify.snoozes()
    if sn:
        for tk, until in sorted(sn.items()):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(f"**{tk}** muted until "
                            f"{pd.Timestamp(until).tz_convert('America/New_York'):%b %d, %H:%M} ET")
                st.space("stretch")
                if st.button("Unmute", key=f"unmute_{tk}", disabled=not CAN, type="tertiary",
                             icon=":material/notifications_active:"):
                    notify.snooze(tk, None)
                    st.rerun()
    else:
        st.caption("No tickers muted.")
    if CAN:
        with st.form("snooze_add", border=False, clear_on_submit=True):
            c1, c2 = st.columns([2, 1])
            tk = c1.text_input("Ticker to mute", placeholder="e.g. VRTX").strip().upper()
            days = c2.selectbox("For", [1, 3, 7, 14, 30], format_func=lambda d: f"{d} days")
            if st.form_submit_button("Mute", icon=":material/snooze:") and tk:
                notify.snooze(tk, datetime.combine(datetime.now(timezone.utc).date()
                                                   + timedelta(days=days), time(),
                                                   tzinfo=timezone.utc))
                st.rerun()
    else:
        _auth.guard("mute tickers", key="snooze")

# ------------------------------------------------------------------ brief
with tab_brief:
    b = q("SELECT day, body, model FROM briefs ORDER BY day DESC LIMIT 7")
    if b.empty:
        empty_state("No daily brief yet",
                    "With an LLM key saved (Settings → AI), the close refresh writes one and "
                    "sends it to your channels.", "summarize")
    else:
        day = st.selectbox("Day", b["day"].astype(str).tolist(), key="brief_day")
        row = b[b["day"].astype(str) == day].iloc[0]
        with card(f"Daily brief · {day}", icon_name="summarize", meta=str(row["model"] or "")):
            st.markdown(md_safe(str(row["body"] or "")))
    if CAN and st.button("Write today's brief now", icon=":material/edit_note:"):
        from bioterm import ai
        from bioterm.ai import jobs

        if not ai.available():
            st.warning("Add an LLM key on the Settings page first.")
        else:
            with st.spinner("Writing…"):
                res = jobs.daily_brief(deliver=False, force=True)
            st.toast("Brief written" if res.get("rows") else f"Skipped: {res.get('skipped')}",
                     icon=":material/summarize:")
            st.rerun()
