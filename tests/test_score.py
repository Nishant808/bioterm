from datetime import date, datetime, timezone

from bioterm.db import (bulk_upsert, catalysts, fundamentals, init_db, news,
                        read_sql, scores, securities, technicals)
from bioterm.process import score


def _seed_two_names():
    init_db()
    bulk_upsert(securities, [
        {"ticker": "NEAR", "name": "Near Cat Bio", "is_watchlist": 0},
        {"ticker": "FARC", "name": "Far Cat Bio", "is_watchlist": 0},
    ])
    today = date.today()
    for tk in ("NEAR", "FARC"):
        bulk_upsert(technicals, [{
            "ticker": tk, "date": today, "close": 10.0, "rsi14": 55.0,
            "macd": 0.1, "macd_signal": 0.0, "vol_z20": 0.5,
            "pct_52w_range": 0.5, "ret_1m": 0.05, "ret_3m": 0.1, "ret_6m": 0.2,
        }])
        bulk_upsert(fundamentals, [{
            "ticker": tk, "cash": 5e8, "burn_ttm": 2e8, "runway_quarters": 10.0,
            "net_income_ttm": -2e8, "updated_at": datetime.now(timezone.utc),
        }])


def test_nearer_catalyst_scores_higher():
    _seed_two_names()
    bulk_upsert(catalysts, [
        {"id": "c-near", "ticker": "NEAR", "type": "phase3_readout",
         "title": "near", "date": date.today(), "months_away": 1.0,
         "confidence": "high", "source": "t", "url": "",
         "created_at": datetime.now(timezone.utc)},
        {"id": "c-far", "ticker": "FARC", "type": "phase3_readout",
         "title": "far", "date": date.today(), "months_away": 5.5,
         "confidence": "high", "source": "t", "url": "",
         "created_at": datetime.now(timezone.utc)},
    ])
    score.run()
    df = read_sql("SELECT ticker, focus_score, catalyst FROM scores").set_index("ticker")
    assert df.loc["NEAR", "catalyst"] > df.loc["FARC", "catalyst"]
    assert df.loc["NEAR", "focus_score"] > df.loc["FARC", "focus_score"]


def test_conviction_multiplier_lifts_score(monkeypatch):
    _seed_two_names()
    import bioterm.process.score as score_mod

    real_load = score_mod.load_settings

    def patched():
        s = real_load()
        s.watchlist = [{"ticker": "NEAR", "conviction": 5}]
        return s

    monkeypatch.setattr(score_mod, "load_settings", patched)
    score.run()
    df = read_sql("SELECT ticker, conviction_mult FROM scores").set_index("ticker")
    assert df.loc["NEAR", "conviction_mult"] > df.loc["FARC", "conviction_mult"]


def test_short_runway_raises_risk():
    init_db()
    bulk_upsert(securities, [
        {"ticker": "RICH", "name": "Rich Bio", "is_watchlist": 0},
        {"ticker": "POOR", "name": "Poor Bio", "is_watchlist": 0},
    ])
    bulk_upsert(fundamentals, [
        {"ticker": "RICH", "runway_quarters": 12.0, "net_income_ttm": -1e8,
         "updated_at": datetime.now(timezone.utc)},
        {"ticker": "POOR", "runway_quarters": 1.5, "net_income_ttm": -1e8,
         "updated_at": datetime.now(timezone.utc)},
    ])
    score.run()
    df = read_sql("SELECT ticker, risk FROM scores").set_index("ticker")
    assert df.loc["POOR", "risk"] > df.loc["RICH", "risk"]
