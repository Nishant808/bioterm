"""Watchlist - your names and conviction. Conviction multiplies the Focus Score;
edits persist to the database."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import scores_df, universe_df
from _ui import card, kpi_row, page_header
from bioterm import store

page_header("Watchlist",
            "Your conviction (1–5) multiplies the Focus Score · saved to the database and "
            "applied on the next refresh")

current = pd.DataFrame(store.get_watchlist())
if current.empty:
    current = pd.DataFrame(columns=["ticker", "conviction", "thesis", "molecules"])
current["molecules"] = current["molecules"].apply(
    lambda x: ", ".join(x) if isinstance(x, list) else (x or ""))

scores = scores_df().set_index("ticker")
current["focus_rank"] = current["ticker"].map(
    lambda t: int(scores.loc[t, "rank"]) if t in scores.index else None)

with kpi_row(3, "wl"):
    st.metric("Names", len(current), border=True)
    st.metric("In the top 20", int((current["focus_rank"].fillna(999) <= 20).sum()),
              border=True)
    st.metric("High conviction (4–5)",
              int((pd.to_numeric(current["conviction"], errors="coerce") >= 4).sum()),
              border=True)

with card("Your names", icon_name="bookmark_star",
          meta="Edit cells directly · add a row at the bottom for a new name"):
    edited = st.data_editor(
        current[["ticker", "conviction", "thesis", "molecules", "focus_rank"]],
        num_rows="dynamic", hide_index=True, key="wl_editor",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", required=True, width=90),
            "conviction": st.column_config.NumberColumn(
                "Conviction", min_value=1, max_value=5, step=1, default=3, width=100,
                help="1 = skeptical · 3 = neutral · 5 = high conviction"),
            "thesis": st.column_config.TextColumn("Thesis", width="large"),
            "molecules": st.column_config.TextColumn("Molecules (comma-separated)",
                                                     width="medium"),
            "focus_rank": st.column_config.NumberColumn("Focus rank", disabled=True,
                                                        width=90),
        },
    )

    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        save = st.button("Save watchlist", type="primary", icon=":material/save:")
        st.caption("Names not yet in the universe are added on the next full refresh. "
                   "`config/watchlist.yml` is only the initial seed.")

if save:
    entries, unknown, known = [], [], set(universe_df()["ticker"])
    for _, r in edited.iterrows():
        tk = str(r["ticker"]).strip().upper()
        if not tk:
            continue
        entries.append({
            "ticker": tk,
            "conviction": int(r["conviction"]) if pd.notna(r["conviction"]) else 3,
            "thesis": (r.get("thesis") or "").strip(),
            "molecules": [m.strip() for m in str(r.get("molecules") or "").split(",")
                          if m.strip()],
        })
        if tk not in known:
            unknown.append(tk)
    n = store.save_watchlist(entries)
    st.cache_data.clear()
    st.toast(f"Saved {n} names", icon=":material/check_circle:")
    if unknown:
        st.toast("Not in the universe yet (added on the next full refresh): "
                 + ", ".join(unknown), icon=":material/info:")
    st.rerun()
