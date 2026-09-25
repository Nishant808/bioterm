"""Data health - ingestion runs, freshness of every source, data-quality checks,
storage and provider circuit breakers. The page to open when a number looks off."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from _shared import q
from _ui import (MUTED, NEG, POS, WARN, card, empty_state, esc, kpi_row, page_header,
                 status_rows)

page_header("Data health", "Ingestion runs · source freshness · data-quality checks · storage")

FRESH = [  # (label, sql, max age in days before it's flagged)
    ("Daily prices", "SELECT MAX(date) AS t FROM prices", 4),
    ("Technicals", "SELECT MAX(date) AS t FROM technicals", 4),
    ("Fundamentals", "SELECT MAX(updated_at) AS t FROM fundamentals", 3),
    ("Clinical trials", "SELECT MAX(fetched_at) AS t FROM clinical_trials", 3),
    ("SEC filings", "SELECT MAX(filed_date) AS t FROM filings", 4),
    ("News", "SELECT MAX(published) AS t FROM news", 2),
    ("Insider trades (Form 4)", "SELECT MAX(filed_date) AS t FROM insider_txns", 7),
    ("13F holdings", "SELECT MAX(filed_date) AS t FROM inst_holdings", 120),
    ("FINRA short volume", "SELECT MAX(date) AS t FROM short_volume", 5),
    ("Options snapshots", "SELECT MAX(date) AS t FROM options_snapshots", 5),
    ("Trading halts", "SELECT MAX(fetched_at) AS t FROM halts", 3),
    ("Focus scores", "SELECT MAX(asof) AS t FROM scores", 3),
    ("Signals", "SELECT MAX(asof) AS t FROM signal_scores", 4),
    ("AI news events", "SELECT MAX(scored_at) AS t FROM news_llm", 7),
]


def _fresh_rows() -> pd.DataFrame:
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    out = []
    for lab, sql, max_age in FRESH:
        try:
            t = pd.to_datetime(q(sql).iloc[0]["t"], errors="coerce", utc=True)
            t = t.tz_localize(None) if t is not None and pd.notna(t) else None
        except Exception:  # noqa: BLE001
            t = None
        age = (now - t).total_seconds() / 86400 if t is not None else None
        state = "missing" if t is None else ("stale" if age > max_age else "ok")
        out.append({"source": lab, "latest": t, "age_days": age, "state": state})
    return pd.DataFrame(out)


runs = q("SELECT job, started_at, finished_at, status, rows, detail FROM ingest_runs "
         "ORDER BY started_at DESC LIMIT 400")
fresh = _fresh_rows()
try:
    dq = q("SELECT run_at, \"check\", status, count, detail FROM dq_checks "
           "WHERE run_at = (SELECT MAX(run_at) FROM dq_checks)")
except Exception:  # noqa: BLE001
    dq = pd.DataFrame()

last = runs.sort_values("started_at").groupby("job").last() if not runs.empty else runs
n_err = int((last["status"] == "error").sum()) if not runs.empty else 0
with kpi_row(4, "health"):
    st.metric("Jobs failing now", n_err, border=True)
    st.metric("Sources fresh", f"{int((fresh['state'] == 'ok').sum())}/{len(fresh)}",
              border=True)
    st.metric("Data-quality checks passing",
              f"{int((dq['status'] == 'ok').sum())}/{len(dq)}" if not dq.empty else "—",
              border=True)
    st.metric("Runs logged (recent)", len(runs), border=True)

c1, c2 = st.columns([1.1, 1])
with c1:
    with card("Source freshness", icon_name="schedule"):
        items = []
        for r in fresh.itertuples():
            col = {"ok": POS, "stale": WARN, "missing": MUTED}[r.state]
            when = f"{r.latest:%b %d %H:%M} UTC" if pd.notna(r.latest) else "never"
            age = f"{r.age_days:.1f} days old" if pd.notna(r.age_days) else "no data yet"
            items.append((col, r.source, f"{when} · {age}"))
        status_rows(items)
with c2:
    with card("Latest run per job", icon_name="sync"):
        if runs.empty:
            empty_state("No ingestion runs yet", "", "sync")
        else:
            lj = last.reset_index()
            lj["duration_s"] = (pd.to_datetime(lj["finished_at"]) -
                                pd.to_datetime(lj["started_at"])).dt.total_seconds()
            st.dataframe(lj[["job", "status", "started_at", "duration_s", "rows"]],
                         hide_index=True, width="stretch", height=380,
                         column_config={"started_at": st.column_config.DatetimeColumn(
                             "Started (UTC)", format="MMM D HH:mm"),
                             "duration_s": st.column_config.NumberColumn("Seconds",
                                                                         format="%.0f")})

with card("Data-quality checks", icon_name="rule",
          meta="run after every full refresh · process/dq.py"):
    if dq.empty:
        st.caption("No checks recorded yet - they run with the next full refresh.")
    else:
        order = {"fail": 0, "warn": 1, "ok": 2}
        status_rows([({"ok": POS, "warn": WARN, "fail": NEG}.get(r.status, MUTED),
                      f"{r.check} · {r.status.upper()}", str(r.detail or ""))
                     for r in sorted(dq.itertuples(), key=lambda r: order.get(r.status, 3))])

fails = runs[runs["status"] == "error"].head(25) if not runs.empty else runs
if not fails.empty:
    with card("Recent failures", icon_name="error", meta="newest first"):
        for r in fails.itertuples():
            st.markdown(f"**{r.job}** · {pd.Timestamp(r.started_at):%b %d %H:%M} UTC  \n"
                        f"<span style='color:{NEG}'>{esc(str(r.detail or '')[:400])}</span>",
                        unsafe_allow_html=True)

with card("Storage", icon_name="database"):
    try:
        from bioterm.db import get_engine

        if get_engine().dialect.name.startswith("postgres"):
            sizes = q("SELECT c.relname AS table, c.reltuples::bigint AS approx_rows, "
                      "pg_total_relation_size(c.oid) AS bytes FROM pg_class c "
                      "JOIN pg_namespace n ON n.oid = c.relnamespace "
                      "WHERE c.relkind = 'r' AND n.nspname = 'public' ORDER BY bytes DESC")
            total = q("SELECT pg_database_size(current_database()) AS b").iloc[0]["b"]
            st.caption(f"Database size {total / 1e6:,.0f} MB (Neon's free plan allows 512 MB). "
                       "Old news, runs and alerts are pruned by `bioterm retention`.")
            sizes["MB"] = sizes["bytes"] / 1e6
            st.dataframe(sizes[["table", "approx_rows", "MB"]].head(20), hide_index=True,
                         width="stretch",
                         column_config={"MB": st.column_config.NumberColumn(format="%.1f")})
        else:
            st.caption("Local SQLite database.")
    except Exception as exc:  # noqa: BLE001
        st.caption(f"Storage stats unavailable: {exc}")

try:
    from bioterm.httpx_util import breaker_state

    bs = breaker_state()
    if bs.get("open"):
        st.warning("Paused providers (circuit open after repeated failures): "
                   + ", ".join(bs["open"]), icon=":material/power_off:")
except Exception:  # noqa: BLE001
    pass
