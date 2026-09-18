from datetime import date, datetime, timezone

from bioterm.db import bulk_upsert, filing_risk_flags, init_db, read_sql
from bioterm.ingest.edgar import (
    _latest_per_ticker,
    check_going_concern,
    has_going_concern_doubt,
)

GC_TEXT = (
    "Note 2. Going Concern. These conditions raise substantial doubt about the "
    "Company's ability to continue as a going concern within one year of the "
    "date these financial statements were issued."
)

NO_GC_TEXT = "Note 2. Liquidity. The Company believes its cash is sufficient for the next 12 months."

RESOLVED_GC_TEXT = (
    "Following the financing, management concluded there is no longer substantial "
    "doubt about the Company's ability to continue as a going concern."
)


def test_has_going_concern_doubt_detects_standard_language():
    assert has_going_concern_doubt(GC_TEXT) is True


def test_has_going_concern_doubt_false_when_absent():
    assert has_going_concern_doubt(NO_GC_TEXT) is False


def test_has_going_concern_doubt_respects_negation():
    # the same standard phrase, but explicitly resolved earlier in the filing -
    # a naive substring match would still flag this as a live risk.
    assert has_going_concern_doubt(RESOLVED_GC_TEXT) is False


def test_latest_per_ticker_picks_most_recent():
    rows = [
        {"ticker": "AAAA", "form": "10-Q", "filed_date": date(2026, 1, 1), "id": "old", "url": "u"},
        {"ticker": "AAAA", "form": "10-Q", "filed_date": date(2026, 6, 1), "id": "new", "url": "u"},
        {"ticker": "AAAA", "form": "8-K", "filed_date": date(2026, 7, 1), "id": "8k", "url": "u"},
        {"ticker": "BBBB", "form": "10-K", "filed_date": date(2026, 3, 1), "id": "b", "url": "u"},
    ]
    out = _latest_per_ticker(rows, {"10-K", "10-Q"})
    assert out["AAAA"]["id"] == "new"  # newer 10-Q wins, the 8-K isn't a risk form
    assert out["BBBB"]["id"] == "b"


def test_check_going_concern_bounded_and_idempotent(monkeypatch):
    init_db()
    calls = []

    def fake_get_bytes(url, **kwargs):
        calls.append(url)
        return GC_TEXT.encode() if "AAAA" in url else NO_GC_TEXT.encode()

    monkeypatch.setattr("bioterm.ingest.edgar.get_bytes", fake_get_bytes)

    candidates = {
        "AAAA": {"id": "aaaa:1", "form": "10-K", "filed_date": date(2026, 1, 1), "url": "http://x/AAAA"},
        "BBBB": {"id": "bbbb:1", "form": "10-K", "filed_date": date(2026, 1, 1), "url": "http://x/BBBB"},
    }
    n = check_going_concern(candidates, max_fetches=1)
    assert n == 1  # budget of 1 - only the first candidate gets fetched
    assert len(calls) == 1

    n2 = check_going_concern(candidates, max_fetches=10)
    # the one already checked is skipped; only the remaining one is fetched
    assert n2 == 1
    assert len(calls) == 2

    flags = read_sql("SELECT ticker, going_concern FROM filing_risk_flags").set_index("ticker")
    assert flags.loc["AAAA", "going_concern"] == 1
    assert flags.loc["BBBB", "going_concern"] == 0


def test_going_concern_flag_lowers_focus_score():
    from bioterm.db import fundamentals, securities, technicals
    from bioterm.process import score

    init_db()
    now = datetime.now(timezone.utc)
    for tk in ("FLAG", "CLEAN"):
        bulk_upsert(securities, [{"ticker": tk, "name": tk, "is_watchlist": 0}])
        bulk_upsert(technicals, [{"ticker": tk, "date": date.today(), "close": 10.0,
                                  "rsi14": 55, "macd": 0.1, "macd_signal": 0.0,
                                  "vol_z20": 0.5, "pct_52w_range": 0.5,
                                  "ret_1m": 0.05, "ret_3m": 0.1, "ret_6m": 0.2}])
        bulk_upsert(fundamentals, [{"ticker": tk, "runway_quarters": 12.0,
                                    "net_income_ttm": -1e8, "updated_at": now}])
    bulk_upsert(filing_risk_flags, [
        {"id": "flag:1", "ticker": "FLAG", "form": "10-K", "filed_date": date.today(),
         "going_concern": 1, "checked_at": now},
    ])
    score.run()
    s = read_sql("SELECT ticker, focus_score FROM scores WHERE ticker IN ('FLAG','CLEAN')").set_index("ticker")
    assert s.loc["FLAG", "focus_score"] < s.loc["CLEAN", "focus_score"]
