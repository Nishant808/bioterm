"""13F specialist-fund holdings: parsing a real information table, choosing the
filings, mapping CUSIPs to tickers, and the quarter-over-quarter changes."""
from datetime import date
from pathlib import Path

import pandas as pd

from bioterm.db import bulk_upsert, init_db, read_sql, securities
from bioterm.ingest import institutions as inst
from bioterm.process import smart_money

FIX = Path(__file__).parent / "fixtures"


def test_parse_real_infotable_keeps_equity_and_skips_notes():
    rows = inst.parse_infotable((FIX / "13f_infotable_sample.xml").read_bytes(),
                                filed=date(2026, 8, 14))
    by = {r["cusip"]: r for r in rows}
    assert by["004225108"]["issuer"] == "ACADIA Pharmaceuticals Inc."
    assert by["004225108"]["shares"] == 42912904
    assert by["004225108"]["value"] == 1085696471          # whole dollars post-2023
    assert "15102KAA8" not in by                             # PRN convertible note skipped
    assert "15102K100" in by                                 # the same issuer's stock kept
    assert len(rows) == 6


def test_pre_2023_values_are_in_thousands():
    rows = inst.parse_infotable((FIX / "13f_infotable_sample.xml").read_bytes(),
                                filed=date(2022, 11, 14))
    assert {r["cusip"]: r for r in rows}["004225108"]["value"] == 1085696471 * 1000


def test_options_rows_are_skipped():
    xml = b"""<informationTable xmlns="x"><infoTable><nameOfIssuer>Foo Inc</nameOfIssuer>
      <cusip>111111111</cusip><value>10</value><shrsOrPrnAmt><sshPrnamt>5</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><putCall>Call</putCall></infoTable>
      <infoTable><nameOfIssuer>Foo Inc</nameOfIssuer><cusip>111111111</cusip><value>7</value>
      <shrsOrPrnAmt><sshPrnamt>3</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
      </infoTable><infoTable><nameOfIssuer>Foo Inc</nameOfIssuer><cusip>111111111</cusip>
      <value>2</value><shrsOrPrnAmt><sshPrnamt>1</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>
      </shrsOrPrnAmt></infoTable></informationTable>"""
    rows = inst.parse_infotable(xml)
    assert rows == [{"cusip": "111111111", "issuer": "Foo Inc", "title_class": "",
                     "shares": 4.0, "value": 9.0}]


def test_latest_filings_one_per_period_newest_first():
    subs = {"filings": {"recent": {
        "form": ["13F-HR", "4", "13F-HR/A", "13F-HR", "13F-HR"],
        "accessionNumber": ["a3", "x", "a2am", "a2", "a1"],
        "filingDate": ["2026-08-14", "2026-08-01", "2026-06-01", "2026-05-15", "2026-02-17"],
        "reportDate": ["2026-06-30", "", "2026-03-31", "2026-03-31", "2025-12-31"],
    }}}
    got = inst.latest_13f_filings(subs)
    assert [g["accession"] for g in got] == ["a3", "a2"]
    assert got[0]["period"] == date(2026, 6, 30)


def test_pick_infotable_from_a_real_directory_listing():
    idx = {"directory": {"item": [
        {"name": "0001104659-26-097191-index.html", "size": ""},
        {"name": "infotable.xml", "size": "39786"},
        {"name": "primary_doc.xml", "size": "2136"}]}}
    assert inst.pick_infotable(idx) == "infotable.xml"
    odd = {"directory": {"item": [{"name": "primary_doc.xml", "size": "9"},
                                  {"name": "form13fInfoTable_2026.xml", "size": "1"}]}}
    assert inst.pick_infotable(odd) == "form13fInfoTable_2026.xml"


def test_issuer_names_match_universe_names():
    secs = pd.DataFrame({"ticker": ["ACAD", "ALKS", "VRTX", "BEAM"],
                         "name": ["ACADIA PHARMACEUTICALS INC", "Alkermes Plc",
                                  "Vertex Pharmaceuticals Inc", "Beam Therapeutics Inc"]})
    exact, core = inst.name_index(secs)
    assert inst.match_issuer("ACADIA Pharmaceuticals Inc.", exact, core) == "ACAD"
    assert inst.match_issuer("Alkermes plc", exact, core) == "ALKS"
    assert inst.match_issuer("Vertex Pharmaceuticals Incorporated", exact, core) == "VRTX"
    assert inst.match_issuer("Beam Benefits Holdings", exact, core) is None


def _holdings(rows):
    init_db()
    from bioterm.db import inst_filers, inst_holdings

    bulk_upsert(inst_filers, [{"cik": "1", "name": "Fund One", "short_name": "One"},
                              {"cik": "2", "name": "Fund Two", "short_name": "Two"}])
    bulk_upsert(inst_holdings, [{"id": f"{c}|{p}|{cu}", "cik": c, "period": p, "cusip": cu,
                                 "issuer": cu, "ticker": tk, "shares": s, "value": s * 10}
                                for c, p, cu, tk, s in rows])


def test_fund_changes_and_consensus():
    q1, q2 = date(2026, 3, 31), date(2026, 6, 30)
    _holdings([
        ("1", q1, "AAA", "AAAA", 100), ("1", q2, "AAA", "AAAA", 150),   # added 50%
        ("1", q1, "BBB", "BBBB", 100),                                    # exited
        ("1", q2, "CCC", "CCCC", 10),                                     # new
        ("2", q1, "AAA", "AAAA", 50), ("2", q2, "AAA", "AAAA", 52),       # held
        ("2", q2, "CCC", "CCCC", 5),                                      # new
    ])
    ch = smart_money.fund_changes().set_index(["cik", "cusip"])
    assert ch.loc[("1", "AAA"), "status"] == "added"
    assert ch.loc[("1", "BBB"), "status"] == "exited"
    assert ch.loc[("1", "CCC"), "status"] == "new"
    assert ch.loc[("2", "AAA"), "status"] == "held"
    summ = smart_money.ticker_summary().set_index("key")
    assert summ.loc["CCCC", "new"] == 2 and summ.loc["CCCC", "net_flow"] == 2
    assert summ.loc["BBBB", "exited"] == 1 and summ.loc["BBBB", "holders"] == 0
    assert summ.loc["AAAA", "holders"] == 2


def test_stale_funds_and_stub_filings_are_not_read_as_exits():
    old0, old1 = date(2024, 9, 30), date(2024, 12, 31)
    q1, q2 = date(2026, 3, 31), date(2026, 6, 30)
    book = [(f"C{i:02d}", f"T{i:02d}") for i in range(12)]
    _holdings(
        # fund 1 stopped filing in 2024 (its last "13F" lists one line)
        [("1", old0, c, t, 100) for c, t in book] + [("1", old1, "ZZZ", None, 1)]
        # fund 2 files a stub quarter between two full ones
        + [("2", q1, c, t, 100) for c, t in book] + [("2", q2, "C00", "T00", 100)]
        + [("2", date(2025, 12, 31), c, t, 90) for c, t in book]
        # fund 3 is current
        + [("3", q1, "C00", "T00", 10), ("3", q2, "C00", "T00", 20)])
    ch = smart_money.fund_changes()
    assert "1" not in set(ch["cik"])                       # stale fund dropped entirely
    f2 = ch[ch["cik"] == "2"]
    assert set(f2["period"].dt.date) == {q1}              # stub quarter skipped
    assert not (f2["status"] == "exited").any()
    assert ch[ch["cik"] == "3"]["status"].tolist() == ["added"]


def test_run_fetches_new_periods_once_and_maps_tickers(monkeypatch):
    init_db()
    bulk_upsert(securities, [{"ticker": "ACAD", "name": "ACADIA PHARMACEUTICALS INC"}])
    calls = []
    subs = {"name": "BAKER BROS. ADVISORS LP", "filings": {"recent": {
        "form": ["13F-HR"], "accessionNumber": ["0001104659-26-097191"],
        "filingDate": ["2026-08-14"], "reportDate": ["2026-06-30"]}}}

    def fake_json(url, params=None, **kw):
        calls.append(url)
        if "submissions" in url:
            return subs
        if url.endswith("index.json"):
            return {"directory": {"item": [{"name": "infotable.xml", "size": "10"}]}}
        raise AssertionError(url)

    monkeypatch.setattr(inst, "get_json", fake_json)
    monkeypatch.setattr(inst, "get_bytes",
                        lambda url, **kw: (FIX / "13f_infotable_sample.xml").read_bytes())
    monkeypatch.setattr(inst, "openfigi_lookup", lambda cusips: {c: None for c in cusips})
    from bioterm.config import load_settings as real

    def one_fund():
        s = real()
        s.funds = [{"name": "Baker Bros. Advisors LP", "short": "Baker Bros",
                    "cik": "1263508"}]
        return s
    monkeypatch.setattr(inst, "load_settings", one_fund)

    out = inst.run()
    assert out["periods_fetched"] == 1
    h = read_sql("SELECT cusip, ticker, value FROM inst_holdings").set_index("cusip")
    assert h.loc["004225108", "ticker"] == "ACAD"
    assert len(h) == 6
    n_calls = len(calls)
    assert inst.run()["periods_fetched"] == 0          # period already stored
    assert len(calls) == n_calls + 1                    # only the submissions check
