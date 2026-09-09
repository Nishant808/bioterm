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
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from .db import alerts_fired, bulk_upsert, read_sql
from .httpx_util import session
from .store import get_meta, get_watchlist

log = logging.getLogger("bioterm.alerts")

DEFAULT_RULES = {
    "score_jump": 0.05,
    "catalyst_within_days": 21,
    "event_tags": ["topline", "meets primary endpoint", "approval", "approved",
                   "complete response letter", "crl", "clinical hold",
                   "breakthrough therapy", "priority review", "accelerated approval"],
    "watchlist_only": False,
    "news_lookback_days": 3,
}


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
    news = read_sql(
        "SELECT ticker, title, published, event_tags, event_score FROM news")

    out: list[dict] = []

    # --- score jumps vs the last distinct snapshot run ---
    runs = read_sql("SELECT DISTINCT ts FROM score_snapshots ORDER BY ts DESC")
    if len(runs) >= 2:
        prev_ts = pd.to_datetime(runs.iloc[1]["ts"])
        prev = read_sql("SELECT ticker, focus_score FROM score_snapshots WHERE ts = :t",
                        {"t": prev_ts.to_pydatetime()}).set_index("ticker")
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
                        "detail": f"{c['type']} · {c['date']} ({float(c['months_away']):.1f} mo) — {str(c['title'])[:90]}",
                        "weight": 1.0 / (1 + max(0.0, float(c["months_away"])))})

    # --- high-signal headlines ---
    if not news.empty:
        news["published"] = pd.to_datetime(news["published"], utc=True, errors="coerce")
        cut = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(rules["news_lookback_days"]))
        want = set(rules["event_tags"])
        for _, n in news[news["published"] >= cut].iterrows():
            hit = {t for t in str(n["event_tags"] or "").split(",") if t} & want
            if not hit:
                continue
            if wl_only and str(n["ticker"] or "").upper() not in wl:
                continue
            out.append({"kind": "headline", "ticker": n["ticker"] or "?",
                        "detail": f"{', '.join(sorted(hit))} — {str(n['title'])[:110]}",
                        "weight": abs(float(n["event_score"] or 0))})

    out.sort(key=lambda a: a["weight"], reverse=True)
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
            icon = {"score move": "📈", "catalyst soon": "🗓", "headline": "📰"}.get(a["kind"], "•")
            lines.append(f"{icon} <b>{a['ticker']}</b> — {a['detail']}")
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
