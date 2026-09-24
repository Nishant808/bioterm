from datetime import datetime, timezone

from bioterm.db import bulk_upsert, init_db, news, read_sql
from bioterm.process import finbert


def _seed():
    init_db()
    now = datetime.now(timezone.utc)
    bulk_upsert(news, [
        {"id": "a", "ticker": "AAA", "title": "Aaa misses primary endpoint - Reuters",
         "published": now, "sentiment": 0.1},
        {"id": "b", "ticker": "BBB", "title": "Bbb wins FDA approval", "published": now,
         "sentiment": 0.3},
    ])


def stub(texts):
    return [{"positive": 0.05, "negative": 0.9, "neutral": 0.05} if "misses" in t
            else {"positive": 0.8, "negative": 0.1, "neutral": 0.1} for t in texts]


def test_scores_unscored_headlines_once_and_records_provenance():
    _seed()
    seen = []

    def spy(texts):
        seen.extend(texts)
        return stub(texts)

    out = finbert.run(scorer=spy)
    assert out["rows"] == 2
    assert "Aaa misses primary endpoint" in seen          # publisher tail stripped
    n = read_sql("SELECT id, sentiment FROM news").set_index("id")["sentiment"]
    assert n["a"] == -0.85 and n["b"] == 0.7
    x = read_sql("SELECT * FROM news_nlp").set_index("id")
    assert x.loc["a", "vader"] == 0.1 and x.loc["a", "label"] == "negative"
    assert finbert.run(scorer=spy)["rows"] == 0             # already scored


def test_noop_without_the_nlp_extra(monkeypatch):
    _seed()
    monkeypatch.setattr(finbert, "available", lambda: False)
    assert finbert.run()["rows"] == 0
    assert read_sql("SELECT sentiment FROM news WHERE id='a'").iloc[0, 0] == 0.1


def test_clean_title_and_tone():
    assert finbert.clean_title("Drug X approved - FiercePharma") == "Drug X approved"
    assert finbert.clean_title("Phase 3 - topline due in Q4") == "Phase 3 - topline due in Q4"
    assert finbert.clean_title("Twist jumps on AI deal - timothysykes.com") == "Twist jumps on AI deal"
    assert finbert.to_tone({"positive": 0.7, "negative": 0.2, "neutral": 0.1}) == (0.5, "positive", 0.7)


def test_reingested_headlines_keep_their_finbert_tone():
    init_db()
    now = datetime.now(timezone.utc)
    bulk_upsert(news, [{"id": "a", "title": "Drug X approved", "published": now,
                        "sentiment": 0.1}])
    finbert.run(scorer=lambda texts: [{"positive": 0.9, "negative": 0.05,
                                       "neutral": 0.05} for _ in texts])
    # the next news ingest sees the same article in the feed and upserts VADER again
    bulk_upsert(news, [{"id": "a", "title": "Drug X approved", "published": now,
                        "sentiment": 0.1}])
    assert finbert.reapply() == 1
    assert read_sql("SELECT sentiment FROM news").iloc[0]["sentiment"] == 0.85
