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
