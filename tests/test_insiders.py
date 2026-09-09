from datetime import date, datetime, timezone

from bioterm.db import bulk_upsert, init_db, insider_txns, read_sql
from bioterm.ingest.insiders import net_open_market, parse_form4

FORM4_XML = b"""<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerName>Testco, Inc.</issuerName><issuerTradingSymbol>TSTC</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-08-15</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4():
    rows = parse_form4(FORM4_XML, "TSTC", date(2026, 8, 16), "http://x/form4.xml")
    assert len(rows) == 1
    r = rows[0]
    assert r["owner"] == "Doe Jane"
    assert r["role"] == "Director"
    assert r["code"] == "P"
    assert r["shares"] == 10000
    assert r["value"] == 125000.0  # positive = acquired


def test_net_open_market_rollup():
    init_db()
    now = datetime.now(timezone.utc)
    bulk_upsert(insider_txns, [
        {"id": "a", "ticker": "TSTC", "txn_date": date.today(), "filed_date": date.today(),
         "owner": "A", "role": "Director", "code": "P", "acquired_disposed": "A",
         "shares": 1000, "price": 10.0, "value": 10000.0, "url": "", "fetched_at": now},
        {"id": "b", "ticker": "TSTC", "txn_date": date.today(), "filed_date": date.today(),
         "owner": "B", "role": "Officer", "code": "P", "acquired_disposed": "A",
         "shares": 2000, "price": 10.0, "value": 20000.0, "url": "", "fetched_at": now},
        {"id": "c", "ticker": "TSTC", "txn_date": date.today(), "filed_date": date.today(),
         "owner": "C", "role": "Director", "code": "S", "acquired_disposed": "D",
         "shares": 500, "price": 10.0, "value": -5000.0, "url": "", "fetched_at": now},
    ])
    nom = net_open_market(days=90).set_index("ticker")
    assert nom.loc["TSTC", "n_buyers"] == 2
    assert nom.loc["TSTC", "buy_value"] == 30000.0
    assert nom.loc["TSTC", "net_value"] == 25000.0


def test_insider_buying_lifts_score():
    from datetime import date as _d

    from bioterm import store
    from bioterm.db import bulk_upsert, fundamentals, securities, technicals
    from bioterm.process import score

    init_db()
    now = datetime.now(timezone.utc)
    for tk in ("BUYR", "NONE"):
        bulk_upsert(securities, [{"ticker": tk, "name": tk, "is_watchlist": 0}])
        bulk_upsert(technicals, [{"ticker": tk, "date": _d.today(), "close": 10.0,
                                  "rsi14": 55, "macd": 0.1, "macd_signal": 0.0,
                                  "vol_z20": 0.5, "pct_52w_range": 0.5,
                                  "ret_1m": 0.05, "ret_3m": 0.1, "ret_6m": 0.2}])
        bulk_upsert(fundamentals, [{"ticker": tk, "runway_quarters": 12.0,
                                    "net_income_ttm": -1e8, "updated_at": now}])
    bulk_upsert(insider_txns, [
        {"id": f"x{i}", "ticker": "BUYR", "txn_date": _d.today(), "filed_date": _d.today(),
         "owner": f"O{i}", "role": "Director", "code": "P", "acquired_disposed": "A",
         "shares": 100000, "price": 10.0, "value": 1_000_000.0, "url": "", "fetched_at": now}
        for i in range(3)
    ])
    score.run()
    s = read_sql("SELECT ticker, focus_score FROM scores WHERE ticker IN ('BUYR','NONE')").set_index("ticker")
    assert s.loc["BUYR", "focus_score"] > s.loc["NONE", "focus_score"]
