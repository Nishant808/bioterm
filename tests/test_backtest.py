"""Backtest engine on a synthetic universe with a known answer: names drift at
persistent, different rates, so momentum must rank them (positive IC, positive
top-minus-bottom spread) - and nothing may peek at the future."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from bioterm.db import bulk_upsert, init_db, prices, read_sql, securities, signal_scores
from bioterm.process import backtest as bt
from bioterm.process.signals import price_features


def _seed(n_names=20, n_days=520, seed=3):
    init_db()
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(end=date.today() - timedelta(days=1), periods=n_days)
    rows, names = [], []
    for i in range(n_names):
        tk = f"T{i:02d}"
        drift = (i - n_names / 2) * 0.0004               # persistent winners and losers
        r = drift + rng.normal(0, 0.012, n_days)
        c = 20 * np.exp(np.cumsum(r))
        v = rng.lognormal(13, 0.3, n_days)
        rows += [{"ticker": tk, "date": d.date(), "open": x, "high": x * 1.01,
                  "low": x * 0.99, "close": float(x), "volume": float(vv)}
                 for d, x, vv in zip(days, c, v)]
        names.append({"ticker": tk, "name": f"{tk} Bio"})
    xbi = 90 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n_days)))
    rows += [{"ticker": "XBI", "date": d.date(), "open": x, "high": x, "low": x,
              "close": float(x), "volume": 1e6} for d, x in zip(days, xbi)]
    bulk_upsert(prices, rows)
    bulk_upsert(securities, names)
    return days


def test_forward_returns_are_future_only():
    f = price_features(pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=5),
                                     "close": [10, 11, 12, 13, 14], "high": 1, "low": 1,
                                     "volume": 1}))
    bt.add_forward(f, [2])
    assert f["fwd_2"].iloc[0] == 12 / 10 - 1
    assert f["fwd_2"].iloc[-2:].isna().all()          # no future -> no label


def test_run_writes_all_three_studies_and_finds_momentum():
    days = _seed()
    # a couple of historical calls for the track record
    bulk_upsert(signal_scores, [
        {"ticker": "T19", "asof": days[300].date(), "label": "BUY", "net": 0.4,
         "close": None},
        {"ticker": "T00", "asof": days[300].date(), "label": "SELL", "net": -0.4,
         "close": None}])
    closes = read_sql("SELECT ticker, close FROM prices WHERE date = :d",
                      {"d": str(days[300].date())}).set_index("ticker")["close"]
    bulk_upsert(signal_scores, [
        {"ticker": t, "asof": days[300].date(), "label": lab, "net": n,
         "close": float(closes[t])} for t, lab, n in (("T19", "BUY", 0.4), ("T00", "SELL", -0.4))])

    out = bt.run()
    assert out["rows"] == 3 and out["names"] == 20
    kinds = set(read_sql("SELECT kind FROM backtests")["kind"])
    assert kinds == {"events", "factor", "track"}

    fac = bt.latest("factor")
    mom = fac["factors"]["momentum"]
    assert mom["ic_21"] > 0.05
    q = mom["quintiles_63"]
    assert q[-1] > q[0] and mom["spread_63"] > 0
    eq = fac["equity"]
    assert len(eq["date"]) == len(eq["top"]) == len(eq["universe"]) == len(eq["xbi"])
    assert eq["top"][-1] > eq["universe"][-1]

    ev = bt.latest("events")
    assert ev["n_events"] > 0 and ev["by_code"]
    any_code = next(iter(ev["by_code"].values()))
    assert {"side", "n", "mean_21", "hit_21", "t_21"} <= set(any_code)

    tr = bt.latest("track")
    assert tr["by_label"]["BUY"]["x_21"] > 0 and tr["by_label"]["SELL"]["hit_21"] == 1.0


def test_calibration_reads_the_event_study():
    import json

    from bioterm.db import backtests
    from bioterm.process import signals as sg

    init_db()
    bulk_upsert(backtests, [{"id": "events|x", "kind": "events", "ts": pd.Timestamp.now(),
                             "params": "{}", "results": json.dumps({"by_code": {
                                 "breakout_52w": {"side": "BUY", "n": 120, "t_63": 3.0},
                                 "death_cross": {"side": "SELL", "n": 80, "t_63": 2.0},
                                 "rare": {"side": "BUY", "n": 30, "t_63": 9.0}}})}])
    cal = sg.calibration()
    assert cal["breakout_52w"] == 1.3               # strong edge, capped
    assert cal["death_cross"] == 0.8                # a SELL whose stocks went *up*: dampened
    assert "rare" not in cal                        # too few events to trust
