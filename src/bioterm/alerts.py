"""Alert evaluation + optional delivery.

Rules live in the DB (``app_meta.alert_rules``, editable from the dashboard).
``evaluate()`` is pure and shared by the dashboard's Alerts page and the
``bioterm alerts`` CLI (run as a step in the ingest-fast workflow).

Delivery is opt-in and credential-gated:
  * Telegram - set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID  (BotFather, 2 min, free)
  * anything else - read ``alerts_fired`` yourself
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select

from .db import alerts_fired, bulk_upsert, read_sql, score_snapshots, signal_scores
from .httpx_util import session
from .store import get_meta, get_watchlist
from .util import strip_markup

log = logging.getLogger("bioterm.alerts")

DEFAULT_RULES = {
    "score_jump": 0.05,
    "catalyst_within_days": 21,
    "event_tags": ["topline", "meets primary endpoint", "approval", "approved",
                   "complete response letter", "crl", "clinical hold",
                   "breakthrough therapy", "priority review", "accelerated approval"],
    "watchlist_only": False,
    "news_lookback_days": 3,
    # signal-engine label changes that alert (entering any of these from another label)
    "signal_labels": ["STRONG BUY", "BUY", "SELL", "STRONG SELL"],
}

SIGNAL_RANK = {"STRONG SELL": -2, "SELL": -1, "NEUTRAL": 0, "BUY": 1, "STRONG BUY": 2}


def get_rules() -> dict:
    return {**DEFAULT_RULES, **(get_meta("alert_rules", {}) or {})}


def _aid(kind: str, ticker: str, detail: str) -> str:
    return hashlib.sha1(f"{kind}|{ticker}|{detail}".encode()).hexdigest()[:48]


def evaluate(rules: dict | None = None) -> list[dict]:
    rules = rules or get_rules()
    wl = {w["ticker"].upper() for w in get_watchlist()}
    wl_only = bool(rules.get("watchlist_only"))

    scores = read_sql("SELECT ticker, focus_score, rank FROM scores "
                      "WHERE asof = (SELECT MAX(asof) FROM scores)")
    cats = read_sql("SELECT ticker, type, date, months_away, title FROM catalysts")
    # Only the lookback window is ever used, so don't pull the whole news table (thousands
    # of rows; this runs on every Alerts page view). A day of slack in SQL, the exact cut
    # below - so the result can't depend on how a backend compares the timestamp.
    cut = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(rules["news_lookback_days"]))
    news = read_sql(
        "SELECT ticker, title, published, event_tags, event_score FROM news "
        "WHERE published >= :c",
        {"c": (cut - pd.Timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")})

    out: list[dict] = []

    # --- score jumps vs the last distinct snapshot run ---
    runs = read_sql("SELECT DISTINCT ts FROM score_snapshots ORDER BY ts DESC LIMIT 2")
    if len(runs) >= 2:
        prev_ts = pd.to_datetime(runs.iloc[1]["ts"]).to_pydatetime()
        # A Core select, not raw SQL: the column type binds the datetime the way it was
        # stored. Raw, SQLite compares text - "... 11:00:00" never equals the stored
        # "... 11:00:00.000000", so score moves silently never fired on a local DB.
        prev = read_sql(select(score_snapshots.c.ticker, score_snapshots.c.focus_score)
                        .where(score_snapshots.c.ts == prev_ts)).set_index("ticker")
        for _, r in scores.iterrows():
            if wl_only and r["ticker"] not in wl:
                continue
            if r["ticker"] in prev.index:
                d = float(r["focus_score"]) - float(prev.loc[r["ticker"], "focus_score"])
                if abs(d) >= float(rules["score_jump"]):
                    out.append({"kind": "score move", "ticker": r["ticker"],
                                "detail": f"Focus {d:+.3f} -> {r['focus_score']:.3f} (rank #{int(r['rank'])})",
                                "weight": abs(d)})

    # --- catalyst entering the window ---
    if not cats.empty:
        win = float(rules["catalyst_within_days"]) / 30.0
        near = cats[(cats["months_away"] >= -0.2) & (cats["months_away"] <= win)]
        for _, c in near.iterrows():
            if wl_only and c["ticker"] not in wl:
                continue
            out.append({"kind": "catalyst soon", "ticker": c["ticker"],
                        "detail": f"{c['type']} · {c['date']} ({float(c['months_away']):.1f} mo) — {strip_markup(c['title'])[:90]}",
                        "weight": 1.0 / (1 + max(0.0, float(c["months_away"])))})

    # --- high-signal headlines ---
    if not news.empty:
        news["published"] = pd.to_datetime(news["published"], utc=True, errors="coerce")
        want = set(rules["event_tags"])
        for _, n in news[news["published"] >= cut].iterrows():
            hit = {t for t in str(n["event_tags"] or "").split(",") if t} & want
            if not hit:
                continue
            if wl_only and str(n["ticker"] or "").upper() not in wl:
                continue
            # strip feed markup *before* truncating - cutting a title mid-tag
            # leaves an unclosed <a href=... that Telegram's HTML mode rejects
            out.append({"kind": "headline", "ticker": n["ticker"] or "?",
                        "detail": f"{', '.join(sorted(hit))} — {strip_markup(n['title'])[:110]}",
                        "weight": abs(float(n["event_score"] or 0))})

    # --- signal-engine label transitions (latest run vs the previous day's) ---
    out.extend(_signal_transitions(rules, wl if wl_only else None))

    out.sort(key=lambda a: a["weight"], reverse=True)
    return out


def _signal_transitions(rules: dict, only: set[str] | None) -> list[dict]:
    try:
        days = read_sql("SELECT DISTINCT asof FROM signal_scores ORDER BY asof DESC LIMIT 2")
    except Exception:  # noqa: BLE001 - table appears with the first signals run
        return []
    if days.empty:
        return []
    import json

    want = set(rules.get("signal_labels") or [])
    cur = read_sql(select(signal_scores.c.ticker, signal_scores.c.label, signal_scores.c.net,
                          signal_scores.c.top)
                   .where(signal_scores.c.asof == pd.to_datetime(days.iloc[0]["asof"]).date()))
    prev = pd.DataFrame(columns=["ticker", "label"])
    if len(days) > 1:
        prev = read_sql(select(signal_scores.c.ticker, signal_scores.c.label)
                        .where(signal_scores.c.asof == pd.to_datetime(days.iloc[1]["asof"]).date()))
    before = dict(zip(prev["ticker"], prev["label"]))
    out = []
    for _, r in cur.iterrows():
        if only is not None and r["ticker"] not in only:
            continue
        was = before.get(r["ticker"], "NEUTRAL")
        if r["label"] not in want or r["label"] == was:
            continue
        try:
            top = json.loads(r["top"] or "[]")
        except (TypeError, ValueError):
            top = []
        why = top[0]["title"] if top else ""
        out.append({"kind": "signal", "ticker": r["ticker"],
                    "detail": f"{was} → {r['label']} (net {float(r['net']):+.2f}) — {strip_markup(why)[:100]}",
                    "weight": abs(float(r["net"])) + 0.5 * abs(SIGNAL_RANK.get(r["label"], 0))})
    return out


def _telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = session().post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15)
        r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram send failed: %s", exc)
        return False


def run(deliver: bool = True, max_deliver: int = 12) -> dict:
    """Evaluate rules, persist newly-fired alerts, optionally push them."""
    rules = get_rules()
    fired = evaluate(rules)
    now = datetime.now(timezone.utc)

    known = read_sql("SELECT id FROM alerts_fired")
    known_ids = set(known["id"]) if not known.empty else set()

    new_rows, fresh = [], []
    for a in fired:
        aid = _aid(a["kind"], a["ticker"], a["detail"])
        if aid in known_ids:
            continue
        row = {"id": aid, "ts": now, "kind": a["kind"], "ticker": a["ticker"],
               "detail": a["detail"], "weight": round(float(a["weight"]), 4),
               "delivered": 0}
        new_rows.append(row)
        fresh.append(a)

    if new_rows:
        bulk_upsert(alerts_fired, new_rows)

    delivered = 0
    if deliver and fresh:
        top = fresh[:max_deliver]
        lines = [f"<b>BioTerm — {len(fresh)} new alert(s)</b>"]
        for a in top:
            icon = {"score move": "📈", "catalyst soon": "🗓", "headline": "📰",
                    "signal": "🚦"}.get(a["kind"], "•")
            # parse_mode=HTML: a raw "&" or "<" in a title ("R&D") is a hard error
            lines.append(f"{icon} <b>{html.escape(str(a['ticker']))}</b> — "
                         f"{html.escape(str(a['detail']))}")
        if len(fresh) > len(top):
            lines.append(f"…and {len(fresh) - len(top)} more")
        if _telegram("\n".join(lines)):
            delivered = len(fresh)
            ids = [r["id"] for r in new_rows]
            from .db import get_engine
            with get_engine().begin() as conn:
                conn.execute(alerts_fired.update()
                             .where(alerts_fired.c.id.in_(ids))
                             .values(delivered=1))

    log.info("alerts: %d firing, %d new, %d delivered", len(fired), len(new_rows), delivered)
    return {"firing": len(fired), "new": len(new_rows), "delivered": delivered}
