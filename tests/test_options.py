from datetime import date

import pandas as pd

from bioterm.ingest import options as opt


def _chain(strikes, iv, bid, ask, vol, oi):
    return pd.DataFrame({"strike": strikes, "impliedVolatility": iv, "bid": bid,
                         "ask": ask, "lastPrice": ask, "volume": vol, "openInterest": oi})


def test_chain_metrics_atm_iv_and_implied_move():
    calls = _chain([90, 100, 110], [0.9, 1.0, 1.1], [12, 6, 2], [13, 7, 3], [10, 50, 5], [100, 200, 50])
    puts = _chain([90, 100, 110], [1.2, 1.2, 1.3], [2, 7, 12], [3, 8, 13], [5, 30, 1], [80, 150, 20])
    m = opt.chain_metrics(calls, puts, spot=101.0)
    assert round(m["atm_iv"], 3) == 1.1                  # mean of the 100-strike call/put
    assert round(m["implied_move"], 4) == round((6.5 + 7.5) / 101.0, 4)
    assert m["call_volume"] == 65 and m["put_oi"] == 250


def test_combine_flow_ratios():
    f = {"atm_iv": 1.0, "implied_move": 0.2, "call_volume": 100, "put_volume": 300,
         "call_oi": 100, "put_oi": 100}
    b = {"atm_iv": 0.8, "implied_move": 0.3, "call_volume": 0, "put_volume": 100,
         "call_oi": 100, "put_oi": 100}
    c = opt.combine(f, b)
    assert c["pc_volume_ratio"] == 4.0 and c["vol_oi_ratio"] == 1.25
    assert c["iv_back"] == 0.8 and c["implied_move"] == 0.2


def test_pick_expiries_skips_this_week_and_spaces_the_back_month():
    exps = ["2026-09-25", "2026-10-02", "2026-10-16", "2026-11-20"]
    assert opt.pick_expiries(exps, date(2026, 9, 24)) == ("2026-10-02", "2026-11-20")
    assert opt.pick_expiries([], date(2026, 9, 24)) == (None, None)
