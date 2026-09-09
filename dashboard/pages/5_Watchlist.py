"""Edit your watchlist - conviction feeds the Focus Score. Persists to config/watchlist.yml."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import yaml

from _shared import disclaimer, scores_df, sidebar_freshness, universe_df
from bioterm.config import CONFIG_DIR, load_settings

st.title("Watchlist")
disclaimer()
sidebar_freshness()

st.markdown(
    "Your conviction (1–5) is **your** read on whether the science works. It multiplies "
    "the Focus Score (`config/settings.yml → score.conviction_map`), so a 5-conviction "
    "name with a near catalyst rises to the top; a 1 sinks. Edits save to "
    "`config/watchlist.yml` — re-run `bioterm score` to apply."
)

cfg = load_settings()
current = pd.DataFrame(cfg.watchlist)
if current.empty:
    current = pd.DataFrame(columns=["ticker", "conviction", "thesis", "molecules"])
if "molecules" in current:
    current["molecules"] = current["molecules"].apply(
        lambda x: ", ".join(x) if isinstance(x, list) else (x or ""))

scores = scores_df().set_index("ticker")
current["current_focus_rank"] = current["ticker"].map(
    lambda t: int(scores.loc[t, "rank"]) if t in scores.index else None)

edited = st.data_editor(
    current, num_rows="dynamic", use_container_width=True, hide_index=True,
    column_config={
        "ticker": st.column_config.TextColumn("ticker", required=True),
        "conviction": st.column_config.NumberColumn("conviction", min_value=1,
                                                    max_value=5, step=1, default=3),
        "thesis": st.column_config.TextColumn("thesis", width="large"),
        "molecules": st.column_config.TextColumn("molecules (comma-sep)", width="medium"),
        "current_focus_rank": st.column_config.NumberColumn("focus rank", disabled=True),
    },
)

col1, col2 = st.columns([1, 4])
if col1.button("💾 save watchlist", type="primary"):
    out = []
    known = set(universe_df()["ticker"])
    unknown = []
    for _, r in edited.iterrows():
        tk = str(r["ticker"]).strip().upper()
        if not tk:
            continue
        entry = {"ticker": tk, "conviction": int(r["conviction"]) if pd.notna(r["conviction"]) else 3}
        if isinstance(r.get("thesis"), str) and r["thesis"].strip():
            entry["thesis"] = r["thesis"].strip()
        mol = r.get("molecules")
        if isinstance(mol, str) and mol.strip():
            entry["molecules"] = [m.strip() for m in mol.split(",") if m.strip()]
        out.append(entry)
        if tk not in known:
            unknown.append(tk)
    (CONFIG_DIR / "watchlist.yml").write_text(
        "# BioTerm watchlist - edited via the dashboard\n"
        + yaml.safe_dump({"watchlist": out}, sort_keys=False, allow_unicode=True)
    )
    st.cache_data.clear()
    st.success(f"saved {len(out)} names to config/watchlist.yml")
    if unknown:
        st.info("not in the current universe yet (will be added on next "
                f"`bioterm universe`): {', '.join(unknown)}")
    st.caption("Now run `bioterm ingest --only clinical,news,catalysts,score` "
               "(or wait for the scheduler) to fold them in.")

col2.caption("Add a row at the bottom of the table to track a new name.")
