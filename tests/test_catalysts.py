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


# Fixed reference "today" so year-less / relative phrasing resolves reproducibly
# regardless of when the suite actually runs.
TODAY = date(2026, 9, 18)


@pytest.mark.parametrize(
    "text,expected",
    [
        # a day+month with no year at all - resolve to the nearest future occurrence
        ("PDUFA date of March 15", date(2027, 3, 15)),
        # reversed, UK-style day-month-year
        ("data expected on 15 March 2027", date(2027, 3, 15)),
        # a quarter/half tied to "this/next year" instead of digits
        ("topline data in Q1 of next year", date(2027, 2, 15)),
        ("results expected in the back half of next year", date(2027, 9, 30)),
        ("an update is expected early next year", date(2027, 2, 15)),
        # "year-end" phrasing with no explicit calendar date
        ("management expects a decision by year-end", date(2026, 12, 15)),
        ("guidance calls for a filing by the end of next year", date(2027, 12, 15)),
        ("topline results are expected later this year", date(2026, 11, 15)),
        # an impossible day clamps to the last real day of the month instead of
        # being silently discarded
        ("data expected February 30, 2027", date(2027, 2, 28)),
    ],
)
def test_extract_date_relative_and_yearless(text, expected):
    got = extract_date(text, today=TODAY)
    assert got is not None
    d, _gran = got
    assert d == expected


def test_extract_date_month_day_no_year_prefers_near_future():
    # March 15 has already passed (more than the grace window) relative to
    # TODAY = Sept 18, 2026, so it should resolve to next year...
    assert extract_date("PDUFA date of March 15", today=TODAY)[0] == date(2027, 3, 15)
    # ...but relative to an earlier "today", the same phrase is still ahead of
    # us this year.
    early = date(2026, 2, 1)
    assert extract_date("PDUFA date of March 15", today=early)[0] == date(2026, 3, 15)


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


@pytest.mark.parametrize(
    "text,expected",
    [
        # PDUFA is the rarer, more decisive signal - it should win even though
        # "Phase 3" is also mentioned, regardless of which is listed first in
        # _TYPE_KEYWORDS (the old first-match-wins design got this backwards
        # whenever the less-specific keyword happened to be checked first).
        ("Following Phase 3 success, the company's PDUFA date is set for March 15",
         "pdufa"),
        ("FDA issues a complete response letter for the BLA", "fda_action"),
        # a bare mention of a trial phase should still beat the generic
        # "data"/"results" filler words that appear in almost every headline
        ("Phase 1 dose-escalation data presented at a conference", "phase1_readout"),
    ],
)
def test_classify_type_prefers_more_specific_signal(text, expected):
    assert classify_type(text) == expected


def test_catalyst_run_end_to_end(monkeypatch):
    from datetime import datetime, timezone

    from bioterm.db import bulk_upsert, clinical_trials, init_db, news, read_sql
    from bioterm.process import catalysts

    init_db()
    today = date.today()
    today.replace(day=15)
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
