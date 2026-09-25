"""Dashboard live prices: Yahoo frames parsed into quotes/histories, the US market
clock, indicators on the live history, and the labelled stored-close fallback."""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
import _live as live  # noqa: E402

NY = ZoneInfo("America/New_York")


def _bars(closes, start="2026-09-21", tz=True):
    idx = pd.date_range(start, periods=len(closes), freq="B", tz=NY if tz else None)
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * .99, "Close": c,
                         "Adj Close": c, "Volume": 1e6}, index=idx)


def test_quotes_from_a_batch_download():
    raw = pd.concat({"AAA": _bars([10, 11, 12]), "BBB": _bars([20, 19, np.nan])}, axis=1)
    q = live.quotes_from_download(raw, ["AAA", "BBB", "ZZZ"])
    assert q["AAA"]["price"] == 12 and q["AAA"]["prev_close"] == 11
    assert abs(q["AAA"]["change_pct"] - (12 / 11 - 1)) < 1e-12
    assert q["BBB"]["price"] == 19                 # a NaN bar (no trade yet) is skipped
    assert "ZZZ" not in q and q["AAA"]["source"] == "live"
    one = live.quotes_from_download(_bars([5, 6]), ["CCC"])        # single-ticker shape
    assert one["CCC"]["price"] == 6


def test_history_is_normalised_to_naive_new_york_time():
    h = live._norm_history(_bars([1, 2, np.nan, 4]))
    assert list(h.columns) == live.COLS and len(h) == 3
    assert h["date"].dt.tz is None and h["close"].iloc[-1] == 4


def test_market_clock():
    at = lambda *a: datetime(*a, tzinfo=NY)  # noqa: E731
    assert live.market_state(at(2026, 9, 25, 10, 0))[0] == "open"
    assert live.market_state(at(2026, 9, 25, 8, 0))[0] == "pre"
    assert live.market_state(at(2026, 9, 25, 17, 0))[0] == "after"
    assert live.market_state(at(2026, 9, 26, 12, 0))[0] == "closed"      # Saturday


def test_indicators_on_live_history():
    h = live._norm_history(_bars(list(np.linspace(10, 30, 260)), start="2025-09-01"))
    t = live.indicators(h)
    last = t.iloc[-1]
    assert last["sma20"] > last["sma50"] > last["sma200"]
    assert last["rsi14"] > 70 and abs(last["pct_52w_range"] - 1) < 1e-9
    assert last["ret_1m"] > 0


def test_offline_falls_back_to_stored_closes_and_says_so():
    from datetime import date, timedelta

    from bioterm.db import bulk_upsert, init_db, prices

    init_db()
    d = date.today()
    bulk_upsert(prices, [{"ticker": "AAA", "date": d - timedelta(days=i), "open": 1,
                          "high": 1, "low": 1, "close": 10.0 + i, "volume": 1}
                         for i in range(3)])
    live._stored_quotes.clear()
    live._stored_history.clear()
    q = live.quote("AAA")                          # BIOTERM_LIVE_PRICES=0 in conftest
    assert q["source"] == "stored" and q["price"] == 10.0 and q["prev_close"] == 11.0
    h, src = live.history("AAA", "1y")
    assert src == "stored" and len(h) == 3
    assert live.history("AAA", "1d", "5m")[0].empty          # no intraday from the DB
    assert "unavailable" in live.source_note("stored")
