"""Screener - filter the universe on fundamentals, catalysts, ownership, signals and
the dilution / takeout screens; save screens and get alerted when a name enters."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import _auth
from _ui import card, empty_state, kpi_row, page_header

page_header("Screener", "Filter on cash, catalysts, ownership, signals and the dilution / "
                        "takeout screens · save screens and get alerted on new entries")

from bioterm import screener as sc  # noqa: E402

LABELS = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]
PHASES = ["approved", "P3", "P2/P3", "P2", "P1/P2", "P1"]


@st.cache_data(ttl=300, show_spinner="Building the screen…")
def _frame() -> pd.DataFrame:
    return sc.frame()


df = _frame()
if df.empty:
    empty_state("Nothing to screen yet", "The first data refresh builds the universe.",
                "filter_alt")
    st.stop()

state = st.session_state.setdefault("scr_filters", [])

# ------------------------------------------------------------------ presets + saved
saved = sc.list_screens()
with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    preset = st.selectbox("Start from", ["—"] + list(sc.PRESETS) +
                          ([f"★ {n}" for n in saved["name"]] if not saved.empty else []),
                          key="scr_preset", width=320)
    if st.button("Load", icon=":material/download:", disabled=preset == "—"):
        if preset.startswith("★ "):
            row = saved[saved["name"] == preset[2:]].iloc[0]
            st.session_state["scr_filters"] = json.loads(row["filters"] or "[]")
        else:
            st.session_state["scr_filters"] = [dict(f) for f in sc.PRESETS[preset]]
        st.rerun()
    if st.button("Clear", icon=":material/filter_alt_off:", type="tertiary"):
        st.session_state["scr_filters"] = []
        st.rerun()

# ------------------------------------------------------------------ builder
with card("Conditions", icon_name="tune", meta="all conditions must hold"):
    fields = list(sc.FIELDS)
    for i, f in enumerate(list(state)):
        label, kind, help_ = sc.FIELDS.get(f["field"], (f["field"], "num", ""))
        with st.container(horizontal=True, vertical_alignment="center", gap="small",
                          key=f"scr_row_{i}"):
            st.markdown(f"**{label}**")
            v = f.get("value")
            if kind == "bool":
                txt = "yes" if v else "no"
            elif isinstance(v, list):
                txt = ", ".join(str(x) for x in v) if f["op"] == "in" else \
                    f"{v[0]:,.4g} – {v[1]:,.4g}"
            else:
                txt = f"{float(v):,.4g}" if isinstance(v, (int, float)) else str(v)
            st.caption(f"{f['op']} {txt}")
            st.space("stretch")
            if st.button("Remove", icon=":material/close:", key=f"scr_del_{i}",
                         type="tertiary"):
                state.pop(i)
                st.rerun()
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        fld = st.selectbox("Field", fields, format_func=lambda k: sc.FIELDS[k][0],
                           key="scr_new_field", width=260)
        label, kind, help_ = sc.FIELDS[fld]
        op = st.selectbox("Condition", sc.OPS.get(kind, [">="]), key="scr_new_op", width=120)
        if kind == "bool":
            val = st.segmented_control("Value", [True, False], default=True, required=True,
                                       format_func=lambda b: "Yes" if b else "No",
                                       key="scr_new_bool")
        elif kind == "label":
            val = st.multiselect("Value", LABELS, default=["BUY", "STRONG BUY"],
                                 key="scr_new_lab", width=320)
        elif kind == "text":
            opts = PHASES if fld == "top_phase" else sorted(
                df[fld].dropna().astype(str).unique().tolist())
            val = st.multiselect("Value", opts, key="scr_new_txt", width=320)
        elif op == "between":
            c1, c2 = st.columns(2)
            lo = c1.number_input("From", value=0.0, key="scr_new_lo", format="%g")
            hi = c2.number_input("To", value=1.0, key="scr_new_hi", format="%g")
            val = [lo, hi]
        else:
            s = pd.to_numeric(df[fld], errors="coerce").dropna()
            default = float(s.median()) if not s.empty else 0.0
            val = st.number_input("Value", value=round(default, 4), key="scr_new_val",
                                  format="%g", help=help_ or None)
        if st.button("Add", icon=":material/add:", type="primary"):
            state.append({"field": fld, "op": op, "value": val})
            st.rerun()

res = sc.apply(df, state)
with kpi_row(4, "scr"):
    st.metric("Matches", len(res), delta=f"of {len(df)} names", delta_color="off",
              border=True)
    st.metric("Median market cap", f"${res['market_cap'].median() / 1e9:,.2f}B"
              if not res.empty and res["market_cap"].notna().any() else "—", border=True)
    st.metric("Below cash", int(res["below_cash"].fillna(False).sum()) if not res.empty else 0,
              border=True)
    st.metric("Binary event in 90 days",
              int(res["binary_within_90d"].fillna(False).sum()) if not res.empty else 0,
              border=True)

COLS = ["ticker", "name", "market_cap", "ev", "runway_quarters", "signal", "focus_rank",
        "next_catalyst_days", "next_catalyst_type", "top_phase", "dilution_risk",
        "takeout_score", "funds_net", "short_pct_float", "ret_3m"]
with card("Results", icon_name="table_rows", meta="click a column to sort"):
    if res.empty:
        st.caption("No names match - remove a condition.")
    else:
        view = res[[c for c in COLS if c in res]].sort_values("market_cap", ascending=False)
        view.insert(0, "open", "Stock_Detail?ticker=" + view["ticker"])
        st.dataframe(view, hide_index=True, width="stretch", height=520, column_config={
            "open": st.column_config.LinkColumn("", display_text="Open", width=60),
            "ticker": st.column_config.TextColumn("Ticker", width=72),
            "name": st.column_config.TextColumn("Company", width="medium"),
            "market_cap": st.column_config.NumberColumn("Mkt cap", format="compact"),
            "ev": st.column_config.NumberColumn("EV", format="compact"),
            "runway_quarters": st.column_config.NumberColumn("Runway q", format="%.1f"),
            "signal": "Signal", "focus_rank": st.column_config.NumberColumn("Focus #",
                                                                           format="%d"),
            "next_catalyst_days": st.column_config.NumberColumn("Catalyst in", format="%d d"),
            "next_catalyst_type": "Next catalyst", "top_phase": "Top phase",
            "dilution_risk": st.column_config.ProgressColumn("Dilution risk", min_value=0,
                                                             max_value=1, format="%.2f"),
            "takeout_score": st.column_config.ProgressColumn("Takeout profile", min_value=0,
                                                             max_value=1, format="%.2f"),
            "funds_net": st.column_config.NumberColumn("Funds net", format="%+d"),
            "short_pct_float": st.column_config.NumberColumn("Short %", format="percent"),
            "ret_3m": st.column_config.NumberColumn("3m", format="percent")})
        st.download_button("Export CSV", res.to_csv(index=False), "bioterm_screen.csv",
                           "text/csv", icon=":material/download:", type="tertiary")

with card("Save this screen", icon_name="bookmark_add"):
    if _auth.guard("save screens", key="scr"):
        with st.form("scr_save", border=False, clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            name = c1.text_input("Name", placeholder="e.g. Funded, below cash, P3")
            alert = c2.toggle("Alert on new entries", value=True)
            if st.form_submit_button("Save screen", type="primary", icon=":material/save:"):
                if not name.strip() or not state:
                    st.warning("Give it a name and at least one condition.")
                else:
                    sc.save_screen(name.strip(), state, alert=alert)
                    st.toast("Screen saved", icon=":material/check_circle:")
                    st.rerun()
    if not saved.empty:
        st.caption("Saved screens")
        for r in saved.itertuples():
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                n = len(json.loads(r.members or "[]")) if r.alert else None
                st.markdown(f"**{r.name}**" + (" · :material/notifications_active: alerts"
                                               if r.alert else "")
                            + (f" · {n} names at last check" if n is not None else ""))
                st.space("stretch")
                if st.button("Delete", key=f"scr_rm_{r.id}", icon=":material/delete:",
                             type="tertiary", disabled=not _auth.can_edit()):
                    sc.delete_screen(r.id)
                    st.rerun()

st.caption("Dilution risk and takeout profile are transparent screening heuristics (see "
           "bioterm/screener.py), not forecasts.")
