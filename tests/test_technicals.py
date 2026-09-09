import numpy as np
import pandas as pd

from bioterm.process.technicals import atr, macd, rsi


def test_rsi_all_gains_is_100():
    close = pd.Series(np.arange(1, 60, dtype=float))
    assert rsi(close).iloc[-1] > 99


def test_rsi_all_losses_is_0():
    close = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert rsi(close).iloc[-1] < 1


def test_rsi_flat_is_50():
    close = pd.Series([100.0] * 40)
    assert abs(rsi(close).iloc[-1] - 50.0) < 1e-6


def test_macd_crossover_sign():
    # ramp up then down -> histogram should flip sign
    up = np.linspace(10, 30, 40)
    down = np.linspace(30, 10, 40)
    close = pd.Series(np.concatenate([up, down]))
    _, _, hist = macd(close)
    assert hist.iloc[35] > 0
    assert hist.iloc[-1] < 0


def test_atr_positive_and_scales_with_range():
    n = 40
    base = pd.DataFrame(
        {"high": [11.0] * n, "low": [9.0] * n, "close": [10.0] * n}
    )
    wide = pd.DataFrame(
        {"high": [15.0] * n, "low": [5.0] * n, "close": [10.0] * n}
    )
    assert atr(base).iloc[-1] > 0
    assert atr(wide).iloc[-1] > atr(base).iloc[-1]


def test_indicators_pipeline_writes_rows(monkeypatch):
    from bioterm.db import bulk_upsert, init_db, prices, read_sql
    from bioterm.process import technicals

    init_db()
    dates = pd.bdate_range("2024-01-01", periods=260)
    rng = np.random.default_rng(0)
    px = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    rows = [
        {
            "ticker": "TEST", "date": d.date(),
            "open": p, "high": p * 1.02, "low": p * 0.98,
            "close": p, "adj_close": p, "volume": 1_000_000 + i * 10,
        }
        for i, (d, p) in enumerate(zip(dates, px))
    ]
    bulk_upsert(prices, rows)
    out = technicals.run(["TEST"])
    assert out["rows"] > 0
    t = read_sql("SELECT * FROM technicals WHERE ticker='TEST' ORDER BY date DESC")
    assert not t.empty
    assert t.iloc[0]["rsi14"] is not None
    assert 0 <= t.iloc[0]["pct_52w_range"] <= 1
