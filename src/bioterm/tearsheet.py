"""Tear sheets: everything BioTerm knows about one name, as a printable HTML page
(print it to PDF from the browser) or an Excel workbook (one sheet per section)."""
from __future__ import annotations

import html
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    from .db import read_sql

    try:
        return read_sql(sql, params or {})
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def gather(ticker: str) -> dict[str, Any]:
    t = ticker.upper()
    today = date.today()
    d: dict[str, Any] = {"ticker": t, "generated": datetime.now(timezone.utc)}
    sec = _q("SELECT name, exchange, in_xbi, is_watchlist FROM securities WHERE ticker = :t",
             {"t": t})
    d["name"] = sec.iloc[0]["name"] if not sec.empty else t
    f = _q("SELECT * FROM fundamentals WHERE ticker = :t", {"t": t})
    d["fundamentals"] = f.iloc[0].to_dict() if not f.empty else {}
    sc = _q("SELECT asof, focus_score, rank, momentum, catalyst, newsflow, risk FROM scores "
            "WHERE ticker = :t ORDER BY asof DESC LIMIT 1", {"t": t})
    d["score"] = sc.iloc[0].to_dict() if not sc.empty else {}
    sg = _q("SELECT asof, label, net, top FROM signal_scores WHERE ticker = :t "
            "ORDER BY asof DESC LIMIT 1", {"t": t})
    d["signal"] = sg.iloc[0].to_dict() if not sg.empty else {}
    try:
        d["signal_evidence"] = [e.get("title") for e in json.loads(d["signal"].get("top") or "[]")]
    except (TypeError, ValueError):
        d["signal_evidence"] = []
    d["catalysts"] = _q("SELECT date, type, title, confidence, source, url FROM catalysts "
                        "WHERE ticker = :t AND date >= :a ORDER BY date LIMIT 15",
                        {"t": t, "a": (today - timedelta(days=15)).isoformat()})
    d["trials"] = _q("SELECT nct_id, phase, status, title, conditions, primary_completion_date, "
                     "enrollment FROM clinical_trials WHERE ticker = :t AND status IN "
                     "('RECRUITING','ACTIVE_NOT_RECRUITING','NOT_YET_RECRUITING',"
                     "'ENROLLING_BY_INVITATION') ORDER BY primary_completion_date", {"t": t})
    d["filings"] = _q("SELECT f.filed_date, f.form, f.items, s.summary, f.url FROM filings f "
                      "LEFT JOIN filing_summaries s ON s.accession = f.id WHERE f.ticker = :t "
                      "ORDER BY f.filed_date DESC LIMIT 20", {"t": t})
    d["insiders"] = _q("SELECT txn_date, owner, role, code, shares, price, value, plan_10b5_1 "
                       "FROM insider_txns WHERE ticker = :t AND code IN ('P','S') "
                       "ORDER BY txn_date DESC LIMIT 20", {"t": t})
    d["funds"] = _q("SELECT h.period, f.short_name AS fund, h.shares, h.value FROM inst_holdings "
                    "h LEFT JOIN inst_filers f ON f.cik = h.cik WHERE h.ticker = :t "
                    "ORDER BY h.period DESC, h.value DESC LIMIT 40", {"t": t})
    d["news"] = _q("SELECT published, source, title, sentiment, url FROM news "
                   "WHERE ticker = :t ORDER BY published DESC LIMIT 15", {"t": t})
    d["loe"] = _q("SELECT trade_name, appl_no, approval_date, loe_date FROM loe_calendar "
                  "WHERE ticker = :t ORDER BY loe_date", {"t": t})
    d["prices"] = _q("SELECT date, open, high, low, close, volume FROM prices WHERE ticker = :t "
                     "AND date >= :c ORDER BY date",
                     {"t": t, "c": (today - timedelta(days=400)).isoformat()})
    return d


def _money(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "–"
    if pd.isna(v):
        return "–"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"${v / div:,.2f}{suf}"
    return f"${v:,.0f}"


def summary_rows(d: dict[str, Any]) -> list[tuple[str, str]]:
    f, s, g = d["fundamentals"], d["score"], d["signal"]
    rq = f.get("runway_quarters")
    return [
        ("Company", str(d["name"])), ("Ticker", d["ticker"]),
        ("Market cap", _money(f.get("market_cap"))), ("Cash", _money(f.get("cash"))),
        ("Debt", _money(f.get("total_debt"))),
        ("Burn / year", _money(f.get("burn_ttm"))),
        ("Runway", f"{float(rq):.1f} quarters" if rq is not None and pd.notna(rq) else "–"),
        ("Short % float", f"{float(f['short_percent_float']):.1%}"
         if f.get("short_percent_float") is not None and pd.notna(f.get("short_percent_float"))
         else "–"),
        ("Focus Score", f"{float(s['focus_score']):.3f} (rank #{int(s['rank'])})"
         if s.get("focus_score") is not None else "–"),
        ("Signal", f"{g.get('label')} (net {float(g['net']):+.2f})" if g.get("label") else "–"),
        ("Signal evidence", "; ".join(str(x) for x in d["signal_evidence"][:4]) or "–"),
        ("Generated", f"{d['generated']:%Y-%m-%d %H:%M} UTC"),
    ]


def xlsx(ticker: str) -> bytes:
    d = gather(ticker)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(summary_rows(d), columns=["Field", "Value"]).to_excel(
            w, sheet_name="Summary", index=False)
        for name in ("catalysts", "trials", "filings", "insiders", "funds", "news", "loe",
                     "prices"):
            df = d[name]
            if df is None or df.empty:
                continue
            df = df.copy()
            for c in df.columns:     # Excel can't hold tz-aware datetimes
                if isinstance(df[c].dtype, pd.DatetimeTZDtype):
                    df[c] = df[c].dt.tz_localize(None)
            df.to_excel(w, sheet_name=name.capitalize()[:31], index=False)
        pd.DataFrame([["Monitoring and screening only - not investment advice. Sources: SEC "
                       "EDGAR, ClinicalTrials.gov, openFDA, FINRA, yfinance, RSS."]],
                     columns=["Note"]).to_excel(w, sheet_name="About", index=False)
    return buf.getvalue()


def _table(df: pd.DataFrame, cols: list[str], links: dict[str, str] | None = None,
           limit: int = 15) -> str:
    if df is None or df.empty:
        return "<p class='muted'>None on file.</p>"
    links = links or {}
    head = "".join(f"<th>{html.escape(c.replace('_', ' ').title())}</th>" for c in cols)
    rows = []
    for _, r in df.head(limit).iterrows():
        cells = []
        for c in cols:
            v = r.get(c)
            txt = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            if isinstance(v, (pd.Timestamp, datetime, date)):
                txt = pd.Timestamp(v).strftime("%Y-%m-%d")
            txt = html.escape(txt[:220])
            url = r.get(links.get(c, "")) if c in links else None
            if isinstance(url, str) and url.startswith("http"):
                txt = f"<a href='{html.escape(url)}'>{txt}</a>"
            cells.append(f"<td>{txt}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def html_page(ticker: str) -> str:
    d = gather(ticker)
    kv = "".join(f"<div><span>{html.escape(k)}</span><b>{html.escape(v)}</b></div>"
                 for k, v in summary_rows(d))
    css = """
body{font:13px/1.45 Inter,system-ui,sans-serif;color:#111;margin:28px;max-width:1080px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid #ddd;
padding-bottom:4px}.sub{color:#666;margin:2px 0 14px}.kv{display:grid;
grid-template-columns:repeat(3,1fr);gap:6px 18px}.kv div{display:flex;justify-content:space-between;
border-bottom:1px dotted #ddd;padding:3px 0}.kv span{color:#666}table{width:100%;
border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:4px 6px;
border-bottom:1px solid #eee;vertical-align:top}th{background:#f6f7f9}a{color:#1d5fd0;
text-decoration:none}.muted{color:#888}footer{margin-top:26px;color:#888;font-size:11px}
@media print{body{margin:10mm}a{color:#111}}"""
    parts = [
        f"<h1>{html.escape(str(d['name']))} ({d['ticker']})</h1>",
        f"<p class='sub'>BioTerm tear sheet · {d['generated']:%B %d, %Y}</p>",
        f"<div class='kv'>{kv}</div>",
        "<h2>Upcoming catalysts</h2>",
        _table(d["catalysts"], ["date", "type", "title", "confidence"], {"title": "url"}),
        "<h2>Active trials</h2>",
        _table(d["trials"], ["nct_id", "phase", "status", "title", "primary_completion_date",
                             "enrollment"]),
        "<h2>Recent SEC filings</h2>",
        _table(d["filings"], ["filed_date", "form", "items", "summary"], {"form": "url"}),
        "<h2>Insider trades (open market)</h2>",
        _table(d["insiders"], ["txn_date", "owner", "role", "code", "shares", "price", "value"]),
        "<h2>Specialist funds (13F)</h2>",
        _table(d["funds"], ["period", "fund", "shares", "value"]),
        "<h2>Marketed drugs</h2>",
        _table(d["loe"], ["trade_name", "appl_no", "approval_date", "loe_date"]),
        "<h2>Recent headlines</h2>",
        _table(d["news"], ["published", "source", "title", "sentiment"], {"title": "url"}),
        "<footer>Monitoring and screening only - not investment advice. BioTerm's signal "
        "labels and scores are screening states computed from public data (SEC EDGAR, "
        "ClinicalTrials.gov, openFDA, FINRA, company press releases).</footer>",
    ]
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{d['ticker']} tear "
            f"sheet</title><style>{css}</style></head><body>{''.join(parts)}</body></html>")
