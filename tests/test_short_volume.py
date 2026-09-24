from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from bioterm.db import init_db, read_sql
from bioterm.ingest import short_volume as sv

FIX = Path(__file__).parent / "fixtures" / "finra_CNMSshvol20260923.txt"


def test_parse_real_finra_file():
    rows = sv.parse(FIX.read_text() + "12371\n", {"MRNA", "XBI"})
    by = {r["ticker"]: r for r in rows}
    assert set(by) == {"MRNA", "XBI"}
    assert by["MRNA"]["date"] == date(2026, 9, 23)
    assert round(by["MRNA"]["short_volume"]) == 5558118
    assert round(by["MRNA"]["total_volume"]) == 9061316


def test_run_skips_missing_days_and_known_days(monkeypatch):
    init_db()
    fetched = []

    def fake_bytes(url, **kw):
        fetched.append(url)
        if url.endswith("0921.txt") or url.endswith("0923.txt") or url.endswith("0922.txt"):
            ymd = url[-12:-4]
            return (f"Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
                    f"{ymd}|MRNA|60|0|100|Q\n{ymd}|ZZZZ|1|0|2|Q\n2\n").encode()
        raise requests.HTTPError("404")

    monkeypatch.setattr(sv, "get_bytes", fake_bytes)
    monkeypatch.setattr(sv, "date", type("D", (), {"today": staticmethod(lambda: date(2026, 9, 24))}))
    out = sv.run(tickers=["MRNA"], backfill_days=5)
    assert out["days"] == 3
    df = read_sql("SELECT * FROM short_volume")
    assert set(df["ticker"]) == {"MRNA"} and len(df) == 3
    n = len(fetched)
    sv.run(tickers=["MRNA"], backfill_days=5)
    assert len(fetched) - n == 2            # only the days that 404'd are retried


def test_short_ratio_trend():
    days = pd.bdate_range("2026-08-01", periods=25)
    df = pd.DataFrame({"ticker": "AAA", "date": days,
                       "short_volume": [40] * 20 + [80] * 5, "total_volume": [100] * 25})
    t = sv.short_ratio_trend(df).set_index("ticker")
    assert t.loc["AAA", "ratio_5d"] == 0.8
    assert round(t.loc["AAA", "delta"], 2) == 0.3
