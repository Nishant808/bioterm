"""Fundamentals & ownership: rNPV/SOTP, the screener (dilution + takeout scores,
saved screens and their alerts), whole-market 13F aggregation, Orange Book LOE,
FAERS, USAspending and ETF flows / XBI rebalance - on synthetic files shaped
like the real ones."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest


@pytest.fixture
def db():
    from bioterm.db import init_db

    init_db()


# ---------------------------------------------------------------- valuation
def test_rnpv_math():
    from bioterm.process.valuation import Inputs, rnpv, sales_curve

    i = Inputs(peak_sales=1e9, launch_year=2028, ramp_years=4, loe_year=2035, margin=0.5,
               tax=0.2, discount=0.10, erosion=0.5, dev_cost=100e6, dev_years=2)
    c = sales_curve(i, 2026, 2040)
    assert c[2027] == 0 and c[2028] == 250e6 and c[2031] == 1e9 and c[2035] == 1e9
    assert c[2036] == 500e6 and c[2037] == 250e6
    r_hi = rnpv(i, 0.8, today=date(2026, 1, 1))
    r_lo = rnpv(i, 0.2, today=date(2026, 1, 1))
    assert r_hi["rnpv"] > r_lo["rnpv"] and r_hi["npv_commercial"] > 0
    assert r_lo["rnpv"] == pytest.approx(0.2 * r_lo["npv_commercial"] - r_lo["npv_dev_cost"])
    royalty = rnpv(Inputs(**{**i.__dict__, "royalty": 0.1}), 0.8, today=date(2026, 1, 1))
    assert royalty["npv_commercial"] < r_hi["npv_commercial"]      # 10% vs 40% of sales


def test_sotp_from_saved_valuations(db):
    from bioterm import store
    from bioterm.db import bulk_upsert, fundamentals
    from bioterm.process import valuation

    mid = store.save_molecule({"ticker": "AAAA", "name": "aaaamab", "aliases": "",
                               "indication": "x", "nct_ids": ""})
    bulk_upsert(fundamentals, [{"ticker": "AAAA", "cash": 2e8, "total_debt": 5e7,
                                "shares_out": 1e8, "market_cap": 5e8}])
    res = valuation.save(mid, valuation.Inputs(peak_sales=8e8, pos=0.5))
    sp = valuation.sotp("AAAA")
    assert sp["parts"][0]["rnpv"] == pytest.approx(res["rnpv"])
    assert sp["equity_value"] == pytest.approx(res["rnpv"] + 2e8 - 5e7)
    assert sp["per_share"] == pytest.approx(sp["equity_value"] / 1e8)


# ---------------------------------------------------------------- screener
def _seed_screen():
    from bioterm.db import (bulk_upsert, catalysts, clinical_trials, filings, fundamentals,
                            securities, technicals)

    today = date.today()
    now = datetime.now(timezone.utc)
    bulk_upsert(securities, [{"ticker": t, "name": f"{t} BIO", "is_watchlist": 0}
                             for t in ("CASH", "BURN", "TAKE")])
    bulk_upsert(fundamentals, [
        {"ticker": "CASH", "market_cap": 1e8, "cash": 3e8, "total_debt": 0,
         "runway_quarters": 12, "shares_out": 1e7},
        {"ticker": "BURN", "market_cap": 4e8, "cash": 5e7, "runway_quarters": 2,
         "shares_out": 1e8, "warrants_out": 3e7},
        {"ticker": "TAKE", "market_cap": 3e9, "cash": 9e8, "runway_quarters": 10,
         "shares_out": 1e8}])
    bulk_upsert(filings, [{"id": "BURN:1", "ticker": "BURN", "form": "S-3",
                           "filed_date": today - timedelta(days=200), "fetched_at": now}])
    bulk_upsert(clinical_trials, [{"nct_id": "N1", "ticker": "TAKE", "phase": "P3",
                                   "status": "RECRUITING", "conditions": "Breast Cancer"}])
    bulk_upsert(technicals, [{"ticker": t, "date": today, "close": 10, "pct_52w_range": 0.4,
                              "ret_3m": 0.1} for t in ("CASH", "BURN", "TAKE")])
    bulk_upsert(catalysts, [{"id": "c", "ticker": "TAKE", "type": "phase3_readout",
                             "title": "P3 data", "date": today + timedelta(days=30)}])


def test_screener_scores_and_presets(db):
    from bioterm import screener

    _seed_screen()
    df = screener.frame().set_index("ticker")
    assert df.loc["CASH", "below_cash"] and not df.loc["TAKE", "below_cash"]
    assert df.loc["BURN", "dilution_risk"] >= 0.8                # runway + shelf + warrants
    assert df.loc["CASH", "dilution_risk"] == 0
    assert df.loc["TAKE", "takeout_score"] > df.loc["BURN", "takeout_score"]
    assert df.loc["TAKE", "binary_within_90d"] and df.loc["TAKE", "top_phase"] == "P3"
    got = screener.apply(df.reset_index(), screener.PRESETS["Below cash, funded"])
    assert got["ticker"].tolist() == ["CASH"]
    rng = screener.apply(df.reset_index(), [{"field": "market_cap", "op": "between",
                                            "value": [2e8, 5e9]}])
    assert set(rng["ticker"]) == {"BURN", "TAKE"}


def test_saved_screen_alerts_fire_once_on_entry(db):
    from bioterm import alerts, screener
    from bioterm.db import bulk_upsert, fundamentals

    _seed_screen()
    sid = screener.save_screen("cheap", [{"field": "below_cash", "op": "is", "value": True}],
                               alert=True)
    assert [a for a in alerts.evaluate() if a["kind"] == "screen"] == []   # CASH already in
    bulk_upsert(fundamentals, [{"ticker": "BURN", "market_cap": 1e7}], update_only=["market_cap"])
    fired = [a for a in alerts.evaluate() if a["kind"] == "screen"]
    assert [a["ticker"] for a in fired] == ["BURN"]
    assert [a for a in alerts.evaluate() if a["kind"] == "screen"]          # evaluate is pure
    alerts.run(deliver=False)                                                # commits members
    assert [a for a in alerts.evaluate() if a["kind"] == "screen"] == []
    screener.delete_screen(sid)
    assert screener.list_screens().empty


# ---------------------------------------------------------------- 13F data sets
def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, body in files.items():
            zf.writestr(n, body)
    return buf.getvalue()


def _13f(period: str, rows: list[tuple]) -> bytes:
    sub = "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
    cov = "ACCESSION_NUMBER\tFILINGMANAGER_NAME\n"
    info = ("ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tVALUE\t"
            "SSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\n")
    seen = set()
    for acc, cik, mgr, issuer, cusip, value, shares, putcall in rows:
        if acc not in seen:
            sub += f"{acc}\t01-AUG-2026\t13F-HR\t{cik}\t{period}\n"
            cov += f"{acc}\t{mgr}\n"
            seen.add(acc)
        info += f"{acc}\t1\t{issuer}\tCOM\t{cusip}\t{value}\t{shares}\tSH\t{putcall}\n"
    return _zip({"SUBMISSION.tsv": sub, "COVERPAGE.tsv": cov, "INFOTABLE.tsv": info})


def test_whole_market_13f(tmp_path):
    from bioterm.ingest import whole13f

    html = ('<a href="/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip">'
            '<a href="/files/structureddata/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip">')
    urls = whole13f.dataset_urls(html)
    assert urls[0].endswith("01jun2026-31aug2026_form13f.zip") and len(urls) == 2
    cur = tmp_path / "cur.zip"
    prev = tmp_path / "prev.zip"
    cur.write_bytes(_13f("30-JUN-2026", [
        ("a1", "1", "Fund One", "AAAA BIO INC", "000000AA1", 1000, 100, ""),
        ("a2", "2", "Fund Two", "AAAA BIO INC", "000000AA1", 3000, 300, ""),
        ("a2", "2", "Fund Two", "AAAA BIO INC", "000000AA1", 999, 99, "Call"),   # option: out
        ("a3", "3", "Fund Three", "OTHER CORP", "000000ZZ9", 5, 5, "")]))
    prev.write_bytes(_13f("31-MAR-2026", [
        ("b1", "1", "Fund One", "AAAA BIO INC", "000000AA1", 900, 90, ""),
        ("b4", "4", "Fund Four", "AAAA BIO INC", "000000AA1", 50, 5, "")]))
    matcher = lambda n: "AAAA" if n.startswith("AAAA") else None  # noqa: E731
    c, period = whole13f.aggregate(str(cur), {}, matcher)
    p, _ = whole13f.aggregate(str(prev), {}, matcher)
    assert period == "30-JUN-2026" and set(c["ticker"]) == {"AAAA"}
    rows = whole13f.summarise(c, p, period)
    r = rows[0]
    assert r["holders"] == 2 and r["shares"] == 400 and r["new_holders"] == 1
    assert r["exited_holders"] == 1 and r["holders_prev"] == 2
    top = json.loads(r["top_holders"])
    assert top[0]["name"] == "Fund Two" and top[0]["change"] == "new"
    assert top[1]["change"] == 10.0


# ---------------------------------------------------------------- drugs
def test_orange_book_loe_and_faers():
    from bioterm.ingest import drugs

    products = ("Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~"
                "Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name\n"
                "AAAANIB~TABLET;ORAL~AAAAVIX~AAAA~10MG~N~212345~001~~Mar 1, 2021~Yes~Yes~RX~"
                "AAAA BIO INC\n"
                "OLDDRUG~TABLET;ORAL~OLDX~ZZ~5MG~N~012345~001~~Approved Prior to Jan 1, 1982~"
                "Yes~Yes~RX~OTHER PHARMA\n")
    patents = ("Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~"
               "Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~"
               "Submission_Date\nN~212345~001~9999999~Jun 1, 2034~Y~~~~\n"
               "N~212345~001~9999998~Jan 1, 2031~~Y~~~~\n")
    excl = ("Appl_Type~Appl_No~Product_No~Exclusivity_Code~Exclusivity_Date\n"
            "N~212345~001~NCE~Mar 1, 2026\n")
    zb = _zip({"products.txt": products, "patent.txt": patents, "exclusivity.txt": excl})
    p, pa, ex = drugs.parse_orange_book(zb)
    rows = drugs.loe_rows(p, pa, ex, lambda n: "AAAA" if n.startswith("AAAA") else None)
    assert len(rows) == 1
    r = rows[0]
    assert r["trade_name"] == "AAAAVIX" and r["loe_date"] == date(2034, 6, 1)
    assert r["approval_date"] == date(2021, 3, 1)
    q = drugs.faers_quarters({"results": [{"time": "20260105", "count": 3},
                                          {"time": "20260320", "count": 2},
                                          {"time": "20260401", "count": 7}]})
    assert q == {"2026Q1": 5, "2026Q2": 7}


def test_orange_book_blocked_falls_back_to_openfda_approvals(db, monkeypatch):
    from bioterm.db import bulk_upsert, fda_events, read_sql
    from bioterm.ingest import drugs

    bulk_upsert(fda_events, [
        {"id": "e1", "ticker": "AAAA", "kind": "approval", "application_number": "NDA212345",
         "brand_name": "AAAAVIX", "generic_name": "aaaanib", "sponsor_name": "AAAA BIO",
         "event_date": date(2021, 3, 1)},
        {"id": "e2", "ticker": "AAAA", "kind": "approval", "application_number": "NDA212345",
         "brand_name": "AAAAVIX", "generic_name": "aaaanib", "sponsor_name": "AAAA BIO",
         "event_date": date(2023, 5, 1)}])

    def blocked():
        raise ValueError("fda.gov returned a web page instead of the Orange Book ZIP")

    monkeypatch.setattr(drugs, "download_orange_book", blocked)
    out = drugs.run_orange_book()
    assert out["rows"] == 1 and out["source"].startswith("openfda-fallback")
    r = read_sql("SELECT * FROM loe_calendar").iloc[0]
    assert r["trade_name"] == "AAAAVIX" and str(r["approval_date"])[:10] == "2021-03-01"
    assert r["loe_date"] is None or pd.isna(r["loe_date"])


def test_orange_book_download_refuses_the_bot_filter_page(monkeypatch):
    from bioterm.ingest import drugs

    monkeypatch.setattr("bioterm.httpx_util.get_bytes",
                        lambda *a, **k: b"<!DOCTYPE html><title>Apology</title>")
    with pytest.raises(ValueError, match="bot filter"):
        drugs.download_orange_book()
    monkeypatch.setattr("bioterm.httpx_util.get_bytes", lambda *a, **k: b"PK\x03\x04zip")
    assert drugs.download_orange_book().startswith(b"PK")


# ---------------------------------------------------------------- gov + etf
def test_usaspending_rows_keep_only_the_company():
    from bioterm.ingest import gov

    res = [{"Recipient Name": "AAAA BIO INC", "Award Amount": 5e6, "Awarding Agency":
            "Department of Health and Human Services", "Awarding Sub Agency": "BARDA",
            "generated_internal_id": "CONT_AWD_1", "Start Date": "2025-01-01"},
           {"Recipient Name": "AAAA BIOLOGICAL SUPPLY LLC", "Award Amount": 1e6,
            "generated_internal_id": "CONT_AWD_2"}]
    rows = gov.to_rows(res, "AAAA", "contract", "AAAA BIO")
    assert [r["amount"] for r in rows] == [5e6]
    assert rows[0]["url"] == "https://www.usaspending.gov/award/CONT_AWD_1"


def test_navhist_flows_and_rebalance(db):
    from bioterm.db import bulk_upsert, etf_flows, prices, securities
    from bioterm.ingest import etf

    buf = io.BytesIO()
    pre = pd.DataFrame([["SPDR S&P Biotech ETF", None, None, None], [None] * 4])
    body = pd.DataFrame({"Date": ["24-Sep-2026", "25-Sep-2026"], "NAV": [100.0, 101.0],
                         "Shares Outstanding": [1_000_000, 1_050_000],
                         "Total Net Assets": [1.0e8, 1.0605e8]})
    with pd.ExcelWriter(buf) as w:
        pre.to_excel(w, index=False, header=False, startrow=0)
        body.to_excel(w, index=False, startrow=3)
    df = etf.parse_navhist(buf.getvalue())
    assert len(df) == 2 and df.iloc[-1]["flow_est"] == pytest.approx(50_000 * 101.0)
    assert etf.next_rebalance(date(2026, 9, 25)) == date(2026, 12, 18)
    assert etf.next_rebalance(date(2026, 3, 1)) == date(2026, 3, 20)
    bulk_upsert(securities, [{"ticker": "AAAA", "name": "A", "in_xbi": 1, "etf_weight": 75.0},
                             {"ticker": "BBBB", "name": "B", "in_xbi": 1, "etf_weight": 25.0}])
    bulk_upsert(etf_flows, [{"etf": "XBI", "date": date.today(), "aum": 1e9}])
    bulk_upsert(prices, [{"ticker": t, "date": date.today() - timedelta(days=i), "close": 10,
                          "volume": 1e6} for t in ("AAAA", "BBBB") for i in range(5)])
    rp = etf.rebalance_pressure().set_index("ticker")
    assert rp.loc["AAAA", "trade_usd"] < 0 < rp.loc["BBBB", "trade_usd"]       # sell / buy
    assert rp.loc["AAAA", "days_of_volume"] == pytest.approx((0.5 - 0.75) * 1e9 / 1e7)
