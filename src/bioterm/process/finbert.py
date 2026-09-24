"""FinBERT headline tone -> ``news.sentiment`` (+ provenance in ``news_nlp``).

VADER is a general social-media lexicon: "misses estimates" and "beats" barely
move it. FinBERT (ProsusAI/finbert, a BERT fine-tuned on financial news) reads
the sentence and returns p(positive) / p(negative) / p(neutral); the tone we
store is p(positive) - p(negative), on the same -1..1 scale VADER used, so every
downstream consumer (news flow, the sentiment charts, the signal engine) upgrades
without a code change.

Optional: needs the ``nlp`` extra (transformers + CPU torch, ~700 MB). The
daily Actions run installs it and caches the model; everywhere else - the
dashboard, the fast run, tests - this module is a no-op and VADER stays.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Callable

from ..config import load_settings
from ..db import bulk_upsert, news, news_nlp, read_sql

log = logging.getLogger("bioterm.process.finbert")

# Google News appends " - Publisher" (capitalised, a few words); a lowercase or
# long tail is part of the headline itself ("... Phase 3 - topline due")
_PUBLISHER_TAIL = re.compile(r"\s+-\s+[A-Z0-9][^-]{1,59}$")
# ... or a bare domain ("- timothysykes.com", "- simplywall.st")
_DOMAIN_TAIL = re.compile(r"\s+-\s+[a-z0-9][\w-]*(?:\.[a-z0-9-]+)+$", re.I)

Scorer = Callable[[list[str]], list[dict]]


def available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def clean_title(title: str) -> str:
    t = " ".join(str(title or "").split())
    d = _DOMAIN_TAIL.search(t)
    if d:
        t = t[:d.start()]
    m = _PUBLISHER_TAIL.search(t)
    if m and len(m.group(0).split()) <= 7:
        return t[:m.start()]
    return t


def load_scorer(model_id: str, batch_size: int = 32) -> Scorer:
    """A callable texts -> [{positive, negative, neutral}] probabilities."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id)
    model.eval()
    torch.set_num_threads(max(1, torch.get_num_threads()))
    labels = {i: str(l).lower() for i, l in model.config.id2label.items()}

    def score(texts: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(texts), batch_size):
            enc = tok(texts[i:i + batch_size], padding=True, truncation=True,
                      max_length=64, return_tensors="pt")
            with torch.no_grad():
                probs = torch.softmax(model(**enc).logits, dim=-1).tolist()
            out.extend({labels[j]: float(p) for j, p in enumerate(row)} for row in probs)
        return out

    return score


def to_tone(probs: dict) -> tuple[float, str, float]:
    """(tone = p_pos - p_neg, top label, its probability)."""
    pos, neg = probs.get("positive", 0.0), probs.get("negative", 0.0)
    label = max(probs, key=probs.get) if probs else "neutral"
    return round(pos - neg, 4), label, round(probs.get(label, 0.0), 4)


def run(max_rows: int | None = None, scorer: Scorer | None = None) -> dict:
    cfg = load_settings()
    if scorer is None and not available():
        log.info("finbert: transformers/torch not installed - VADER tone stays")
        return {"rows": 0, "skipped": "nlp extra not installed"}
    model_id = str(cfg.get("nlp", "model", default="ProsusAI/finbert"))
    limit = int(max_rows or cfg.get("nlp", "max_per_run", default=6000))
    todo = read_sql(
        "SELECT n.id, n.title, n.sentiment FROM news n LEFT JOIN news_nlp x ON x.id = n.id "
        "WHERE x.id IS NULL ORDER BY n.published DESC LIMIT :lim", {"lim": limit})
    if todo.empty:
        return {"rows": 0}
    scorer = scorer or load_scorer(model_id, int(cfg.get("nlp", "batch_size", default=32)))
    texts = [clean_title(t) for t in todo["title"].tolist()]
    probs = scorer(texts)
    now = datetime.now(timezone.utc)
    nlp_rows, news_rows = [], []
    for (_, r), p in zip(todo.iterrows(), probs):
        tone, label, conf = to_tone(p)
        nlp_rows.append({"id": r["id"], "vader": r["sentiment"], "finbert": tone,
                         "label": label, "confidence": conf, "model": model_id,
                         "scored_at": now})
        news_rows.append({"id": r["id"], "sentiment": tone})
    bulk_upsert(news_nlp, nlp_rows)
    bulk_upsert(news, news_rows, update_only=["sentiment"])
    log.info("finbert: scored %d headlines with %s", len(nlp_rows), model_id)
    return {"rows": len(nlp_rows), "model": model_id}
