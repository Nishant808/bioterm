"""Alert evaluation: the news lookback and the score-move baseline are applied in SQL,
so check the results are still exactly what the rules say."""
from datetime import date, datetime, timedelta, timezone

from bioterm import alerts
from bioterm.db import bulk_upsert, get_engine, init_db, news, score_snapshots, scores


def _headline(i: str, ticker: str, published: datetime, tags: str = "approval") -> dict:
    return {"id": i, "ticker": ticker, "tickers_csv": ticker, "title": f"{ticker} news {i}",
            "summary": "", "url": f"http://x/{i}", "source": "Test", "published": published,
            "sentiment": 0.5, "event_tags": tags, "event_score": 1.0, "fetched_at": published}


def test_headlines_respect_the_lookback_window():
    init_db()
    now = datetime.now(timezone.utc)
    bulk_upsert(news, [
        _headline("fresh", "AAA", now - timedelta(hours=2)),
        _headline("edge", "BBB", now - timedelta(days=2, hours=23)),
        _headline("stale", "CCC", now - timedelta(days=3, hours=6)),  # inside the SQL slack
        _headline("old", "DDD", now - timedelta(days=20)),
        _headline("untagged", "EEE", now - timedelta(hours=1), tags=""),
    ])
    fired = alerts.evaluate({**alerts.DEFAULT_RULES, "event_tags": ["approval"],
                             "news_lookback_days": 3})
    assert sorted(a["ticker"] for a in fired if a["kind"] == "headline") == ["AAA", "BBB"]


def test_score_moves_compare_against_the_previous_run():
    init_db()
    t0 = datetime(2026, 9, 20, 9)
    bulk_upsert(scores, [{"ticker": "AAA", "asof": date(2026, 9, 22), "focus_score": 0.50,
                          "rank": 1}])
    with get_engine().begin() as conn:   # as score.py writes them (autoincrement id)
        conn.execute(score_snapshots.insert(), [
            {"ts": t0, "ticker": "AAA", "focus_score": 0.10, "rank": 9},    # oldest - ignored
            {"ts": t0 + timedelta(hours=2), "ticker": "AAA", "focus_score": 0.42, "rank": 3},
            {"ts": t0 + timedelta(hours=4), "ticker": "AAA", "focus_score": 0.50, "rank": 1},
        ])
    fired = [a for a in alerts.evaluate({**alerts.DEFAULT_RULES, "score_jump": 0.05})
             if a["kind"] == "score move"]
    assert len(fired) == 1
    assert fired[0]["detail"].startswith("Focus +0.080")


def test_signal_label_transitions_alert_once():
    import json
    from datetime import date, timedelta

    from bioterm import alerts
    from bioterm.db import bulk_upsert, init_db, signal_scores

    init_db()
    d1, d2 = date.today() - timedelta(days=1), date.today()
    top = json.dumps([{"title": "Phase 3 readout in 40 days", "side": "BUY"}])
    bulk_upsert(signal_scores, [
        {"ticker": "AAA", "asof": d1, "label": "NEUTRAL", "net": 0.1, "top": "[]"},
        {"ticker": "AAA", "asof": d2, "label": "STRONG BUY", "net": 0.62, "top": top},
        {"ticker": "BBB", "asof": d1, "label": "SELL", "net": -0.3, "top": "[]"},
        {"ticker": "BBB", "asof": d2, "label": "SELL", "net": -0.32, "top": "[]"},
    ])
    sig = [a for a in alerts.evaluate() if a["kind"] == "signal"]
    assert [a["ticker"] for a in sig] == ["AAA"]
    assert sig[0]["detail"].startswith("NEUTRAL → STRONG BUY")
    assert alerts.run(deliver=False)["new"] >= 1
    assert alerts.run(deliver=False)["new"] == 0
