"""Offline smoke tests - no network. External calls are monkeypatched."""
from datetime import datetime, timezone

from bioterm.db import bulk_upsert, init_db, read_sql, securities


def test_universe_falls_back_to_seed(monkeypatch):
    from bioterm import universe

    monkeypatch.setattr(universe, "fetch_xbi", lambda: (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(universe, "fetch_ibb", lambda: (_ for _ in ()).throw(RuntimeError("no net")))
    init_db()
    df = universe.build_universe(force=True)
    assert len(df) >= 40
    assert "MRNA" in set(df["ticker"])
    assert df["is_watchlist"].sum() >= 1


def test_news_matcher_precision(monkeypatch):
    init_db()
    bulk_upsert(securities, [
        {"ticker": "BEAM", "name": "Beam Therapeutics Inc", "is_watchlist": 0},
        {"ticker": "MRNA", "name": "Moderna Inc", "is_watchlist": 0},
    ])
    from bioterm.ingest import news as news_mod

    matchers = news_mod._build_matchers()
    # "Beam Benefits" (an unrelated insurance product) must NOT match BEAM
    assert news_mod._match_tickers(" Principal buys Beam Benefits today ", matchers) == []
    # real mentions do match
    assert "BEAM" in news_mod._match_tickers(" Beam Therapeutics posts data ", matchers)
    assert "MRNA" in news_mod._match_tickers(" $MRNA jumps on RSV win ", matchers)


def test_sentiment_event_tagging():
    from bioterm.process.sentiment import score_text

    v, tags, es = score_text("Company drug meets primary endpoint in Phase 3", "")
    assert "meets primary endpoint" in tags
    assert es > 0

    v, tags, es = score_text("FDA issues complete response letter", "")
    assert es < 0


def test_full_pipeline_recompute_no_data():
    """catalysts + score must run cleanly on an empty-ish DB."""
    from bioterm import pipeline

    init_db()
    bulk_upsert(securities, [{"ticker": "AAAA", "name": "Aaaa Bio", "is_watchlist": 0}])
    out = pipeline.recompute()
    assert out["catalysts"].get("error") is None
    assert out["score"].get("error") is None
