"""Edit your watchlist - conviction feeds the Focus Score. Persists to the database."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import scores_df, universe_df
from _ui import page_setup
from bioterm import store

page_setup("Watchlist",
           "your conviction (1–5) multiplies the Focus Score · edits persist to the "
           "database and apply on the next refresh")

current = pd.DataFrame(store.get_watchlist())
if current.empty:
    current = pd.DataFrame(columns=["ticker", "conviction", "thesis", "molecules"])
current["molecules"] = current["molecules"].apply(
    lambda x: ", ".join(x) if isinstance(x, list) else (x or ""))

scores = scores_df().set_index("ticker")
current["focus_rank"] = current["ticker"].map(
    lambda t: int(scores.loc[t, "rank"]) if t in scores.index else None)

edited = st.data_editor(
    current[["ticker", "conviction", "thesis", "molecules", "focus_rank"]],
    num_rows="dynamic", use_container_width=True, hide_index=True, key="wl_editor",
    column_config={
        "ticker": st.column_config.TextColumn("ticker", required=True),
        "conviction": st.column_config.NumberColumn(
            "conviction", min_value=1, max_value=5, step=1, default=3),
        "thesis": st.column_config.TextColumn("thesis", width="large"),
        "molecules": st.column_config.TextColumn("molecules (comma-sep)", width="medium"),
        "focus_rank": st.column_config.NumberColumn("focus rank", disabled=True),
    },
)

c1, c2 = st.columns([1, 4])
if c1.button("💾 save watchlist", type="primary"):
    entries, unknown, known = [], [], set(universe_df()["ticker"])
    for _, r in edited.iterrows():
        tk = str(r["ticker"]).strip().upper()
        if not tk:
            continue
        entries.append({
            "ticker": tk,
            "conviction": int(r["conviction"]) if pd.notna(r["conviction"]) else 3,
            "thesis": (r.get("thesis") or "").strip(),
            "molecules": [m.strip() for m in str(r.get("molecules") or "").split(",") if m.strip()],
        })
        if tk not in known:
            unknown.append(tk)
    n = store.save_watchlist(entries)
    st.cache_data.clear()
    st.success(f"saved {n} names")
    if unknown:
        st.info("not in the universe yet (added on the next `bioterm universe` / full "
                f"refresh): {', '.join(unknown)}")
    st.rerun()

c2.caption("Add a row at the bottom of the table to track a new name. "
           "The YAML file `config/watchlist.yml` is only the initial seed now.")
