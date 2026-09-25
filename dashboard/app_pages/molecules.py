"""Molecules - per-asset tracking: each drug you follow, linked to its trials
(by NCT ID), dated readouts, headlines and publications."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _shared import molecule_links_df, molecule_trials_df, molecules_df, universe_df
from _ui import (MUTED, PHASE_COLORS, card, chart, display_name, empty_state, esc,
                 headline_rows, kpi_row, kv_list, page_header, phase_group, plotly_layout,
                 safe_url, tone_of)
import _auth
from bioterm import store

page_header("Molecules",
            "Every trial, readout, headline and paper for the drugs you follow")

mols = molecules_df()
uni = universe_df()
tickers = uni["ticker"].tolist() if not uni.empty else []
names = dict(zip(uni["ticker"], uni["name"])) if not uni.empty else {}


def _editor(m: dict | None, key: str) -> None:
    """Add (m=None) or edit one molecule. Aliases and NCT IDs are what link the
    molecule to trials, headlines and catalysts - the more names, the more hits."""
    if not _auth.guard("track or edit molecules", key=key):
        return
    with st.form(key, clear_on_submit=m is None, border=False):
        with st.container(horizontal=True, gap="small"):
            tk_opts = tickers or ([m["ticker"]] if m else [])
            tk_ix = tk_opts.index(m["ticker"]) if m and m["ticker"] in tk_opts else None
            tk = st.selectbox("Company", tk_opts, index=tk_ix, placeholder="Ticker",
                              format_func=lambda t: f"{t} · {display_name(names.get(t, ''))}",
                              disabled=m is not None, key=f"{key}_tk")
            name = st.text_input("Molecule", value=m["name"] if m else "",
                                 placeholder="e.g. olezarsen", disabled=m is not None,
                                 key=f"{key}_name")
        aliases = st.text_input(
            "Other names", value=", ".join(m["aliases"]) if m else "",
            placeholder="Code names and brands, comma separated - e.g. AKCEA-APOCIII-LRx, "
                        "Tryngolza", key=f"{key}_aliases")
        with st.container(horizontal=True, gap="small"):
            indication = st.text_input("Indication", value=(m or {}).get("indication") or "",
                                       placeholder="e.g. severe hypertriglyceridemia")
            ncts = st.text_input("Pinned trials", value=", ".join(m["nct_ids"]) if m else "",
                                 placeholder="NCT05079919, NCT05552326", key=f"{key}_ncts",
                                 help="Always tracked, even if the sponsor search misses them")
        notes = st.text_area("Notes", value=(m or {}).get("notes") or "", height=68,
                             placeholder="Mechanism, differentiation, what would move it…")
        if st.form_submit_button("Save molecule" if m else "Track molecule", type="primary",
                                 icon=":material/save:" if m else ":material/add:"):
            if not tk or not name.strip():
                st.warning("A molecule needs a company and a name.")
                return
            store.save_molecule({"id": m["id"] if m else None, "ticker": tk,
                                 "name": name.strip(), "aliases": aliases,
                                 "indication": indication, "nct_ids": ncts, "notes": notes})
            st.cache_data.clear()
            st.toast("Saved — trials and papers are matched on the next data refresh; "
                     "headlines and catalysts on the next fast run.",
                     icon=":material/check_circle:")
            st.rerun()


if mols.empty:
    empty_state("No molecules tracked yet",
                "Track a drug to link it to its trials, readouts, headlines and papers.",
                "science")
    with st.container(horizontal=True, horizontal_alignment="center"):
        if st.button("Import molecules from the watchlist", icon=":material/download:",
                     type="primary", disabled=not _auth.can_edit()):
            n = store.sync_molecules_from_watchlist()
            st.cache_data.clear()
            st.toast(f"Imported {n} molecule{'s' if n != 1 else ''}",
                     icon=":material/check_circle:")
            st.rerun()
    with card("Track a molecule", icon_name="add_circle"):
        _editor(None, "mol_add")
    st.stop()

trials = molecule_trials_df()
today = pd.Timestamp.today().normalize()

# ------------------------------------------------------------------ KPIs
nxt = mols["next_readout"].dropna()
nxt = nxt[nxt >= today]
with kpi_row(4, "mols"):
    st.metric("Molecules tracked", len(mols),
              delta=f"{mols['ticker'].nunique()} companies", delta_color="off",
              delta_arrow="off", border=True)
    st.metric("Active trials", int(pd.to_numeric(mols["n_active"], errors="coerce").sum()),
              delta=f"{len(trials)} linked in total", delta_color="off", delta_arrow="off",
              border=True)
    st.metric("Next primary completion", f"{nxt.min():%b %d, %Y}" if not nxt.empty else "–",
              delta=mols.loc[nxt.idxmin(), "name"] if not nxt.empty else None,
              delta_color="off", delta_arrow="off", border=True)
    st.metric("Headlines · 30 days", int(pd.to_numeric(mols["n_news_30d"],
                                                        errors="coerce").fillna(0).sum()),
              delta=f"{int(pd.to_numeric(mols['papers_total'], errors='coerce').fillna(0).sum())}"
                    " papers indexed", delta_color="off", delta_arrow="off", border=True)

# ------------------------------------------------------------------ table
view = mols.assign(
    phase=mols["top_phase"].fillna("–"),
    trials=[f"{int(a or 0)} active / {int(t or 0)}" for a, t in
            zip(pd.to_numeric(mols["n_active"], errors="coerce").fillna(0),
                pd.to_numeric(mols["n_trials"], errors="coerce").fillna(0))],
    tone=[tone_of(v)[0] if pd.notna(v) else "–" for v in mols["news_tone_30d"]],
    names=[a + [d for d in disc if d not in a] for a, disc in
           zip(mols["aliases"], mols["discovered_aliases"])])
with card("Tracked molecules", icon_name="science", meta="Select a row for its dossier"):
    picked = st.dataframe(
        view[["ticker", "name", "names", "indication", "phase", "trials", "next_readout",
              "n_news_30d", "tone", "papers_total"]],
        hide_index=True, key="mol_table", on_select="rerun", selection_mode="single-row",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", width=70),
            "name": st.column_config.TextColumn("Molecule", width="medium"),
            "names": st.column_config.ListColumn("Also known as", width="medium"),
            "indication": st.column_config.TextColumn("Indication"),
            "phase": st.column_config.TextColumn("Top phase", width=80),
            "trials": st.column_config.TextColumn("Trials", width=100),
            "next_readout": st.column_config.DateColumn("Next readout", format="MMM D, YYYY"),
            "n_news_30d": st.column_config.NumberColumn("News 30d", width=75),
            "tone": st.column_config.TextColumn("Tone", width=80),
            "papers_total": st.column_config.NumberColumn("Papers", width=70,
                                                          help="Europe PMC hits, all time"),
        })
rows = list(getattr(getattr(picked, "selection", None), "rows", []) or [])
ids = mols["id"].tolist()
sel = ids[rows[0]] if rows and rows[0] < len(ids) else None
if sel and st.session_state.get("_mol_last_sel") != sel:
    st.session_state["mol_pick"] = sel
st.session_state["_mol_last_sel"] = sel

# ------------------------------------------------------------------ readout timeline
ahead = trials[(trials["primary_completion_date"] >= today)
               & (trials["primary_completion_date"] <= today + pd.Timedelta(days=548))]
if not ahead.empty:
    label = dict(zip(mols["id"], mols["ticker"] + " · " + mols["name"]))
    ahead = ahead.assign(mol=ahead["molecule_id"].map(label),
                         group=ahead["phase"].map(phase_group))
    with card("Readout timeline", icon_name="timeline",
              meta="Primary completion dates · next 18 months"):
        fig = go.Figure()
        for grp in ["Phase 3", "Phase 2", "Phase 1", "Other"]:
            g = ahead[ahead["group"] == grp]
            if g.empty:
                continue
            fig.add_trace(go.Scatter(
                x=g["primary_completion_date"], y=g["mol"], mode="markers", name=grp,
                marker=dict(size=11, color=PHASE_COLORS[grp], symbol="diamond",
                            line=dict(color="#0B0E14", width=1)),
                customdata=list(zip(g["nct_id"], g["status"], g["title"].str.slice(0, 90))),
                hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]}<br>%{x|%b %d, %Y}"
                              "<br>%{customdata[2]}<extra></extra>"))
        fig.add_vline(x=today, line=dict(color=MUTED, width=1))
        fig.update_layout(**plotly_layout(height=max(220, 34 * ahead["mol"].nunique() + 80)))
        fig.update_yaxes(showgrid=False, tickfont=dict(size=11), autorange="reversed")
        chart(fig, key="mol_timeline")

# ------------------------------------------------------------------ dossier
if st.session_state.get("mol_pick") not in ids:
    st.session_state["mol_pick"] = ids[0]
labels = dict(zip(mols["id"], mols["ticker"] + " · " + mols["name"]))
with card("Dossier", icon_name="folder_open"):
    mid = st.selectbox("Molecule", ids, key="mol_pick", format_func=lambda i: labels[i],
                       width=420, label_visibility="collapsed")
    m = mols[mols["id"] == mid].iloc[0].to_dict()
    tr = trials[trials["molecule_id"] == mid].sort_values("primary_completion_date")
    links = molecule_links_df(mid)
    info, notes_col = st.columns([1, 1.3], gap="medium")
    with info:
        disc = [d for d in (m.get("discovered_aliases") or []) if d not in m["aliases"]]
        kv_list([
            ("Company", f"{m['ticker']} · {display_name(names.get(m['ticker'], ''))}", None),
            ("Indication", m.get("indication") or "–", None),
            ("Your names", ", ".join(m["aliases"]) or "–", None),
            ("Found on ClinicalTrials.gov", ", ".join(disc[:6]) or "–", None),
            ("Pinned trials", ", ".join(m["nct_ids"]) or "–", None),
            ("Most advanced phase", m.get("top_phase") or "–", None),
            ("Next readout", f"{pd.Timestamp(m['next_readout']):%b %d, %Y}"
             if pd.notna(m.get("next_readout")) else "–", None),
            ("Papers (Europe PMC)", str(int(m["papers_total"]))
             if pd.notna(m.get("papers_total")) else "–", None),
        ])
    with notes_col:
        if m.get("notes"):
            st.caption("Notes")
            st.markdown(esc(m["notes"]).replace("$", "\\$"))
        with st.expander("Edit molecule", icon=":material/edit:"):
            _editor(m, f"mol_edit_{mid}")
            if st.button("Stop tracking", icon=":material/delete:", type="tertiary",
                         key=f"mol_del_{mid}", disabled=not _auth.can_edit()):
                store.delete_molecule(mid)
                st.cache_data.clear()
                st.session_state.pop("mol_pick", None)
                st.rerun()

    t_tr, t_news, t_cat, t_pap = st.tabs([
        f":material/biotech: Trials ({len(tr)})",
        f":material/newspaper: Headlines ({int((links['kind'] == 'news').sum()) if not links.empty else 0})",
        f":material/event: Catalysts ({int((links['kind'] == 'catalyst').sum()) if not links.empty else 0})",
        f":material/menu_book: Papers ({int((links['kind'] == 'paper').sum()) if not links.empty else 0})"])
    with t_tr:
        if tr.empty:
            empty_state("No trials linked yet",
                        "Trials are matched by name on the daily refresh — add code names "
                        "or pin NCT IDs to widen the net.", "biotech")
        else:
            st.dataframe(
                tr[["url", "phase", "status", "title", "sponsor", "primary_completion_date",
                    "enrollment", "source"]],
                hide_index=True,
                column_config={
                    "url": st.column_config.LinkColumn("Trial", display_text=r"(NCT\d+)",
                                                       width=110),
                    "phase": st.column_config.TextColumn("Phase", width=70),
                    "status": st.column_config.TextColumn("Status", width=150),
                    "title": st.column_config.TextColumn("Title", width="large"),
                    "sponsor": st.column_config.TextColumn("Sponsor"),
                    "primary_completion_date": st.column_config.DateColumn(
                        "Primary completion", format="MMM D, YYYY"),
                    "enrollment": st.column_config.NumberColumn("Enrollment", format="%d"),
                    "source": st.column_config.TextColumn(
                        "Linked by", width=80, help="pinned = your NCT list · search = "
                                                    "matched by name"),
                })
    with t_news:
        nw = links[links["kind"] == "news"] if not links.empty else links
        if nw.empty:
            empty_state("No headlines name this molecule (90 days)", "", "newspaper")
        else:
            nv = nw.assign(ticker=nw["detail_obj"].map(lambda d: d.get("ticker")),
                           tickers_csv=nw["detail_obj"].map(lambda d: d.get("ticker")),
                           published=nw["date"], source="",
                           event_score=nw["detail_obj"].map(lambda d: d.get("event_score")))
            headline_rows(nv.head(40), time_fmt="%b %d")
    with t_cat:
        ct = links[links["kind"] == "catalyst"] if not links.empty else links
        if ct.empty:
            empty_state("No dated catalysts name this molecule", "", "event_busy")
        else:
            st.dataframe(ct[["date", "title", "url"]], hide_index=True, column_config={
                "date": st.column_config.DateColumn("Date", format="MMM D, YYYY", width=110),
                "title": st.column_config.TextColumn("Catalyst", width="large"),
                "url": st.column_config.LinkColumn("Link", display_text="Open")})
    with t_pap:
        pp = links[links["kind"] == "paper"] if not links.empty else links
        if pp.empty:
            empty_state("No papers indexed yet", "Europe PMC is searched on the daily refresh.",
                        "menu_book")
        else:
            st.html("<div class='bt-list'>" + "".join(
                "<div class='bt-row'><div class='bt-row-l bt-date'>"
                f"<b>{pd.Timestamp(r['date']):%b %Y}</b></div><div class='bt-row-m'>"
                "<div class='bt-row-t'>"
                + (f"<a href='{safe_url(r['url'])}' target='_blank' rel='noopener'>"
                   f"{esc(r['title'])}</a>" if safe_url(r['url']) else esc(r['title']))
                + f"</div><div class='bt-row-s'>{esc((r['detail_obj'] or {}).get('journal', ''))}"
                  "</div></div></div>"
                for _, r in pp.head(20).iterrows() if pd.notna(r["date"])) + "</div>")

with st.expander("Track another molecule", icon=":material/add_circle:"):
    _editor(None, "mol_add")
    if st.button("Import any new molecules from the watchlist", icon=":material/download:",
                 type="tertiary", disabled=not _auth.can_edit()):
        n = store.sync_molecules_from_watchlist()
        st.cache_data.clear()
        st.toast(f"Imported {n} molecule{'s' if n != 1 else ''}", icon=":material/check_circle:")
        st.rerun()
