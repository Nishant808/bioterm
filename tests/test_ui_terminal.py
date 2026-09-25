"""Terminal UI: command-bar mnemonics and navigation, the pro chart payload, tear
sheets, the workspace monitor and the stock page's tab deep link."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st

DASH = Path(__file__).resolve().parents[1] / "dashboard"
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))


@pytest.fixture(autouse=True)
def _clear_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def test_command_parsing():
    import _command as cmd

    known = {"VRTX", "MRNA", "AAAA"}
    assert cmd.parse("vrtx", known) == ("app_pages/stock.py", {"ticker": "VRTX"})
    assert cmd.parse("VRTX CAT", known) == ("app_pages/stock.py",
                                            {"ticker": "VRTX", "tab": "Catalysts"})
    assert cmd.parse("<VRTX> BS", known)[1]["tab"] == "Balance sheet"
    assert cmd.parse("SCR", known) == ("app_pages/screener.py", {})
    assert cmd.parse("cmp vrtx mrna nope", known) == ("app_pages/compare.py",
                                                      {"tickers": "VRTX,MRNA"})
    assert cmd.parse("TEAR VRTX", known)[1] == {"ticker": "VRTX", "tear": "1"}
    assert cmd.parse("obesity drugs", known) == (None, ["OBESITY", "DRUGS"])


def test_pro_chart_payload_snaps_markers_to_sessions():
    import _charts

    d = pd.DataFrame({"date": pd.to_datetime(["2026-09-24", "2026-09-25", "2026-09-28"]),
                      "open": [1, 2, 3], "high": [2, 3, 4], "low": [0.5, 1, 2],
                      "close": [1.5, 2.5, float("nan")], "volume": [10, 20, 30],
                      "sma20": [None, 2.0, 2.1], "rsi14": [50, 55, 60]})
    p = _charts.payload(d, markers=[{"time": "2026-09-26", "position": "aboveBar",
                                     "color": "#fff", "shape": "circle", "text": "x"}])
    assert [c["time"] for c in p["candles"]] == ["2026-09-24", "2026-09-25"]   # NaN close out
    assert p["markers"] == []            # Saturday snaps to the next bar - none left
    p2 = _charts.payload(d.iloc[:2], markers=[{"time": "2026-09-24", "text": "BUY"}])
    assert p2["markers"][0]["time"] == "2026-09-24"
    assert p["lines"]["sma20"] == [{"time": "2026-09-25", "value": 2.0}]
    intr = _charts.payload(d.iloc[:1].assign(date=pd.to_datetime(["2026-09-25 10:05"])),
                           intraday=True)
    assert isinstance(intr["candles"][0]["time"], int)


def _seed():
    from tests.test_dashboard import _seed as seed

    seed()


def test_tear_sheets_build(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _seed()
    from bioterm import tearsheet

    html = tearsheet.html_page("AAAA")
    assert "AAAA" in html and "Upcoming catalysts" in html and "<script" not in html
    x = tearsheet.xlsx("AAAA")
    assert x[:2] == b"PK" and len(x) > 3000
    import io

    sheets = pd.ExcelFile(io.BytesIO(x)).sheet_names
    assert sheets[0] == "Summary" and "Prices" in sheets


def test_command_bar_navigates_and_stock_tab_deep_link():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _seed()
    from streamlit.testing.v1 import AppTest

    from bioterm.db import init_db

    init_db()
    at = AppTest.from_file(str(DASH / "Home.py"), default_timeout=60)
    at.run()
    at.text_input(key="bt_cmd").input("AAAA CAT").run()
    assert not at.exception
    assert at.query_params.get("ticker") in ("AAAA", ["AAAA"])
    at2 = AppTest.from_file(str(DASH / "Home.py"), default_timeout=60)
    at2.query_params["ticker"] = "AAAA"
    at2.query_params["tab"] = "Balance sheet"
    at2.run()
    at2.switch_page("app_pages/stock.py")
    at2.run()
    assert not at2.exception
