from datetime import date

from bioterm import store
from bioterm.db import init_db, read_sql


def test_watchlist_roundtrip():
    init_db()
    store.save_watchlist([
        {"ticker": "aaaa", "conviction": 5, "thesis": "hot", "molecules": ["X-1", "X-2"]},
        {"ticker": "BBBB", "conviction": 2, "thesis": "", "molecules": []},
    ])
    wl = {w["ticker"]: w for w in store.get_watchlist()}
    assert wl["AAAA"]["conviction"] == 5
    assert wl["AAAA"]["molecules"] == ["X-1", "X-2"]
    assert store.watchlist_conviction("aaaa") == 5

    store.remove_from_watchlist("BBBB")
    assert "BBBB" not in {w["ticker"] for w in store.get_watchlist()}

    store.add_to_watchlist("CCCC", 3)
    assert store.watchlist_conviction("CCCC") == 3


def test_manual_catalyst_crud():
    init_db()
    cid = store.add_manual_catalyst("DDDD", "pdufa", "2027-01-15", "PDUFA date", "high")
    got = store.get_manual_catalysts()
    assert any(c["id"] == cid and c["type"] == "pdufa" for c in got)
    store.delete_manual_catalyst(cid)
    assert not any(c["id"] == cid for c in store.get_manual_catalysts())


def test_notes_roundtrip():
    init_db()
    assert store.get_note("EEEE") == ""
    store.set_note("eeee", "watch the Phase 2 readout")
    assert store.get_note("EEEE") == "watch the Phase 2 readout"


def test_meta_roundtrip():
    init_db()
    assert store.get_meta("weights", {"a": 1}) == {"a": 1}
    store.set_meta("weights", {"momentum": 0.5})
    assert store.get_meta("weights")["momentum"] == 0.5


def test_manual_catalyst_feeds_catalyst_engine():
    from bioterm.db import bulk_upsert, securities
    from bioterm.process import catalysts

    init_db()
    bulk_upsert(securities, [{"ticker": "FFFF", "name": "Ffff Bio", "is_watchlist": 0}])
    nextmonth = date.today().replace(day=15)
    y, m = (nextmonth.year, nextmonth.month + 1) if nextmonth.month < 12 else (nextmonth.year + 1, 1)
    store.add_manual_catalyst("FFFF", "pdufa", date(y, m, 15), "FFFF PDUFA", "high")
    catalysts.run()
    c = read_sql("SELECT * FROM catalysts WHERE ticker='FFFF'")
    assert not c.empty
    assert (c["source"] == "manual").any()
