"""Real-time layer against captured live payloads (tests/fixtures): Nasdaq halts
RSS, EDGAR current-filings Atom, Nasdaq quote JSON, EDGAR full-text search and
Federal Register notices - plus the alert sources, "why it moved", the pulse
lease and the wire-only news pass."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

FX = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    from bioterm.db import init_db

    init_db()


# ---------------------------------------------------------------- parsers
def test_halts_feed_parses_codes_and_times():
    from bioterm.ingest import halts

    rows = halts.parse((FX / "nasdaq_halts.xml").read_bytes())
    assert len(rows) == 17
    kitt = next(r for r in rows if r["symbol"] == "KITT")
    assert kitt["reason"] == "T1" and kitt["market"] == "NASDAQ"
    # 19:50 New York (EDT) on 09/24/2026 is 23:50 UTC
    assert kitt["halt_at"] == datetime(2026, 9, 24, 23, 50, tzinfo=timezone.utc)
    assert {r["reason"] for r in rows} == {"T1", "T12", "H11"}
    assert halts.label("T1") == "News pending" and halts.label("ZZ") == "ZZ"


def test_edgar_current_feed_parses_and_maps_to_universe():
    from bioterm.ingest import edgar_live

    entries = edgar_live.parse((FX / "edgar_current_8k.atom").read_bytes())
    assert len(entries) == 40
    duke = entries[0]
    assert duke["form"] == "8-K" and duke["cik"] == "0001326160"
    assert duke["accession"] == "0001104659-26-110588" and duke["filed"] == "2026-09-25"
    assert duke["items"] == "5.02,8.01,9.01" and duke["url"].endswith("-index.htm")
    rows = edgar_live.to_rows(entries, {"0001326160": "DUK"})
    assert len(rows) == 1 and rows[0]["id"] == "DUK:0001104659-26-110588"
    assert rows[0]["source"] == "live"
    sc = [{**duke, "form": "SC 13G", "role": "Filed by"}, {**duke, "form": "SC 13G",
                                                         "role": "Subject"}]
    assert len(edgar_live.to_rows(sc, {"0001326160": "DUK"})) == 1


def test_quote_parsers():
    from bioterm import quotes

    q = quotes.parse_nasdaq_quote(json.loads((FX / "nasdaq_quote_vrtx.json").read_text()))
    assert q["price"] == 523.21 and abs(q["prev_close"] - 522.38) < 1e-9
    assert q["provider"] == "nasdaq" and q["asof"] == pd.Timestamp("2026-09-25 06:23")
    f = quotes.parse_finnhub_quote({"c": 10.5, "d": 0.5, "dp": 5, "pc": 10.0, "t": 1790000000})
    assert f["price"] == 10.5 and abs(f["change_pct"] - 0.05) < 1e-12
    assert quotes.parse_finnhub_quote({"c": 0}) is None


def test_quotes_fail_over_to_nasdaq_then_stored(monkeypatch, db):
    from bioterm import quotes
    from bioterm.db import bulk_upsert, prices

    monkeypatch.setenv("BIOTERM_LIVE_PRICES", "1")
    quotes.clear_cache()
    monkeypatch.setattr(quotes, "_yahoo", lambda t: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(quotes, "_nasdaq", lambda t: quotes.parse_nasdaq_quote(
        json.loads((FX / "nasdaq_quote_vrtx.json").read_text())) if t == "VRTX" else None)
    d = date.today()
    bulk_upsert(prices, [{"ticker": "ZZZZ", "date": d - timedelta(days=i), "close": 5.0 + i}
                         for i in range(2)])
    got = quotes.quotes(["VRTX", "ZZZZ"])
    assert got["VRTX"]["provider"] == "nasdaq" and got["VRTX"]["source"] == "live"
    assert got["ZZZZ"]["source"] == "stored" and got["ZZZZ"]["price"] == 5.0
    quotes.clear_cache()


def test_pdufa_regex_efts_and_fedreg(monkeypatch, db):
    from bioterm.db import bulk_upsert, read_sql, securities
    from bioterm.ingest import pdufa

    today = date(2026, 9, 25)
    assert pdufa.pdufa_dates("The FDA assigned a PDUFA target action date of March 15, 2027.",
                             today) == [date(2027, 3, 15)]
    assert pdufa.pdufa_dates("extended the PDUFA goal date from January 10, 2027 to April 10, "
                             "2027", today) == [date(2027, 4, 10)]
    assert pdufa.pdufa_dates("the Prescription Drug User Fee Act (PDUFA) requires", today) == []
    doc = json.loads((FX / "fedreg_doc.json").read_text())
    assert pdufa.meeting_date(doc["dates"]) == date(2026, 10, 30)
    assert pdufa.sponsors("NDA 219694, for atropine sulfate ophthalmic solution, 0.01%, "
                          "submitted by Sydnexis, Inc., for the proposed indication") == \
        ["Sydnexis, Inc"]

    bulk_upsert(securities, [{"ticker": "CAPR", "name": "CAPRICOR THERAPEUTICS, INC.",
                              "cik": "0001133869"}])
    efts = json.loads((FX / "efts_pdufa.json").read_text())
    monkeypatch.setattr("bioterm.httpx_util.get_json",
                        lambda *a, **k: efts if k.get("params", a[1] if len(a) > 1 else {})
                        .get("from", 0) == 0 else {"hits": {"hits": []}})
    pdufa_day = date.today() + timedelta(days=60)
    body = (f"<p>The FDA set a PDUFA target action date of {pdufa_day:%B %d, %Y} for "
            f"deramiocel.</p>").encode()
    monkeypatch.setattr("bioterm.httpx_util.get_bytes", lambda *a, **k: body)
    out = pdufa.run_edgar(days=60)
    assert out["rows"] >= 1
    row = read_sql("SELECT * FROM news_llm WHERE ticker = 'CAPR'").iloc[0]
    assert str(row["pdufa_date"])[:10] == pdufa_day.isoformat()
    again = pdufa.run_edgar(days=60)           # already-read filings are skipped
    assert again["fetched"] == 0

    from bioterm.process import catalysts

    catalysts.run()
    cat = read_sql("SELECT * FROM catalysts WHERE ticker = 'CAPR' AND type = 'pdufa'")
    assert len(cat) == 1 and cat.iloc[0]["source"] == "sec-filing"


# ---------------------------------------------------------------- alert sources
def _seed_universe():
    from bioterm import store
    from bioterm.db import bulk_upsert, securities

    bulk_upsert(securities, [{"ticker": t, "name": f"{t} BIO", "cik": f"{i:010d}"}
                             for i, t in enumerate(["AAAA", "BBBB"], start=1)])
    store.add_to_watchlist("AAAA", 4)


def test_halt_filing_and_mover_alerts(db):
    from bioterm import alerts, realtime, store
    from bioterm.db import bulk_upsert, filings, halts

    _seed_universe()
    now = datetime.now(timezone.utc)
    bulk_upsert(halts, [
        {"id": "AAAA|x|1", "symbol": "AAAA", "ticker": "AAAA", "reason": "T1",
         "halt_at": now - timedelta(minutes=20), "fetched_at": now},
        {"id": "ZZZZ|x|1", "symbol": "ZZZZ", "ticker": None, "reason": "T1",
         "halt_at": now, "fetched_at": now},
        {"id": "BBBB|x|1", "symbol": "BBBB", "ticker": "BBBB", "reason": "M2",
         "halt_at": now, "fetched_at": now}])
    bulk_upsert(filings, [
        {"id": "AAAA:1", "ticker": "AAAA", "form": "8-K", "items": "8.01",
         "filed_date": now.date(), "url": "https://www.sec.gov/x", "fetched_at": now},
        {"id": "BBBB:2", "ticker": "BBBB", "form": "8-K", "items": "8.01",
         "filed_date": now.date(), "url": "https://www.sec.gov/y", "fetched_at": now},
        {"id": "BBBB:3", "ticker": "BBBB", "form": "424B5", "filed_date": now.date(),
         "url": "https://www.sec.gov/z", "fetched_at": now}])
    store.set_meta(realtime.MOVERS_KEY, {"ts": now.isoformat(), "movers": [
        {"ticker": "BBBB", "price": 4.2, "change_pct": -0.31,
         "why": [{"kind": "filing", "text": "424B5", "when": "x", "url": None}]},
        {"ticker": "AAAA", "price": 10.0, "change_pct": 0.05, "why": []}]})
    fired = alerts.evaluate()
    kinds = {(a["kind"], a["ticker"]) for a in fired}
    assert ("halt", "AAAA") in kinds and ("halt", "BBBB") not in kinds      # M2 is noise
    assert ("filing", "AAAA") in kinds                                       # watchlist 8-K
    assert ("filing", "BBBB") in kinds                                       # anyone's 424B5
    assert sum(1 for a in fired if a["kind"] == "filing" and a["ticker"] == "BBBB") == 1
    mv = [a for a in fired if a["kind"] == "mover"]
    assert [m["ticker"] for m in mv] == ["BBBB"] and "-31.0%" in mv[0]["detail"]
    w = realtime.why("AAAA")
    assert {i["kind"] for i in w} >= {"halt", "filing"}


def test_pulse_runs_every_stage_and_holds_a_lease(monkeypatch, db):
    from bioterm import realtime
    from bioterm.ingest import edgar_live, halts, news

    _seed_universe()
    monkeypatch.setattr(halts, "run", lambda *a, **k: {"rows": 3})
    monkeypatch.setattr(edgar_live, "run", lambda *a, **k: {"rows": 1})
    seen = {}
    monkeypatch.setattr(news, "run", lambda t=None, g=None, scopes=("sector",): seen.update(
        scopes=scopes) or {"rows": 2})
    monkeypatch.setattr(realtime, "record_movers", lambda *a, **k: {"rows": 0})
    out = realtime.pulse(deliver=False)
    assert out["halts"]["rows"] == 3 and seen["scopes"] == ("wire",)
    assert realtime.state()["last_run"]
    assert realtime.acquire_lease(owner="a") and not realtime.acquire_lease(owner="b")
    realtime.release_lease(owner="a")
    assert realtime.acquire_lease(owner="b")


def test_wire_only_news_pass_skips_google(monkeypatch, db):
    from bioterm.db import bulk_upsert, read_sql, securities
    from bioterm.ingest import news

    bulk_upsert(securities, [{"ticker": "AAAA", "name": "Aaaa Therapeutics Inc"}])
    urls = []

    class _E(dict):
        pass

    def fake_feed(url):
        urls.append(url)
        return [_E(link="https://gnw/1", title="Aaaa Therapeutics (Nasdaq: AAAA) reports "
                                                 "positive topline Phase 3 results",
                   summary="", published_parsed=datetime.now(timezone.utc).timetuple())]

    monkeypatch.setattr(news, "_parse_feed", fake_feed)
    monkeypatch.setattr("bioterm.process.finbert.reapply", lambda: None)
    news.run(["AAAA"], None, ("wire",))
    assert urls and all("globenewswire" in u or "prnewswire" in u for u in urls)
    assert read_sql("SELECT ticker FROM news").iloc[0]["ticker"] == "AAAA"
    assert not any("news.google.com" in u for u in urls)


def test_market_calendar_gate_cli_output(capsys):
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / "src/bioterm/market_calendar.py"), "gate",
                        "session"], capture_output=True, text=True, check=True)
    lines = r.stdout.strip().splitlines()
    assert lines[0].startswith("window=") and lines[-1] in ("run=true", "run=false")
