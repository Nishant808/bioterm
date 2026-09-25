"""Platform: the SIC-code universe expansion and coverage tiers, point-in-time
snapshots, data-quality checks, retention, backup/restore, the live per-detector
record and the read-only API."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    from bioterm.db import init_db

    init_db()


def _secs(rows):
    from bioterm.db import bulk_upsert, securities

    now = datetime.now(timezone.utc)
    bulk_upsert(securities, [{"name": r[0], "is_watchlist": 0, "in_xbi": 1, "in_ibb": 0,
                              "in_seed": 0, "updated_at": now, **r[1]} for r in rows])


# ---------------------------------------------------------------- SIC universe
def test_sic_feed_parses_ciks_and_next_page():
    from bioterm.ingest.sic_universe import parse_feed

    rows, nxt = parse_feed((FIX / "edgar_sic_2835.atom").read_bytes())
    assert [r["cik"] for r in rows] == ["0000857171", "0000949858", "0000834306"]
    assert {r["sic"] for r in rows} == {"2835"} and rows[0]["state"] == "NJ"
    assert nxt and "start=10" in nxt and "output=atom" in nxt


def _feed(ciks, sic="2836", more=True):
    ents = "".join(f"<entry><content type='text/xml'><company-info><cik>{c:010d}</cik>"
                   f"<sic>{sic}</sic><state>MA</state></company-info></content></entry>"
                   for c in ciks)
    nxt = ("<link href='https://www.sec.gov/cgi-bin/browse-edgar?x=1&amp;start=9' "
           "rel='next' type='application/atom+xml' />") if more else ""
    return (f"<?xml version='1.0' encoding='ISO-8859-1' ?><feed "
            f"xmlns='http://www.w3.org/2005/Atom'>{ents}{nxt}</feed>").encode("latin-1")


def test_sic_crawl_retries_then_skips_a_bad_page(monkeypatch):
    import bioterm.httpx_util as hu
    from bioterm.ingest import sic_universe as su

    calls = []

    def fake(url, **kw):
        start = int(url.split("start=")[1].split("&")[0])
        calls.append(start)
        if start == 0:
            return _feed(range(1, 101))
        if start == 100:
            raise TimeoutError("read timed out")
        return _feed(range(201, 251), more=False)

    monkeypatch.setattr(hu, "get_bytes", fake)
    monkeypatch.setattr(su.time, "sleep", lambda s: None)
    found, complete = su.crawl(("2836",))
    assert len(found) == 150 and not complete
    assert calls == [0, 100, 100, 100, 200]          # 3 tries, then the next page


def test_exchange_file_drops_otc_and_keeps_primary_ticker():
    from bioterm.ingest.sic_universe import parse_exchange_file

    data = {"fields": ["cik", "name", "ticker", "exchange"],
            "data": [[949858, "Achieve Life Sciences", "ACHV", "Nasdaq"],
                     [949858, "Achieve Life Sciences", "ACHVW", "Nasdaq"],
                     [857171, "Dynagen", "DYNG", "OTC"],
                     [834306, "Biosite", "BSTE", None],
                     [1, "Big Pharma", "BIGP", "NYSE"]]}
    m = parse_exchange_file(data)
    assert set(m) == {"0000949858", "0000000001"}
    assert m["0000949858"]["ticker"] == "ACHV" and m["0000000001"]["exchange"] == "NYSE"
    assert parse_exchange_file({"fields": ["x"], "data": [[1]]}) == {}


def test_sic_plan_adds_extended_tags_core_and_retires_only_on_full_crawl():
    from bioterm.ingest.sic_universe import plan

    found = {"0000000001": "2834", "0000000002": "2836", "0000000003": "2835"}
    listing = {"0000000001": {"ticker": "CORE", "name": "Core Co", "exchange": "Nasdaq"},
               "0000000002": {"ticker": "NEWX", "name": "New Bio", "exchange": "NYSE"}}
    existing = [{"ticker": "CORE", "cik": "0000000001", "tier": "core"},
                {"ticker": "OLDX", "cik": "0000000009", "tier": "extended"},
                {"ticker": "BACK", "cik": "0000000003", "tier": "inactive"}]
    p = plan(found, listing, existing, complete=True)
    assert [r["ticker"] for r in p["new"]] == ["NEWX"] and p["new"][0]["tier"] == "extended"
    assert {"ticker": "CORE", "sic": "2834", "cik": "0000000001"} in p["tag"]
    assert p["retire"] == [{"ticker": "OLDX", "tier": "inactive"}]
    # BACK is unlisted in the ticker file -> neither tagged nor new
    assert not any(r["ticker"] == "BACK" for r in p["tag"] + p["new"])
    assert plan(found, listing, existing, complete=False)["retire"] == []


def test_tiers_select_core_extended_and_rotate(db, monkeypatch):
    from bioterm import universe

    _secs([("Core A", {"ticker": "AAA", "tier": "core", "etf_weight": 2.0}),
           ("Core B", {"ticker": "BBB", "tier": None, "etf_weight": 1.0}),
           ("Ext C", {"ticker": "CCC", "tier": "extended", "in_xbi": 0}),
           ("Ext D", {"ticker": "DDD", "tier": "extended", "in_xbi": 0}),
           ("Gone", {"ticker": "EEE", "tier": "inactive", "in_xbi": 0})])
    assert universe.universe_tickers() == ["AAA", "BBB"]
    assert universe.universe_tickers(tier="extended") == ["CCC", "DDD"]
    assert set(universe.universe_tickers(tier="all")) == {"AAA", "BBB", "CCC", "DDD"}
    assert universe.extended_slice(1, "t") == ["CCC"]
    assert universe.extended_slice(1, "t") == ["DDD"]
    assert universe.extended_slice(1, "t") == ["CCC"]


def test_watchlist_promotes_extended_name_to_core(db):
    from bioterm import store
    from bioterm.db import read_sql

    _secs([("Ext", {"ticker": "XTND", "tier": "extended", "in_xbi": 0})])
    store.add_to_watchlist("XTND", 4)
    row = read_sql("SELECT tier, is_watchlist FROM securities WHERE ticker = 'XTND'").iloc[0]
    assert row["tier"] == "core" and int(row["is_watchlist"]) == 1


def test_rebuild_demotes_names_that_left_xbi_but_keeps_sic(db, monkeypatch):
    from bioterm import universe
    from bioterm.db import bulk_upsert, read_sql, securities

    _secs([("Stays", {"ticker": "STAY", "tier": "core"}),
           ("Leaves", {"ticker": "LEFT", "tier": "core"})])
    bulk_upsert(securities, [{"ticker": "STAY", "sic": "2836", "cik": "0000000007"}],
                update_only=["sic", "cik"])
    monkeypatch.setattr(universe, "fetch_xbi", lambda: pd.DataFrame(
        {"ticker": ["STAY"], "name": ["Stays Inc"], "weight": [1.0]}))
    monkeypatch.setattr(universe, "load_settings", lambda: type("C", (), {
        "raw": {"universe": {"use_ibb": False, "use_seed": False,
                             "include_watchlist": False}}, "seed": []})())
    universe.build_universe(force=True)
    df = read_sql("SELECT ticker, tier, sic, cik FROM securities").set_index("ticker")
    assert df.loc["STAY", "tier"] == "core" and df.loc["STAY", "sic"] == "2836"
    assert df.loc["STAY", "cik"] == "0000000007"
    assert df.loc["LEFT", "tier"] == "extended"


def test_rebuild_with_failed_xbi_demotes_nobody(db, monkeypatch):
    from bioterm import universe
    from bioterm.db import read_sql

    _secs([("Member", {"ticker": "MEMB", "tier": "core"})])

    def boom():
        raise RuntimeError("ssga down")

    monkeypatch.setattr(universe, "fetch_xbi", boom)
    monkeypatch.setattr(universe, "load_settings", lambda: type("C", (), {
        "raw": {"universe": {"use_ibb": False, "use_seed": True, "include_watchlist": False}},
        "seed": [{"ticker": "SEED", "name": "Seed"}]})())
    universe.build_universe(force=True)
    assert read_sql("SELECT tier FROM securities WHERE ticker = 'MEMB'").iloc[0]["tier"] \
        == "core"


def test_score_and_signals_skip_extended(db):
    from bioterm.db import bulk_upsert, prices, read_sql
    from bioterm.process import score, signals, technicals

    _secs([("Core", {"ticker": "CORE", "tier": "core"}),
           ("Ext", {"ticker": "EXTN", "tier": "extended", "in_xbi": 0})])
    d0 = date.today() - timedelta(days=400)
    rows = [{"ticker": tk, "date": d0 + timedelta(days=i), "open": 10 + i * .01,
             "high": 10.5 + i * .01, "low": 9.5 + i * .01, "close": 10 + i * .01,
             "adj_close": 10 + i * .01, "volume": 1e5} for tk in ("CORE", "EXTN")
            for i in range(300)]
    bulk_upsert(prices, rows)
    technicals.run()
    score.run()
    signals.run()
    assert set(read_sql("SELECT ticker FROM scores")["ticker"]) == {"CORE"}
    assert set(read_sql("SELECT ticker FROM signal_scores")["ticker"]) <= {"CORE"}


# ---------------------------------------------------------------- snapshots
def test_snapshots_store_changes_and_rebuild_the_past(db):
    from bioterm.db import bulk_upsert, catalysts, fundamentals, read_sql
    from bioterm.process import snapshots

    _secs([("Core", {"ticker": "CORE", "tier": "core"}),
           ("Ext", {"ticker": "EXTN", "tier": "extended", "in_xbi": 0})])
    bulk_upsert(fundamentals, [{"ticker": "CORE", "market_cap": 1e9, "short_percent_float": .1},
                               {"ticker": "EXTN", "market_cap": 2e8}])
    d1, d2, d3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
    bulk_upsert(catalysts, [{"id": "c1", "ticker": "CORE", "type": "pdufa",
                             "date": date(2026, 11, 1), "confidence": "high", "source": "x"},
                            {"id": "c2", "ticker": "CORE", "type": "phase3_readout",
                             "date": date(2026, 12, 1), "confidence": "medium", "source": "y"}])
    r1 = snapshots.run(d1)
    assert r1["fundamentals"] == 1 and r1["catalyst_changes"] == 2 and r1["universe"] == 2
    r2 = snapshots.run(d2)                       # nothing changed
    assert r2["catalyst_changes"] == 0 and r2["universe"] == 0
    from bioterm.db import get_engine
    from sqlalchemy import text

    with get_engine().begin() as c:
        c.execute(text("DELETE FROM catalysts WHERE id = 'c2'"))
    bulk_upsert(fundamentals, [{"ticker": "CORE", "short_percent_float": .2}],
                update_only=["short_percent_float"])
    r3 = snapshots.run(d3)
    assert r3["catalyst_changes"] == 1           # the tombstone
    assert set(snapshots.catalysts_known_on(d2)["id"]) == {"c1", "c2"}
    assert set(snapshots.catalysts_known_on(d3)["id"]) == {"c1"}
    assert snapshots.members_on(d2) == {"CORE", "EXTN"}
    h = read_sql("SELECT asof, short_percent_float FROM fundamental_snapshots "
                 "WHERE ticker = 'CORE' ORDER BY asof")
    assert h["short_percent_float"].tolist() == [.1, .1, .2]


# ---------------------------------------------------------------- data quality
def test_dq_flags_bad_bars_and_future_rows(db):
    from bioterm.db import bulk_upsert, filings, prices, read_sql
    from bioterm.process import dq

    _secs([("Core", {"ticker": "CORE", "tier": "core"})])
    today = date.today()
    bulk_upsert(prices, [{"ticker": "CORE", "date": today - timedelta(days=2), "open": 10,
                          "high": 9, "low": 11, "close": 10, "volume": 1}])
    bulk_upsert(filings, [{"id": "0001-26-1", "ticker": "CORE", "form": "8-K",
                           "filed_date": today + timedelta(days=5)}])
    res = dq.run()
    assert res["rows"] == len(dq.CHECKS)
    got = dq.latest().set_index("check")
    assert got.loc["invalid OHLC bars", "status"] == "warn"
    assert got.loc["future-dated rows", "status"] == "warn"
    assert got.loc["core universe size", "status"] == "fail"       # 1 name, not 100
    assert set(got["status"]) <= {"ok", "warn", "fail"}
    assert not read_sql("SELECT * FROM dq_checks").empty


# ---------------------------------------------------------------- retention + backup
def test_retention_prunes_only_old_rows(db):
    from bioterm import maintenance
    from bioterm.db import alerts_fired, bulk_upsert, read_sql, short_volume

    now = datetime.now(timezone.utc)
    bulk_upsert(alerts_fired, [{"id": "old", "ts": now - timedelta(days=400), "kind": "x"},
                               {"id": "new", "ts": now - timedelta(days=2), "kind": "x"}])
    bulk_upsert(short_volume, [{"ticker": "A", "date": date.today() - timedelta(days=500),
                                "short_volume": 1},
                               {"ticker": "A", "date": date.today(), "short_volume": 2}])
    dry = maintenance.retention(dry_run=True)
    assert dry["tables"] == {"alerts_fired": 1, "short_volume": 1}
    assert len(read_sql("SELECT * FROM alerts_fired")) == 2
    maintenance.retention()
    assert read_sql("SELECT id FROM alerts_fired")["id"].tolist() == ["new"]
    assert len(read_sql("SELECT * FROM short_volume")) == 1


def test_backup_restore_round_trip_without_secrets(db, tmp_path, monkeypatch):
    from bioterm import maintenance, store, vault
    from bioterm.db import bulk_upsert, get_engine, ingest_runs, prices, read_sql
    from sqlalchemy import text

    monkeypatch.setenv("BIOTERM_SECRET_KEY", "k" * 32)
    vault.reset_key_cache()
    _secs([("Core", {"ticker": "CORE", "tier": "core"})])
    bulk_upsert(prices, [{"ticker": "CORE", "date": date(2026, 9, 1), "close": 1.5,
                          "volume": None}])
    bulk_upsert(ingest_runs, [{"id": 7, "job": "x", "started_at": datetime(2026, 9, 1, 12),
                               "status": "ok"}])
    store.set_meta("alert_rules", {"a": 1})
    store.set_meta("admin_auth", {"hash": "secret"})
    vault.set("ANTHROPIC_API_KEY", "sk-ant-test-123456")
    zp = tmp_path / "b.zip"
    res = maintenance.backup(zp)
    assert res["tables"] > 30 and zp.exists()
    import zipfile

    names = zipfile.ZipFile(zp).namelist()
    assert "app_secrets.jsonl" not in names and "manifest.json" in names
    with get_engine().begin() as c:
        for t in ("prices", "securities", "app_meta", "ingest_runs"):
            c.execute(text(f"DELETE FROM {t}"))
    out = maintenance.restore(zp, replace=True)
    assert out["tables"]["prices"] == 1
    p = read_sql("SELECT * FROM prices").iloc[0]
    assert p["close"] == 1.5 and str(p["date"])[:10] == "2026-09-01"
    assert store.get_meta("alert_rules") == {"a": 1}
    assert store.get_meta("admin_auth") is None
    assert int(read_sql("SELECT id FROM ingest_runs").iloc[0]["id"]) == 7


# ---------------------------------------------------------------- live detector record
def test_detector_record_counts_fresh_firings_and_excess(db):
    from bioterm.db import bulk_upsert, prices, signals
    from bioterm.process.backtest import detector_record

    d0 = date(2026, 1, 1)
    days = [d0 + timedelta(days=i) for i in range(120)]
    rows = []
    for i, d in enumerate(days):
        rows.append({"ticker": "UPUP", "date": d, "close": 10 * (1.01 ** i)})
        rows.append({"ticker": "FLAT", "date": d, "close": 10.0})
    bulk_upsert(prices, rows)
    sig = [{"id": f"s{i}", "asof": days[i], "ticker": "UPUP", "side": "BUY",
            "code": "insider_cluster", "strength": .5} for i in (0, 1, 2, 40)]
    bulk_upsert(signals, sig)
    r = detector_record(horizons=(5, 21))
    v = r["by_code"]["insider_cluster"]
    assert v["n"] == 2                     # days 0-2 are one firing; day 40 is new
    assert v["x_5"] > 0 and v["hit_5"] == 1.0


# ---------------------------------------------------------------- API
def test_api_requires_token_and_serves_json(db, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bioterm.api import create_app
    from bioterm.db import bulk_upsert, catalysts, scores

    _secs([("Core Co", {"ticker": "CORE", "tier": "core"}),
           ("Ext Co", {"ticker": "EXTN", "tier": "extended", "in_xbi": 0})])
    bulk_upsert(scores, [{"ticker": "CORE", "asof": date.today(), "focus_score": .7,
                          "rank": 1}])
    bulk_upsert(catalysts, [{"id": "c1", "ticker": "CORE", "type": "pdufa",
                             "date": date.today() + timedelta(days=30), "title": "PDUFA",
                             "confidence": "high", "source": "x"}])
    c = TestClient(create_app())
    assert c.get("/health").json()["ok"] is True
    assert c.get("/scores").status_code == 503               # no token configured
    monkeypatch.setenv("BIOTERM_API_TOKEN", "tok-123")
    assert c.get("/scores").status_code == 401
    h = {"Authorization": "Bearer tok-123"}
    assert c.get("/scores", headers=h).json()[0]["ticker"] == "CORE"
    assert [r["ticker"] for r in c.get("/universe", headers=h).json()] == ["CORE"]
    assert len(c.get("/universe?tier=all", headers=h).json()) == 2
    assert c.get("/catalysts?days=60", headers=h).json()[0]["type"] == "pdufa"
    st = c.get("/stock/core", headers=h).json()
    assert st["ticker"] == "CORE" and st["catalysts"][0]["title"] == "PDUFA"
    assert c.get("/stock/NOPE", headers=h).status_code == 404
    scr = c.get("/screen", params={"filter": "market_cap:>=:0"}, headers=h)
    assert scr.status_code == 200 and "rows" in scr.json()
    assert c.get("/screen?preset=nope", headers=h).status_code == 404
    json.dumps(c.get("/signals", headers=h).json())
