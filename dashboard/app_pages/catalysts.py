"""Catalyst calendar - every dated catalyst in the horizon."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import catalysts_df, scores_df, universe_df
from _ui import (CATALYST_TYPES, FAMILIES, MUTED, card, catalyst_family, catalyst_label,
                 catalyst_title, chart, empty_state, kpi_row, label, md_safe, page_header,
                 plotly_layout)
import _auth
from bioterm import store

CATALYST_KEYS = list(CATALYST_TYPES)
TYPE_LABELS = [v[0] for v in CATALYST_TYPES.values()]
TYPE_COLORS = [FAMILIES[catalyst_family(k)][2] for k in CATALYST_TYPES]
FAMILY_ORDER = ["regulatory", "clinical", "corporate"]

page_header("Catalyst calendar",
            "Every dated catalyst in the horizon — trial readouts, FDA actions, earnings")

cats = catalysts_df()

# ------------------------------------------------------------------ toolbar
with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    horizon = st.segmented_control("Horizon", [1, 3, 6, 9, 12], default=6, required=True,
                                   format_func=lambda m: f"{m} mo",
                                   help="How far ahead to look")
    fams = st.pills("Families", FAMILY_ORDER, selection_mode="multi", default=FAMILY_ORDER,
                    format_func=lambda f: FAMILIES[f][0],
                    help="Regulatory = PDUFA, AdCom, FDA actions · Clinical = trial "
                         "readouts and data · Corporate = earnings and other")
    only_wl = st.toggle("Watchlist only", value=False)
    st.space("stretch")
    with st.popover("Pin a catalyst", icon=":material/push_pin:"):
        st.caption("Dates you know from your own research — PDUFA, AdCom, expected "
                   "readouts. They feed the Focus Score on the next refresh.")
        _can = _auth.guard("pin catalysts", key="cal")
        with st.form("add_cat_cal", clear_on_submit=True, border=False):
            _tk = st.selectbox("Ticker", universe_df()["ticker"].tolist())
            _ty = st.selectbox("Type", CATALYST_KEYS, format_func=catalyst_label)
            _dt = st.date_input("Date")
            _cf = st.segmented_control("Confidence", ["low", "medium", "high"],
                                       default="medium", required=True)
            _ti = st.text_input("What happens")
            _ur = st.text_input("Source link (optional)")
            if st.form_submit_button("Add catalyst", type="primary", disabled=not _can,
                                     icon=":material/add:") and _ti and _auth.can_edit():
                store.add_manual_catalyst(_tk, _ty, _dt, _ti, _cf, _ur)
                st.cache_data.clear()
                st.toast(f"Pinned for {_tk}", icon=":material/check_circle:")
                st.rerun()
        _manual = store.get_manual_catalysts()
        if _manual:
            st.caption("Pinned by you")
            for mc in _manual:
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    st.markdown(f"**{mc['date']}** · `{mc['ticker']}` · "
                                f"{catalyst_label(mc['type'])} · {md_safe(mc['title'])}")
                    st.space("stretch")
                    if st.button("Delete", key=f"delc_{mc['id']}", icon=":material/delete:",
                                 type="tertiary", disabled=not _can):
                        store.delete_manual_catalyst(mc["id"])
                        st.cache_data.clear()
                        st.rerun()

if cats.empty:
    empty_state("No catalysts derived yet",
                "They're built from trial completion dates, news and earnings on each "
                "refresh.", "event_busy")
    st.stop()

scores = scores_df()[["ticker", "focus_score", "rank", "is_watchlist"]]
cats = cats.merge(scores, on="ticker", how="left")
cats["family"] = cats["type"].map(catalyst_family)

view = cats[(cats["months_away"] >= -0.5) & (cats["months_away"] <= horizon)]
view = view[view["family"].isin(fams or [])]
if only_wl:
    view = view[view["is_watchlist"] == 1]
view = view.sort_values("date")

if view.empty:
    empty_state("No catalysts match these filters",
                "Widen the horizon or select more families.", "filter_alt_off")
    st.stop()

# ------------------------------------------------------------------ summary
today = pd.Timestamp.today().normalize()
with kpi_row(5, "cal"):
    st.metric("Catalysts", len(view), delta=f"{view['ticker'].nunique()} companies",
              delta_color="off", delta_arrow="off", border=True)
    st.metric("Next 7 days",
              int(((view["date"] >= today) & (view["date"] <= today + pd.Timedelta(days=7))).sum()),
              border=True)
    for fam in FAMILY_ORDER:
        st.metric(FAMILIES[fam][0], int((view["family"] == fam).sum()), border=True)

# ------------------------------------------------------------------ density
wk = view.assign(week=view["date"].dt.to_period("W").dt.start_time)
counts = wk.groupby(["week", "family"]).size().unstack(fill_value=0)
with card("Catalysts per week", icon_name="bar_chart",
          meta="Stacked by family · hover a bar for the count"):
    fig = go.Figure()
    for fam in FAMILY_ORDER:
        if fam in counts:
            fig.add_trace(go.Bar(
                x=counts.index, y=counts[fam], name=FAMILIES[fam][0],
                marker=dict(color=FAMILIES[fam][1], line=dict(color="#0B0E14", width=1)),
                hovertemplate="%{x|Week of %b %d}: %{y}<extra>" + FAMILIES[fam][0] + "</extra>"))
    fig.add_vline(x=today, line=dict(color=MUTED, width=1))
    fig.update_layout(**plotly_layout(height=230, barmode="stack", bargap=0.3,
                                      barcornerradius=3))
    chart(fig, key="density")

# ------------------------------------------------------------------ detail
tab_month, tab_co = st.tabs([":material/calendar_month: By month",
                             ":material/view_timeline: By company"])

with tab_month:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("Sorted by date. Click a column header to re-sort; use the table's search "
                   "to find a name.")
        st.space("stretch")
        st.download_button(
            "Export CSV",
            view[["date", "ticker", "type", "title", "months_away", "confidence", "source",
                  "url"]].to_csv(index=False),
            "bioterm_catalysts.csv", "text/csv", icon=":material/download:", type="tertiary")
    months = view.assign(month=view["date"].dt.to_period("M"))
    for month, grp in months.groupby("month"):
        label(month.strftime("%B %Y"), f"{len(grp)} catalysts · {grp['ticker'].nunique()} companies")
        st.dataframe(
            grp.assign(type_badge=grp["type"].map(lambda t: [catalyst_label(t)]),
                       title=grp["title"].map(catalyst_title))
            [["date", "ticker", "type_badge", "title", "confidence", "rank", "url"]],
            hide_index=True,
            column_config={
                "date": st.column_config.DateColumn("Date", format="ddd, MMM D", width=110),
                "ticker": st.column_config.TextColumn("Ticker", width=72),
                "type_badge": st.column_config.MultiselectColumn(
                    "Type", options=TYPE_LABELS, color=TYPE_COLORS, width=160),
                "title": st.column_config.TextColumn("Detail", width="large"),
                "confidence": st.column_config.TextColumn("Confidence", width=90),
                "rank": st.column_config.NumberColumn("Focus #", format="%d", width=70),
                "url": st.column_config.LinkColumn("Source", display_text="Open", width=70),
            })

with tab_co:
    order = view.groupby("ticker")["date"].min().sort_values().index.tolist()
    fig = go.Figure()
    for fam in FAMILY_ORDER:
        sub = view[view["family"] == fam]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["date"], y=sub["ticker"], mode="markers", name=FAMILIES[fam][0],
            marker=dict(color=FAMILIES[fam][1],
                        size=(sub["focus_score"].fillna(0.1).clip(lower=0.05) * 16 + 7),
                        line=dict(color="#0B0E14", width=1.5), opacity=0.95),
            customdata=list(zip(sub["type"].map(catalyst_label),
                                sub["title"].map(lambda s: catalyst_title(s)[:90]),
                                sub["confidence"].fillna(""))),
            hovertemplate="<b>%{y}</b> · %{customdata[0]}<br>%{x|%b %d, %Y} · "
                          "%{customdata[2]} confidence<br>%{customdata[1]}<extra></extra>"))
    fig.add_vline(x=today, line=dict(color=MUTED, width=1))
    fig.update_yaxes(categoryorder="array", categoryarray=order[::-1], showgrid=True,
                     gridcolor="#141A24", tickfont=dict(size=11, family="JetBrains Mono"))
    fig.update_xaxes(showgrid=True, gridcolor="#1A2230")
    fig.update_layout(**plotly_layout(height=max(320, 19 * len(order) + 80)))
    st.caption("One row per company, ordered by its next catalyst. Marker size = Focus Score.")
    chart(fig, key="timeline")
