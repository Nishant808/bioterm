"""Signal engine: each detector fires on the pattern it names (and not on noise),
the composite maps strengths to labels, and a full run writes today's calls."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from bioterm.config import load_settings
from bioterm.db import (bulk_upsert, catalysts, filings, fundamentals, init_db, insider_txns,
                        news, prices, read_sql, securities)
from bioterm.process import signals as sg


def _frame(closes, vols=None, start="2024-01-01"):
    n = len(closes)
    d = pd.bdate_range(start, periods=n)
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"date": d, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                         "volume": vols if vols is not None else [1e6] * n})


def _quiet(n, level=10.0, seed=0):
    rng = np.random.default_rng(seed)
    return list(level * (1 + rng.normal(0, 0.004, n)))


def test_breakout_on_volume_fires_once_as_an_edge():
    closes = _quiet(300) + [11.5]
    vols = [1e6] * 300 + [6e6]
    ev = sg.technical_events(sg.price_features(_frame(closes, vols)))
    last = ev[ev["date"] == ev["date"].max()]
    assert {"breakout_52w", "volume_surge_up"} <= set(last["code"])
    assert (ev["code"] == "breakout_52w").sum() == 1


def test_no_breakout_without_volume():
    ev = sg.technical_events(sg.price_features(_frame(_quiet(300) + [11.5])))
    assert "breakout_52w" not in set(ev["code"])


def test_golden_and_death_crosses():
    down_up = list(np.linspace(20, 10, 220)) + list(np.linspace(10, 30, 120))
    ev = sg.technical_events(sg.price_features(_frame(down_up)))
    assert "golden_cross" in set(ev["code"])
    up_down = list(np.linspace(10, 30, 220)) + list(np.linspace(30, 8, 120))
    ev = sg.technical_events(sg.price_features(_frame(up_down)))
    assert "death_cross" in set(ev["code"])


def test_crash_day_and_live_window():
    closes = _quiet(260) + [6.0, 6.1, 6.0]
    f = sg.price_features(_frame(closes, [1e6] * 260 + [9e6, 3e6, 2e6]))
    ev = sg.technical_events(f)
    live = {s["code"]: s for s in sg.live_technical(ev, len(f))}
    assert "crash_day" in live and live["crash_day"]["side"] == "SELL"
    assert live["crash_day"]["detail"]["sessions_ago"] == 2
    # an edge older than the lookback no longer counts
    f2 = sg.price_features(_frame(closes + _quiet(10, 6.0)))
    live2 = {s["code"] for s in sg.live_technical(sg.technical_events(f2), len(f2))}
    assert "crash_day" not in live2


def test_accumulation_state_from_money_flow():
    n = 260
    closes = _quiet(n)
    df = _frame(closes)
    df["high"] = df["close"] * 1.01
    df["low"] = df["close"] * 0.95     # closes near the high every day -> strong money flow
    f = sg.price_features(df)
    live = {s["code"] for s in sg.live_technical(sg.technical_events(f), len(f))}
    assert "accumulation" in live


def test_relative_strength_rating():
    a = sg.price_features(_frame(list(np.linspace(10, 30, 300))))
    b = sg.price_features(_frame(list(np.linspace(30, 10, 300))))
    feats = {"UP": a, "DOWN": b}
    sg.add_rs_rating(feats)
    assert a["rs"].iloc[-1] > b["rs"].iloc[-1]


def test_composite_labels_regime_and_conviction():
    cfg = load_settings()
    buys = [{"code": "a", "side": "BUY", "strength": 0.5, "title": "", "detail": {},
             "family": "technical"},
            {"code": "b", "side": "BUY", "strength": 0.4, "title": "", "detail": {},
             "family": "people"}]
    _, c = sg.composite(buys, "neutral", 1.0, {}, cfg)
    assert c["bull"] == 0.7 and c["label"] == "STRONG BUY"
    # the same strength from one family alone is only a BUY (needs confluence)
    one = [{**b, "family": "technical"} for b in buys]
    _, c1 = sg.composite(one, "neutral", 1.0, {}, cfg)
    assert c1["bull"] == 0.7 and c1["label"] == "BUY"
    _, off = sg.composite(buys, "risk_off", 1.0, {}, cfg)
    assert off["bull"] < c["bull"]
    _, hi = sg.composite(buys[:1], "neutral", 1.4, {}, cfg)
    _, lo = sg.composite(buys[:1], "neutral", 0.6, {}, cfg)
    assert hi["bull"] > lo["bull"]
    sells = [{**buys[0], "side": "SELL", "strength": 0.6},
             {**buys[1], "side": "SELL", "strength": 0.2}]
    _, s = sg.composite(sells, "neutral", 1.0, {}, cfg)
    assert s["label"] == "STRONG SELL" and s["net"] == -0.68
    adj, cal = sg.composite(buys[:1], "neutral", 1.0, {"a": 1.3}, cfg)
    assert adj[0]["strength"] == 0.65


def _seed_market():
    init_db()
    today = date.today()
    days = pd.bdate_range(end=today, periods=300)
    rows = []
    rng = np.random.default_rng(1)
    for tk, path in {
        "XBI": np.linspace(80, 100, 300),                                 # risk-on tape
        "SETUP": 20 * (1 + rng.normal(0, 0.005, 300)),                    # quiet, catalyst ahead
        "DILUT": np.linspace(30, 12, 300),                                # downtrend + offering
    }.items():
        for d, c in zip(days, path):
            rows.append({"ticker": tk, "date": d.date(), "open": c, "high": c * 1.01,
                         "low": c * 0.99, "close": float(c), "volume": 1e6})
    bulk_upsert(prices, rows)
    bulk_upsert(securities, [{"ticker": t, "name": f"{t} Therapeutics Inc"} for t in ("SETUP", "DILUT")])
    now = datetime.now(timezone.utc)
    bulk_upsert(fundamentals, [
        {"ticker": "SETUP", "market_cap": 8e8, "runway_quarters": 10.0, "updated_at": now},
        {"ticker": "DILUT", "market_cap": 3e8, "runway_quarters": 2.0, "updated_at": now}])
    bulk_upsert(catalysts, [{"id": "c1", "ticker": "SETUP", "type": "phase3_readout",
                             "title": "Phase 3 topline", "date": today + timedelta(days=40),
                             "months_away": 1.3, "confidence": "high", "source": "t",
                             "url": "", "created_at": now}])
    bulk_upsert(filings, [{"id": "f1", "ticker": "DILUT", "form": "424B5",
                           "filed_date": today - timedelta(days=3), "url": "https://sec.gov/x"}])
    bulk_upsert(insider_txns, [
        {"id": f"i{i}", "ticker": "SETUP", "owner": f"Director {i}", "code": "P",
         "txn_date": today - timedelta(days=10), "value": 400000.0} for i in range(2)])
    bulk_upsert(news, [{"id": "n1", "ticker": "DILUT", "tickers_csv": "DILUT",
                        "title": "DILUT receives complete response letter",
                        "published": now - timedelta(days=1), "sentiment": -0.5,
                        "event_score": -1.0, "event_tags": "complete response letter",
                        "url": "https://x.com"}])


def test_run_end_to_end():
    _seed_market()
    out = sg.run()
    assert out["regime"] == "risk_on"
    ss = read_sql("SELECT * FROM signal_scores").set_index("ticker")
    assert ss.loc["SETUP", "label"] in ("BUY", "STRONG BUY")
    assert ss.loc["DILUT", "label"] in ("SELL", "STRONG SELL")
    codes = read_sql("SELECT ticker, code FROM signals")
    setup = set(codes[codes["ticker"] == "SETUP"]["code"])
    dilut = set(codes[codes["ticker"] == "DILUT"]["code"])
    assert {"pre_catalyst_setup", "insider_cluster_buy"} <= setup
    assert {"dilution_filing", "negative_event"} <= dilut
    assert "runway_crunch" not in dilut          # it already raised (424B5 three days ago)
    top = json.loads(ss.loc["SETUP", "top"])
    assert top and top[0]["side"] == "BUY"
    n = len(read_sql("SELECT id FROM signals"))
    sg.run()                                     # a second run today replaces, never duplicates
    assert len(read_sql("SELECT id FROM signals")) == n
