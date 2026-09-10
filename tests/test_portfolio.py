from datetime import datetime, timedelta

import pandas as pd

from bioterm import portfolio as pf


def _tr(rows):
    return pd.DataFrame(rows, columns=["ts", "ticker", "side", "qty", "price", "fees", "note"])


BASE = datetime(2026, 1, 1)


def test_cash_and_positions_average_cost():
    t = _tr([
        (BASE, "AAAA", "BUY", 100, 10.0, 5.0, ""),
        (BASE + timedelta(1), "AAAA", "BUY", 100, 12.0, 5.0, ""),
        (BASE + timedelta(2), "AAAA", "SELL", 50, 15.0, 5.0, ""),
    ])
    cash = pf.cash_balance(t, 100_000)
    # -1005 -1205 +745
    assert round(cash, 2) == round(100_000 - 1005 - 1205 + 745, 2)

    pos = pf.positions(t).set_index("ticker")
    # avg cost = (1005 + 1205) / 200 = 11.05
    assert abs(pos.loc["AAAA", "avg_cost"] - 11.05) < 1e-6
    assert pos.loc["AAAA", "qty"] == 150
    # realized = 50*(15 - 11.05) - 5 = 197.5 - 5 = 192.5
    assert abs(pos.loc["AAAA", "realized_pnl"] - 192.5) < 1e-6


def test_full_exit_zeros_position():
    t = _tr([
        (BASE, "BBBB", "BUY", 10, 20.0, 0.0, ""),
        (BASE + timedelta(1), "BBBB", "SELL", 10, 25.0, 0.0, ""),
    ])
    pos = pf.positions(t).set_index("ticker")
    assert pos.loc["BBBB", "qty"] == 0
    assert abs(pos.loc["BBBB", "realized_pnl"] - 50.0) < 1e-6


def test_mark_to_market():
    t = _tr([(BASE, "CCCC", "BUY", 100, 10.0, 0.0, "")])
    s = pf.mark_to_market(t, {"CCCC": 13.0}, 5_000)
    assert s["cash"] == 4_000
    assert s["invested"] == 1_300
    assert s["equity"] == 5_300
    assert abs(s["total_return"] - 0.06) < 1e-9
    assert abs(s["unrealized_pnl"] - 300) < 1e-6
    assert s["n_positions"] == 1


def test_validate_trade():
    t = _tr([(BASE, "DDDD", "BUY", 10, 100.0, 0.0, "")])  # $1000 of $1500 spent
    assert pf.validate_trade(t, 1_500, "EEEE", "BUY", 4, 100.0, 0) is None  # $400 ≤ $500
    assert "insufficient cash" in pf.validate_trade(t, 1_500, "EEEE", "BUY", 20, 100.0, 0)
    assert "hold" in pf.validate_trade(t, 1_500, "DDDD", "SELL", 15, 100.0, 0)
    assert pf.validate_trade(t, 1_500, "DDDD", "SELL", 10, 100.0, 0) is None
    assert "positive" in pf.validate_trade(t, 1_500, "DDDD", "BUY", 0, 10.0, 0)


def test_equity_curve_runs():
    t = _tr([
        (BASE, "FFFF", "BUY", 100, 10.0, 0.0, ""),
        (BASE + timedelta(3), "FFFF", "BUY", 50, 11.0, 0.0, ""),
    ])
    days = pd.date_range(BASE, BASE + timedelta(5))
    ph = pd.DataFrame({"ticker": "FFFF", "date": days,
                       "close": [10, 10.5, 11, 11, 12, 12.5]})
    c = pf.equity_curve(t, ph, 10_000)
    assert not c.empty
    assert (c["equity"] > 0).all()
    # day 0: 100 sh @10 + 9000 cash = 10000
    assert abs(c.iloc[0]["equity"] - 10_000) < 1e-6


def test_store_roundtrip():
    from bioterm.db import init_db
    from bioterm import store

    init_db()
    pid = store.pf_create("Test Strat", 50_000)
    store.pf_add_trade(pid, "ggg", "BUY", 10, 5.0, 1.0, "hi", ts=BASE)
    tr = store.pf_get_trades(pid)
    assert len(tr) == 1 and tr.iloc[0]["ticker"] == "GGG"
    store.pf_reset(pid)
    assert store.pf_get_trades(pid).empty
    store.pf_delete(pid)
    assert pid not in {p["id"] for p in store.pf_list()}
