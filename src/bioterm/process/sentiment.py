"""News sentiment + biotech event tagging.

Two signals per headline:
  * ``sentiment``   - VADER compound score in [-1, 1] (generic tone)
  * ``event_score`` - signed sum of matched domain-event weights from settings.yml
                      (e.g. "meets primary endpoint" = +1.0, "clinical hold" = -1.0)

The event score is what actually moves biotech stocks; VADER is a weak secondary.

Each configured phrase compiles into a small regex family instead of one literal
string, so "misses its primary endpoints" still matches the phrase written in
settings.yml as "meets primary endpoint" - a plain ``\\bphrase\\b`` match missed
this whenever the headline used a different verb tense or a plural noun. See
``_compile_phrase``.
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

# Small, hand-picked verb families for the words that actually show up in the
# lexicon. Keyed by every inflected form so a phrase can be written in any
# tense in settings.yml and still match all the others (config keeps saying
# "meets primary endpoint"; the compiled pattern also matches "met", "meeting",
# "misses"...  no, "miss" is its own separate family/phrase - see below).
_VERB_FAMILIES = [
    ("meet", "meets", "met", "meeting"),
    ("hit", "hits", "hitting"),
    ("gain", "gains", "gained", "gaining"),
    ("miss", "misses", "missed", "missing"),
    ("fail", "fails", "failed", "failing"),
    ("do", "does", "did", "doing"),
    ("approve", "approves", "approved", "approving"),
    ("discontinue", "discontinues", "discontinued", "discontinuing"),
    ("halt", "halts", "halted", "halting"),
    ("present", "presents", "presented", "presenting"),
    ("announce", "announces", "announced", "announcing"),
    ("receive", "receives", "received", "receiving"),
    ("complete", "completes", "completed", "completing"),
    ("report", "reports", "reported", "reporting"),
    ("initiate", "initiates", "initiated", "initiating"),
    ("expect", "expects", "expected", "expecting"),
    ("price", "prices", "priced", "pricing"),
    ("offer", "offers", "offered", "offering"),
    ("restructure", "restructures", "restructured", "restructuring"),
    ("win", "wins", "won", "winning"),
    ("grant", "grants", "granted", "granting"),
    ("clear", "clears", "cleared", "clearing"),
    ("reject", "rejects", "rejected", "rejecting"),
    ("terminate", "terminates", "terminated", "terminating"),
    ("suspend", "suspends", "suspended", "suspending"),
    ("vote", "votes", "voted", "voting"),
]
_VERB_LOOKUP: dict[str, tuple[str, ...]] = {
    form: fam for fam in _VERB_FAMILIES for form in fam
}

# Words a phrase's *last* token should never get a naive plural "s" bolted onto
# (either it's a filler word, or it already needs no inflection to match well).
_NO_PLURAL = {"of", "in", "to", "a", "an", "the", "its", "is", "are", "by", "for", "on", "at"}

# Optional filler that may sit between two consecutive words of a configured
# phrase without breaking the match ("meets primary endpoint" also catches
# "met THE primary endpoint" / "met ITS primary endpoint").
_FILLER = r"\s+(?:(?:the|a|an|its|this|that)\s+)?"


def _pluralize_pattern(word: str) -> str:
    """A tiny regular-noun pluralizer, as a regex alternation fragment."""
    if len(word) > 2 and word[-1].lower() == "y" and word[-2].lower() not in "aeiou":
        return re.escape(word[:-1]) + "(?:y|ies)"
    if word.lower().endswith(("s", "x", "ch", "sh")):
        return re.escape(word)  # would need "-es", not a plain "s" - don't guess
    return re.escape(word) + "s?"


def _compile_phrase(phrase: str) -> re.Pattern:
    """Turn one configured phrase into a regex that also matches its common
    verb-tense and plural-noun variants, with an optional article/possessive
    between words. The literal phrase always still matches."""
    words = phrase.split()
    n = len(words)
    parts = []
    for i, w in enumerate(words):
        lw = w.lower()
        fam = _VERB_LOOKUP.get(lw)
        if fam:
            parts.append("(?:" + "|".join(fam) + ")")
        elif i == n - 1 and lw not in _NO_PLURAL and w.isalpha():
            parts.append(_pluralize_pattern(w))
        else:
            parts.append(re.escape(w))
    body = _FILLER.join(parts) if len(parts) > 1 else parts[0]
    return re.compile(r"\b" + body + r"\b", re.I)


# Compiled patterns are cached by the *content* of the configured lexicon, not
# forever - settings.yml is meant to hot-reload (the scheduler is long-running),
# so editing it still takes effect on the next call. The cache just means a
# single `run()` over thousands of headlines doesn't recompile ~50 regexes per
# headline when the config hasn't actually changed since the last one.
_pattern_cache: dict[int, list[tuple[re.Pattern, float, str]]] = {}


def _event_patterns() -> list[tuple[re.Pattern, float, str]]:
    cfg = load_settings()
    pos = cfg.get("sentiment", "positive_events", default={}) or {}
    neg = cfg.get("sentiment", "negative_events", default={}) or {}
    key = hash((tuple(sorted(pos.items())), tuple(sorted(neg.items()))))
    cached = _pattern_cache.get(key)
    if cached is not None:
        return cached

    pats: list[tuple[re.Pattern, float, str]] = []
    for bucket in (pos, neg):
        for phrase, weight in bucket.items():
            pats.append((_compile_phrase(str(phrase)), float(weight), str(phrase)))

    if len(_pattern_cache) > 4:  # settings.yml doesn't change often within one run
        _pattern_cache.clear()
    _pattern_cache[key] = pats
    return pats


def _drop_shadowed_hits(
    hits: list[tuple[tuple[int, int], float, str]],
) -> list[tuple[tuple[int, int], float, str]]:
    """Drop a hit whose match sits entirely inside a longer, opposite-signed
    hit's match - e.g. the bare positive phrase "approval" inside the negative
    phrase "voted against approval" is an echo of the same occurrence, not an
    independent positive signal. The longer, more specific phrase wins."""
    def shadowed(i: int) -> bool:
        (s, e), w, _ = hits[i]
        return any(
            j != i and s >= s2 and e <= e2 and (e - s) < (e2 - s2) and (w > 0) != (w2 > 0)
            for j, ((s2, e2), w2, _) in enumerate(hits)
        )
    return [h for i, h in enumerate(hits) if not shadowed(i)]


def score_text(title: str, summary: str = "") -> tuple[float, str, float]:
    """Return (vader_compound, comma-joined-tags, event_score)."""
    text = f"{title or ''}. {summary or ''}".strip()
    vader = _ANALYZER.polarity_scores(text)["compound"] if text else 0.0
    hits: list[tuple[tuple[int, int], float, str]] = []
    for pat, weight, label in _event_patterns():
        m = pat.search(text)  # once per phrase - weight reflects the phrase, not a count
        if m:
            hits.append((m.span(), weight, label))
    kept = _drop_shadowed_hits(hits)
    tags = sorted({label for _, _, label in kept})
    event_score = max(-2.0, min(2.0, sum(w for _, w, _ in kept)))
    return round(vader, 4), ",".join(tags), round(event_score, 4)


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
