from datetime import date

import pytest

from bioterm.process.catalysts import classify_type, extract_date


@pytest.mark.parametrize(
    "text,expected_year,expected_month",
    [
        ("PDUFA date of March 15, 2027 for the therapy", 2027, 3),
        ("topline data expected in Q4 2026", 2026, 11),
        ("results anticipated in the second half of 2026", 2026, 9),
        ("readout in H1 2027", 2027, 3),
        ("data expected mid-2026", 2026, 6),
        ("approval decision by January 2027", 2027, 1),
    ],
)
def test_extract_date(text, expected_year, expected_month):
    got = extract_date(text)
    assert got is not None
    d, _gran = got
    assert d.year == expected_year
    assert d.month == expected_month


def test_extract_date_none_when_absent():
    assert extract_date("the company reported strong pipeline progress") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Company announces PDUFA target action date", "pdufa"),
        ("FDA advisory committee to review the BLA", "adcom"),
        ("Phase 3 pivotal trial topline results", "phase3_readout"),
        ("Phase 2 proof-of-concept data", "phase2_readout"),
        ("presenting data at ASCO", "data_presentation"),
    ],
)
def test_classify_type(text, expected):
    assert classify_type(text) == expected


def test_catalyst_run_end_to_end(monkeypatch):
    from datetime import datetime, timezone

    from bioterm.db import bulk_upsert, clinical_trials, init_db, news, read_sql
    from bioterm.process import catalysts

    init_db()
    today = date.today()
    near = today.replace(day=15)
    bulk_upsert(clinical_trials, [
        {
            "nct_id": "NCT99999999", "ticker": "AAAA", "sponsor": "Aaaa Inc",
            "title": "A pivotal study of drug X", "phase": "P3",
            "status": "ACTIVE_NOT_RECRUITING", "study_type": "INTERVENTIONAL",
            "primary_completion_date": date(today.year + (today.month + 2) // 12,
                                            (today.month + 1) % 12 + 1, 15),
            "url": "http://x", "fetched_at": datetime.now(timezone.utc),
        }
    ])
    bulk_upsert(news, [
        {
            "id": "n1", "ticker": "AAAA", "tickers_csv": "AAAA",
            "title": "Aaaa expects Phase 3 topline data in Q1 2099",
            "summary": "", "url": "http://n1", "source": "t",
            "published": datetime.now(timezone.utc), "sentiment": 0.0,
            "event_tags": "", "event_score": 0.0,
            "fetched_at": datetime.now(timezone.utc),
        }
    ])
    out = catalysts.run()
    assert out["rows"] >= 1
    c = read_sql("SELECT * FROM catalysts WHERE ticker='AAAA'")
    assert not c.empty
    assert set(c["type"]).issubset({
        "phase3_readout", "phase2_readout", "phase1_readout", "trial_completion",
        "pdufa", "adcom", "fda_action", "data_presentation", "earnings", "other",
    })
