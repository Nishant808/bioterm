"""News sentiment + biotech event tagging.

Two signals per headline:
  * ``sentiment``   - VADER compound score in [-1, 1] (generic tone)
  * ``event_score`` - signed sum of matched domain-event weights from settings.yml
                      (e.g. "meets primary endpoint" = +1.0, "clinical hold" = -1.0)

The event score is what actually moves biotech stocks; VADER is a weak secondary.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from ..config import load_settings
from ..db import bulk_upsert, news, read_sql

log = logging.getLogger("bioterm.process.sentiment")

_ANALYZER = SentimentIntensityAnalyzer()


def _event_patterns() -> list[tuple[re.Pattern, float, str]]:
    cfg = load_settings()
    pats: list[tuple[re.Pattern, float, str]] = []
    for bucket in ("positive_events", "negative_events"):
        for phrase, weight in (cfg.get("sentiment", bucket, default={}) or {}).items():
            pats.append(
                (re.compile(r"\b" + re.escape(str(phrase)) + r"\b", re.I), float(weight), str(phrase))
            )
    return pats


def score_text(title: str, summary: str = "") -> tuple[float, str, float]:
    """Return (vader_compound, comma-joined-tags, event_score)."""
    text = f"{title or ''}. {summary or ''}".strip()
    vader = _ANALYZER.polarity_scores(text)["compound"] if text else 0.0
    tags: list[str] = []
    event_score = 0.0
    for pat, weight, label in _event_patterns():
        if pat.search(text):
            tags.append(label)
            event_score += weight
    # clamp
    event_score = max(-2.0, min(2.0, event_score))
    return round(vader, 4), ",".join(sorted(set(tags))), round(event_score, 4)


def run(only_missing: bool = True) -> dict:
    """Backfill sentiment/event fields on the ``news`` table."""
    where = "WHERE sentiment IS NULL" if only_missing else ""
    df = read_sql(f"SELECT id, title, summary FROM news {where}")
    if df.empty:
        return {"rows": 0}
    now = datetime.now(timezone.utc)
    rows = []
    for _, r in df.iterrows():
        v, tags, es = score_text(r["title"], r.get("summary") or "")
        rows.append(
            {
                "id": r["id"],
                "sentiment": v,
                "event_tags": tags,
                "event_score": es,
                "fetched_at": now,
            }
        )
    n = bulk_upsert(
        news, rows, update_only=["sentiment", "event_tags", "event_score", "fetched_at"]
    )
    log.info("sentiment: scored %d headlines", n)
    return {"rows": n}
