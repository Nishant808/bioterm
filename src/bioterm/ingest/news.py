"""News ingestion: sector RSS feeds + per-ticker Google News queries -> ``news``.

Sector feeds are scanned for any universe company mention; per-ticker Google News
RSS queries catch company-specific coverage the sector feeds miss. Dedup is by
URL hash. Sentiment + event tags are scored inline (process.sentiment.score_text).
"""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from datetime import datetime, timezone

import feedparser
import pandas as pd

from ..config import load_settings
from ..db import bulk_upsert, news, read_sql
from ..httpx_util import get_bytes
from ..process.sentiment import score_text
from ..universe import universe_tickers
from ..util import as_text

log = logging.getLogger("bioterm.ingest.news")

# trailing corporate-form words only - we KEEP "Therapeutics"/"Pharmaceuticals"
# because dropping them makes short names like "Beam" match "Beam Benefits".
_CORP_SUFFIX = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "plc", "ag", "nv", "sa", "asa", "ab", "holdings", "holding", "group", "the", "and",
}


def _short_name(name: str) -> str:
    """First two meaningful tokens of the company name, corporate suffixes trimmed."""
    toks = [t for t in re.sub(r"[.,]", " ", as_text(name)).split() if t]
    while toks and toks[-1].lower() in _CORP_SUFFIX:
        toks.pop()
    return " ".join(toks[:2]).strip()


def _build_matchers() -> dict[str, dict]:
    secs = read_sql("SELECT ticker, name FROM securities")
    out: dict[str, dict] = {}
    for _, r in secs.iterrows():
        tk = r["ticker"]
        short = _short_name(r["name"]) or tk
        aliases = {short.lower()} if len(short) >= 4 else set()
        # short tickers (<=2 chars) need a '$' prefix to avoid matching English words
        tk_pat = (rf"(?<![A-Za-z0-9])\$?{re.escape(tk)}(?![A-Za-z0-9])"
                  if len(tk) >= 3 else rf"\${re.escape(tk)}(?![A-Za-z0-9])")
        out[tk] = {
            "ticker_re": re.compile(tk_pat),
            "name_res": [re.compile(rf"\b{re.escape(a)}\b", re.I) for a in aliases if a],
            "short": short,
        }
    return out


def _match_tickers(text: str, matchers: dict[str, dict]) -> list[str]:
    hits = []
    for tk, m in matchers.items():
        if m["ticker_re"].search(text) or any(nr.search(text) for nr in m["name_res"]):
            hits.append(tk)
    return hits


def _mk_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:40]


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _clean_summary(entry) -> str:
    raw = entry.get("summary", "") or ""
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()[:1000]


def _parse_feed(url: str) -> list:
    try:
        raw = get_bytes(url, min_interval=1.0)
        return feedparser.parse(raw).entries
    except Exception as exc:  # noqa: BLE001
        log.warning("feed failed %s: %s", url, exc)
        return []


def _google_news_url(query: str) -> str:
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def run(tickers: list[str] | None = None, google: bool | None = None) -> dict:
    cfg = load_settings()
    lookback = int(cfg.get("ingest", "news_lookback_days", default=45))
    cutoff = datetime.now(timezone.utc) - pd.Timedelta(days=lookback)
    now = datetime.now(timezone.utc)
    tickers = tickers or universe_tickers()
    tickset = set(tickers)
    matchers = {tk: m for tk, m in _build_matchers().items() if tk in tickset}
    rows: dict[str, dict] = {}

    def _add(entry, source: str, forced_ticker: str | None = None):
        link = entry.get("link", "")
        if not link:
            return
        title = entry.get("title", "") or ""
        summary = _clean_summary(entry)
        pub = _published(entry)
        if pub and pub < cutoff:
            return
        matched = [forced_ticker] if forced_ticker else _match_tickers(
            f" {title} {summary} ", matchers
        )
        matched = [t for t in matched if t in tickset]
        if not matched:
            return
        v, tags, es = score_text(title, summary)
        _id = _mk_id(link)
        rows[_id] = {
            "id": _id,
            "ticker": matched[0],
            "tickers_csv": ",".join(matched),
            "title": title[:600],
            "summary": summary,
            "url": link[:500],
            "source": source[:60],
            "published": pub or now,
            "sentiment": v,
            "event_tags": tags,
            "event_score": es,
            "fetched_at": now,
        }

    # 1. sector feeds
    for feed in cfg.feeds:
        if feed.get("scope") != "sector":
            continue
        for entry in _parse_feed(feed["url"]):
            _add(entry, feed.get("name", feed["url"]))

    # 2. per-ticker Google News
    if google is None:
        google = bool(cfg.get("ingest", "news_google_per_ticker", default=True))
    if google:
        secs = read_sql("SELECT ticker, name FROM securities")
        name_by_ticker = dict(zip(secs["ticker"], secs["name"]))
        for tk in tickers:
            short = _short_name(name_by_ticker.get(tk, "")) or tk
            query = f'"{short}" (FDA OR trial OR Phase OR data OR approval OR stock OR drug)'
            for entry in _parse_feed(_google_news_url(query)):
                _add(entry, "Google News", forced_ticker=tk)

    n = bulk_upsert(news, list(rows.values()))
    log.info("news: %d headlines (%d feeds + %d ticker queries)",
             n, sum(1 for f in cfg.feeds if f.get("scope") == "sector"), len(tickers))
    return {"rows": n}
