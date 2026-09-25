"""Workspace - linked panels for one name (pick a ticker once, every panel follows)
or a multi-name monitor; layouts save by name."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import _auth
import _live as live
from _shared import catalysts_df, filings_df, news_df, q, signal_board, trials_df, universe_df
from _ui import (card, catalyst_rows, display_name, empty_state, headline_rows, kv_list,
                 md_safe, page_header, signal_badge, usd)

page_header("Workspace", "Linked panels for one name, or a monitor across several · save "
                         "layouts by name")

PANELS = ["Chart", "Key stats", "Signal evidence", "Catalysts", "News", "Filings", "Trials",
          "Why it moved"]
DEFAULT = {"mode": "Linked", "panels": ["Chart", "Key stats", "Catalysts", "News",
                                        "Signal evidence", "Why it moved"],
           "cols": 2, "tickers": []}

uni = universe_df()
if uni.empty:
    empty_state("No universe yet", "The first data refresh builds it.", "dashboard")
    st.stop()
tickers = uni["ticker"].tolist()
names = dict(zip(uni["ticker"], uni["name"].map(display_name)))

saved = q("SELECT id, name, layout FROM workspaces ORDER BY name")
lay = st.session_state.setdefault("ws_layout", dict(DEFAULT))

with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    if not saved.empty:
        pick = st.selectbox("Saved layout", ["—"] + saved["name"].tolist(), key="ws_saved",
                            width=240)
        if pick != "—" and st.button("Load", icon=":material/download:"):
            st.session_state["ws_layout"] = {**DEFAULT, **json.loads(
                saved[saved["name"] == pick].iloc[0]["layout"] or "{}")}
            st.rerun()
    lay["mode"] = st.segmented_control("Mode", ["Linked", "Monitor"], default=lay["mode"],
                                       required=True, key="ws_mode")
    lay["cols"] = st.segmented_control("Columns", [1, 2, 3], default=lay["cols"],
                                       required=True, key="ws_cols")

if lay["mode"] == "Linked":
    qp = st.query_params.get("ticker", "").upper()
    start = qp if qp in tickers else (st.session_state.get("ws_ticker") or tickers[0])
    tk = st.selectbox("Ticker", tickers, index=tickers.index(start) if start in tickers else 0,
                      format_func=lambda t: f"{t} · {names.get(t, '')}", key="ws_ticker",
                      width=420)
    lay["panels"] = st.multiselect("Panels", PANELS, default=[p for p in lay["panels"]
                                                             if p in PANELS], key="ws_panels")
    cols = st.columns(lay["cols"], gap="medium")
    board = signal_board()
    brow = board[board["ticker"] == tk]
    for i, panel in enumerate(lay["panels"]):
        with cols[i % lay["cols"]]:
            with card(panel, icon_name={"Chart": "candlestick_chart", "Key stats": "analytics",
                                        "Signal evidence": "swap_vert",
                                        "Catalysts": "event", "News": "newspaper",
                                        "Filings": "description", "Trials": "biotech",
                                        "Why it moved": "bolt"}[panel]):
                if panel == "Chart":
                    import _charts

                    h, src = live.history(tk, "1y")
                    if h.empty:
                        st.caption("No prices.")
                    else:
                        _charts.pro_chart(live.indicators(h), height=360, show_rsi=False)
                        st.caption(live.source_note(src))
                elif panel == "Key stats":
                    qd = live.quote(tk) or {}
                    f = q("SELECT market_cap, cash, runway_quarters, short_percent_float "
                          "FROM fundamentals WHERE ticker = :t", {"t": tk})
                    fr = f.iloc[0].to_dict() if not f.empty else {}
                    kv_list([
                        ("Last", f"${qd['price']:,.2f} ({qd['change_pct']:+.2%})"
                         if qd.get("price") and qd.get("change_pct") == qd.get("change_pct")
                         else "–", None),
                        ("Market cap", usd(fr.get("market_cap")), None),
                        ("Cash", usd(fr.get("cash")), None),
                        ("Runway", f"{fr['runway_quarters']:.1f} quarters"
                         if pd.notna(fr.get("runway_quarters")) else "–", None),
                        ("Short % float", f"{fr['short_percent_float']:.1%}"
                         if pd.notna(fr.get("short_percent_float")) else "–", None),
                        ("Signal", str(brow.iloc[0]["label"]) if not brow.empty else "–",
                         None)])
                elif panel == "Signal evidence":
                    if brow.empty:
                        st.caption("No signal yet.")
                    else:
                        st.html(signal_badge(brow.iloc[0]["label"]))
                        for e in (brow.iloc[0].get("top_obj") or [])[:6]:
                            st.markdown(f"- {'▲' if e.get('side') == 'BUY' else '▼'} "
                                        f"{md_safe(str(e.get('title', '')))}")
                elif panel == "Catalysts":
                    c = catalysts_df()
                    c = c[(c["ticker"] == tk) & (c["date"] >= pd.Timestamp.today()
                                                 - pd.Timedelta(days=7))].head(8)
                    catalyst_rows(c) if not c.empty else st.caption("None dated.")
                elif panel == "News":
                    n = news_df()
                    n = n[n["tickers_csv"].fillna("").str.contains(tk)].head(8) \
                        if not n.empty else n
                    headline_rows(n) if not n.empty else st.caption("No recent headlines.")
                elif panel == "Filings":
                    fl = filings_df(tk).head(10)
                    if fl.empty:
                        st.caption("No filings.")
                    else:
                        st.dataframe(fl[["filed_date", "form", "items", "url"]],
                                     hide_index=True, width="stretch", column_config={
                                         "url": st.column_config.LinkColumn(
                                             "", display_text="Open")})
                elif panel == "Trials":
                    tr = trials_df(tk)
                    if tr.empty:
                        st.caption("No trials.")
                    else:
                        st.dataframe(tr[["nct_id", "phase", "status",
                                         "primary_completion_date"]].head(12),
                                     hide_index=True, width="stretch")
                elif panel == "Why it moved":
                    from bioterm.realtime import why

                    items = why(tk, hours=72)
                    if not items:
                        st.caption("No halts, filings, headlines or trial changes in 72 hours.")
                    for it in items:
                        st.markdown(f"- **{it['kind']}** · {md_safe(it['text'][:180])}")
else:
    wl = q("SELECT ticker FROM watchlist ORDER BY ticker")["ticker"].tolist()
    lay["tickers"] = st.multiselect("Names", tickers,
                                    default=[t for t in (lay.get("tickers") or wl[:6])
                                             if t in tickers][:12],
                                    max_selections=12, key="ws_names",
                                    format_func=lambda t: f"{t} · {names.get(t, '')}")
    qs = live.quotes(lay["tickers"])
    board = signal_board().set_index("ticker") if not signal_board().empty else pd.DataFrame()
    cats = catalysts_df()
    cols = st.columns(lay["cols"], gap="small")
    for i, t in enumerate(lay["tickers"]):
        with cols[i % lay["cols"]]:
            qd = qs.get(t) or {}
            with st.container(border=True):
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.page_link("app_pages/stock.py", label=f"**{t}**",
                                 query_params={"ticker": t})
                    st.space("stretch")
                    if not board.empty and t in board.index:
                        st.html(signal_badge(board.loc[t, "label"]))
                pc = qd.get("change_pct")
                st.metric(names.get(t, t)[:28], f"${qd['price']:,.2f}" if qd.get("price")
                          else "–", delta=f"{pc:+.2%}" if pc == pc and pc is not None else None)
                nxt = cats[(cats["ticker"] == t) & (cats["date"] >= pd.Timestamp.today())] \
                    .head(1) if not cats.empty else cats
                if not nxt.empty:
                    r = nxt.iloc[0]
                    st.caption(f"Next: {r['type'].replace('_', ' ')} · "
                               f"{pd.Timestamp(r['date']):%b %d}")

if _auth.can_edit():
    with st.popover("Save layout", icon=":material/save:"):
        name = st.text_input("Layout name", key="ws_save_name")
        if st.button("Save", type="primary", key="ws_save_btn") and name.strip():
            from bioterm.db import bulk_upsert, workspaces

            ex = saved[saved["name"] == name.strip()] if not saved.empty else saved
            wid = ex.iloc[0]["id"] if not ex.empty else uuid.uuid4().hex[:12]
            bulk_upsert(workspaces, [{"id": wid, "name": name.strip()[:80],
                                      "layout": json.dumps(lay),
                                      "updated_at": datetime.now(timezone.utc)}])
            st.toast("Layout saved", icon=":material/check_circle:")
            st.rerun()
