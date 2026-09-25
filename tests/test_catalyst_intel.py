"""Catalyst intelligence: trial change radar, outcome database and base rates,
implied vs realized moves, competitive landscape + read-through, PoS priors and
the industry calendar."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def db():
    from bioterm.db import init_db

    init_db()


# ---------------------------------------------------------------- trial radar
def test_trial_diff_kinds():
    from bioterm.process.trial_changes import diff

    base = {"nct_id": "NCT1", "status": "RECRUITING", "primary_completion_date": "2027-01-01",
            "enrollment": 300}
    k = lambda new: [c["kind"] for c in diff(base, {**base, **new})]  # noqa: E731
    assert k({"primary_completion_date": "2027-06-01"}) == ["date_slip"]
    assert k({"primary_completion_date": "2026-10-01"}) == ["date_pull_in"]
    assert k({"primary_completion_date": "2027-01-15"}) == []           # under 30 days
    assert k({"status": "ACTIVE_NOT_RECRUITING"}) == ["enrollment_complete"]
    assert k({"status": "SUSPENDED"}) == ["suspended"]
    assert k({"status": "TERMINATED", "enrollment": 90}) == ["terminated", "enrollment_change"]
    slip = diff(base, {**base, "primary_completion_date": "2027-06-01"})[0]
    assert slip["days"] == 151 and slip["id"] == diff(base, {**base, "primary_completion_date":
                                                                  "2027-06-01"})[0]["id"]


def test_trial_radar_records_once_and_fires_detectors(db):
    from bioterm.db import bulk_upsert, clinical_trials, read_sql, securities
    from bioterm.process import trial_changes
    from bioterm.process.signals import build_context, event_detectors
    from bioterm.config import load_settings

    bulk_upsert(securities, [{"ticker": "AAAA", "name": "AAAA BIO"}])
    now = datetime.now(timezone.utc)
    bulk_upsert(clinical_trials, [{"nct_id": "NCT1", "ticker": "AAAA", "phase": "P3",
                                   "status": "RECRUITING", "title": "Pivotal",
                                   "primary_completion_date": date(2027, 1, 1),
                                   "enrollment": 300, "fetched_at": now}])
    fresh = [{"nct_id": "NCT1", "ticker": "AAAA", "phase": "P3", "status": "SUSPENDED",
              "primary_completion_date": date(2027, 9, 1), "enrollment": 300}]
    assert trial_changes.record(fresh) == 2
    assert trial_changes.record(fresh) == 0                                 # idempotent
    kinds = set(read_sql("SELECT kind FROM trial_changes")["kind"])
    assert kinds == {"suspended", "date_slip"}
    ctx = build_context(date.today(), load_settings())
    det = load_settings().get("signals", "detectors", default={})
    fired = {f["code"]: f for f in event_detectors("AAAA", ctx, None, det, date.today())}
    assert "trial_halted" in fired and fired["trial_halted"]["side"] == "SELL"
    assert "readout_delay" in fired


# ---------------------------------------------------------------- outcomes
def _prices(ticker, closes, start="2025-01-02"):
    idx = pd.bdate_range(start, periods=len(closes))
    return [{"ticker": ticker, "date": d.date(), "close": float(c)} for d, c in zip(idx, closes)]


def test_around_event_returns():
    from bioterm.process.outcomes import around

    closes = np.r_[np.full(61, 10.0), [12.0], [15.0, 15.0, 15.0, 15.0, 15.0], np.full(30, 16.0)]
    s = pd.Series(closes, index=pd.bdate_range("2025-01-02", periods=len(closes)))
    ev_day = s.index[62].date()           # the 15.0 bar
    r = around(s, ev_day)
    assert abs(r["ret_pre60"] - 0.2) < 1e-9                  # 10 -> 12 before the event
    assert abs(r["ret_1d"] - (15 / 12 - 1)) < 1e-9           # 2-session reaction
    assert r["ret_21d"] is not None
    assert around(s, s.index[10].date()) == {}               # not enough history


def test_outcomes_db_and_base_rates(db, monkeypatch):
    from bioterm.db import bulk_upsert, fda_events, prices, read_sql, securities
    from bioterm.process import outcomes

    bulk_upsert(securities, [{"ticker": "AAAA", "name": "AAAA BIO"}])
    rng = np.random.default_rng(0)
    closes = 10 * np.cumprod(1 + rng.normal(0, 0.01, 400))
    bulk_upsert(prices, _prices("AAAA", closes) + _prices("XBI", np.full(400, 90.0)))
    d = pd.bdate_range("2025-01-02", periods=400)[200].date()
    bulk_upsert(fda_events, [{"id": "f1", "ticker": "AAAA", "kind": "approval",
                              "brand_name": "Aaaamab", "description": "ORIG 1 approved",
                              "event_date": d, "url": "https://fda.example/x"}])
    monkeypatch.setattr(outcomes, "efts_toplines", lambda *a, **k: [])
    out = outcomes.run()
    assert out["rows"] == 1 and out["with_returns"] == 1
    ev = read_sql("SELECT * FROM catalyst_events").iloc[0]
    assert ev["kind"] == "approval" and ev["direction"] == "pos" and ev["ret_1d"] is not None
    res = read_sql("SELECT results FROM backtests WHERE kind = 'outcomes'")
    assert '"approval"' in res.iloc[0]["results"]


def test_implied_vs_realized(db):
    from bioterm.db import (bulk_upsert, catalyst_events, catalysts, fundamentals,
                            options_snapshots)
    from bioterm.process.outcomes import implied_vs_realized

    today = date.today()
    bulk_upsert(catalysts, [{"id": "c1", "ticker": "AAAA", "type": "pdufa", "title": "PDUFA",
                             "date": today + timedelta(days=10)}])
    bulk_upsert(options_snapshots, [{"ticker": "AAAA", "date": today, "spot": 10,
                                     "expiry": today + timedelta(days=20), "atm_iv": 1.2,
                                     "iv_back": 0.9, "implied_move": 0.25}])
    bulk_upsert(fundamentals, [{"ticker": "AAAA", "market_cap": 5e8}])
    bulk_upsert(catalyst_events, [{"id": f"e{i}", "ticker": "AAAA", "kind": "topline",
                                   "event_date": today - timedelta(days=100 * i),
                                   "ret_1d": r, "mcap_bucket": "small"}
                                  for i, r in enumerate([0.1, -0.2, 0.3], start=1)])
    out = implied_vs_realized(30)
    row = out.iloc[0]
    assert row["implied_move"] == 0.25 and abs(row["own_median_move"] - 0.2) < 1e-9
    assert abs(row["implied_vs_history"] - 1.25) < 1e-9


# ---------------------------------------------------------------- landscape
def test_peers_and_read_through_alerts(db):
    from bioterm import alerts, store
    from bioterm.db import bulk_upsert, clinical_trials, securities
    from bioterm.process import landscape

    bulk_upsert(securities, [{"ticker": t, "name": f"{t} BIO"} for t in ("AAAA", "BBBB", "CCCC")])
    bulk_upsert(clinical_trials, [
        {"nct_id": "N1", "ticker": "AAAA", "phase": "P3", "status": "RECRUITING",
         "conditions": "Duchenne Muscular Dystrophy"},
        {"nct_id": "N2", "ticker": "BBBB", "phase": "P2", "status": "RECRUITING",
         "conditions": "Duchenne muscular dystrophy; Becker"},
        {"nct_id": "N3", "ticker": "CCCC", "phase": "P3", "status": "RECRUITING",
         "conditions": "Obesity"}])
    assert landscape.peers("AAAA") == {"BBBB": ["duchenne muscular dystrophy"]}
    store.add_to_watchlist("BBBB", 3)
    store.set_meta("movers_live", {"ts": datetime.now(timezone.utc).isoformat(), "movers": [
        {"ticker": "AAAA", "price": 5, "change_pct": -0.45,
         "why": [{"text": "Phase 3 missed its primary endpoint"}]}]})
    rt = [a for a in alerts.evaluate() if a["kind"] == "read-through"]
    assert [a["ticker"] for a in rt] == ["BBBB"] and "AAAA -45%" in rt[0]["detail"]


# ---------------------------------------------------------------- priors + calendar
def test_pos_priors_from_the_report():
    from bioterm.process.pos import area_of, loa

    assert area_of("Metastatic Non-small Cell Lung Cancer") == "oncology"
    assert area_of("Sickle Cell Disease") == "hematology"
    assert area_of("Chronic Lymphocytic Leukemia") == "oncology"      # blood cancers
    assert loa("P3", "Breast Cancer") == pytest.approx(0.439)
    assert loa("P1", "something unmapped") == pytest.approx(0.079)
    assert loa("P2", "Hemophilia A") == pytest.approx(0.344)
    assert loa("NA", "x") is None


def test_industry_calendar():
    from bioterm.process.industry_calendar import events

    ev = events(365, today=date(2026, 9, 25))
    names = set(ev["name"])
    assert "ESMO Congress 2026" in names and "ASH Annual Meeting 2026" in names
    chmp = ev[ev["kind"] == "chmp"]
    assert chmp.iloc[0]["start"] == date(2026, 10, 12)
    assert (ev["end"] >= date(2026, 9, 25)).all()
