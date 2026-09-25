"""Dashboard: design-system helpers, and every page rendering end to end.

The page tests drive the real router (dashboard/Home.py) with Streamlit's
AppTest against the per-test SQLite database from conftest - once empty (every
empty state must render) and once seeded with a little of everything.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

DASH = Path(__file__).resolve().parents[1] / "dashboard"
APP = str(DASH / "Home.py")
PAGES = ["overview", "signals", "focus", "stock", "smart_money", "molecules", "backtest",
         "catalysts", "news", "watchlist", "compare", "alerts", "portfolio", "copilot",
         "settings", "health"]

if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))


@pytest.fixture(autouse=True)
def _clear_streamlit_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


# ------------------------------------------------------------------ helpers
def test_plain_and_escape():
    import _ui

    raw = '<a href="https://x.com/a" hreflang="en">Drug &amp; device hits endpoint</a>'
    assert _ui.plain(raw) == "Drug & device hits endpoint"
    assert _ui.esc(_ui.plain(raw)) == "Drug &amp; device hits endpoint"
    assert _ui.esc("<script>") == "&lt;script&gt;"
    # a comparison in a headline is prose, not a tag; a truncated tag still goes
    assert _ui.plain("Hits p<0.001, ALT <3x ULN, HR>0.8") == "Hits p<0.001, ALT <3x ULN, HR>0.8"
    assert _ui.plain('approval — <a href="https://www.fiercebio') == "approval —"


def test_safe_url_only_allows_http():
    import _ui

    assert _ui.safe_url("https://a.com/x?y=1&z=2") == "https://a.com/x?y=1&amp;z=2"
    assert _ui.safe_url("javascript:alert(1)") == ""
    assert _ui.safe_url("data:text/html,hi") == ""
    assert _ui.safe_url(None) == ""


def test_display_name_title_cases_only_all_caps():
    import _ui

    assert _ui.display_name("EXELIXIS INC") == "Exelixis Inc"
    assert _ui.display_name("TG THERAPEUTICS INC") == "TG Therapeutics Inc"
    assert _ui.display_name("Takeda") == "Takeda"
    assert _ui.display_name("argenx SE") == "argenx SE"


def test_money_and_markdown_safety():
    import _ui

    assert _ui.usd(-826) == "−$826"
    assert _ui.usd(1234.5, 2) == "$1,234.50"
    assert _ui.usd(54, sign=True) == "+$54"
    assert _ui.usd(None) == "–"
    assert _ui.md_safe("Cost $5 · cash $10") == "Cost \\$5 · cash \\$10"


def test_catalyst_title_and_alert_detail():
    import _ui

    assert _ui.catalyst_title("(news) FDA sets PDUFA date") == "FDA sets PDUFA date"
    assert _ui.catalyst_label("phase3_readout") == "Phase 3 readout"
    assert _ui.catalyst_family("pdufa") == "regulatory"
    assert _ui.phase_group("P2/P3") == "Phase 3" and _ui.phase_group("EP1") == "Phase 1"
    d = _ui.alert_detail("phase3_readout · 2026-09-17 (-0.2 mo) — (news) Topline due")
    assert d == "Phase 3 readout · 2026-09-17 (-0.2 mo) — Topline due"


def test_spark_drops_gaps_and_short_series():
    import _ui

    assert _ui.spark([1, None, float("nan"), 3]) == [1.0, 3.0]
    assert _ui.spark([1]) is None


def test_plotly_layout_never_sets_a_textless_title():
    import _ui

    assert "title" not in _ui.plotly_layout(height=200)
    assert _ui.plotly_layout(title="x")["title"]["text"] == "x"
    assert "template" not in _ui.plotly_layout()  # lets Streamlit's theme apply


# ------------------------------------------------------------------ pages
def _render(page: str, **query) -> AppTest:
    # conftest hands every test a fresh SQLite file, but _shared creates the
    # schema only when first imported in the process - do what a fresh
    # deployment's first import does.
    from bioterm.db import init_db

    init_db()
    at = AppTest.from_file(APP, default_timeout=60)
    for k, v in query.items():
        at.query_params[k] = v
    at.run()
    if page != "overview":
        at.switch_page(f"app_pages/{page}.py")
        at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_on_an_empty_database(page):
    at = _render(page)
    assert not at.exception, [e.value for e in at.exception]


def _seed() -> None:
    from bioterm.db import (bulk_upsert, clinical_trials, fundamentals, init_db, news, prices,
                            securities, technicals)
    from bioterm.process import catalysts, score

    init_db()
    now = datetime.now(timezone.utc)
    today = date.today()
    tickers = ["AAAA", "BBBB", "CCCC"]
    bulk_upsert(securities, [{"ticker": t, "name": f"{t} THERAPEUTICS INC",
                              "is_watchlist": int(t == "AAAA"), "in_xbi": 1}
                             for t in tickers])
    px_rows, tech_rows = [], []
    for i, t in enumerate(tickers):
        for d in pd.bdate_range(today - timedelta(days=60), today):
            base = 10 + i + (d.toordinal() % 7) * 0.1
            px_rows.append({"ticker": t, "date": d.date(), "open": base, "high": base + .5,
                            "low": base - .5, "close": base + .2, "volume": 1e5})
            tech_rows.append({"ticker": t, "date": d.date(), "close": base + .2,
                              "rsi14": 55, "macd": .1, "macd_signal": 0, "vol_z20": .5,
                              "pct_52w_range": .5, "ret_1m": .05, "ret_3m": .1,
                              "ret_6m": .2, "sma20": base, "sma50": base, "sma200": base})
    bulk_upsert(prices, px_rows)
    bulk_upsert(technicals, tech_rows)
    bulk_upsert(fundamentals, [{"ticker": t, "market_cap": 2e9, "cash": 3e8,
                                "runway_quarters": 3.0 + i, "net_income_ttm": -1e8,
                                "updated_at": now} for i, t in enumerate(tickers)])
    bulk_upsert(clinical_trials, [{
        "nct_id": "NCT00000001", "ticker": "AAAA", "sponsor": "Aaaa", "phase": "P3",
        "title": "A pivotal study", "status": "RECRUITING", "study_type": "INTERVENTIONAL",
        "start_date": today - timedelta(days=400),
        "primary_completion_date": today + timedelta(days=40),
        "url": "https://clinicaltrials.gov/study/NCT00000001", "fetched_at": now}])
    bulk_upsert(news, [{
        "id": f"n{i}", "ticker": t, "tickers_csv": t,
        "title": ('<a href="https://x.com/a">Aaaa hits primary endpoint in Phase 3</a>'
                  if i == 0 else f"{t} expects topline data in Q1 2099 - Some Paper"),
        "summary": "", "url": "https://x.com/a", "source": "Google News",
        "published": now - timedelta(hours=i), "sentiment": .4, "event_tags": "topline",
        "event_score": 1.0, "fetched_at": now} for i, t in enumerate(tickers)])
    catalysts.run()
    score.run()
    _seed_intelligence(tickers, today, now)


def _seed_intelligence(tickers, today, now) -> None:
    """13F, short volume, options, a tracked molecule, signals and backtests."""
    import json

    from bioterm import store
    from bioterm.db import (backtests, bulk_upsert, inst_filers, inst_holdings,
                            molecule_trials, options_snapshots, short_volume)
    from bioterm.process import molecules as mol_links
    from bioterm.process import signals

    bulk_upsert(inst_filers, [{"cik": "0001", "name": "BAKER BROS ADVISORS LP",
                               "short_name": "Baker Bros", "last_period": today,
                               "last_filed": today, "checked_at": now}])
    q0, q1 = today - timedelta(days=200), today - timedelta(days=100)
    bulk_upsert(inst_holdings, [
        {"id": f"0001|{p}|{c}", "cik": "0001", "period": p, "filed_date": p + timedelta(days=40),
         "accession": "x", "cusip": c, "issuer": f"{t} THERAPEUTICS INC", "title_class": "COM",
         "ticker": t, "shares": sh, "value": sh * 10.0, "fetched_at": now}
        for p, c, t, sh in ((q0, "000000001", "AAAA", 1e6), (q1, "000000001", "AAAA", 2e6),
                            (q0, "000000002", "BBBB", 5e5), (q1, "000000003", "CCCC", 3e5))])
    days = pd.bdate_range(today - timedelta(days=40), today)
    bulk_upsert(short_volume, [{"ticker": t, "date": d.date(), "short_volume": 4e4 + 500 * i,
                                "short_exempt": 0, "total_volume": 1e5}
                               for t in tickers for i, d in enumerate(days)])
    bulk_upsert(options_snapshots, [{
        "ticker": "AAAA", "date": today, "spot": 12.0, "expiry": today + timedelta(days=24),
        "days_to_expiry": 24, "atm_iv": 0.9, "iv_back": 0.7, "implied_move": 0.22,
        "call_volume": 4000, "put_volume": 800, "call_oi": 2000, "put_oi": 1500,
        "pc_volume_ratio": 0.2, "pc_oi_ratio": 0.75, "vol_oi_ratio": 1.37, "fetched_at": now}])
    mid = store.save_molecule({"ticker": "AAAA", "name": "aaaamab", "aliases": "AA-101",
                               "indication": "a rare disease", "nct_ids": "NCT00000001"})
    bulk_upsert(molecule_trials, [{
        "id": f"{mid}|NCT00000001", "molecule_id": mid, "ticker": "AAAA",
        "nct_id": "NCT00000001", "sponsor": "Aaaa", "title": "A pivotal study of aaaamab",
        "phase": "P3", "status": "RECRUITING", "start_date": today - timedelta(days=400),
        "primary_completion_date": today + timedelta(days=40),
        "url": "https://clinicaltrials.gov/study/NCT00000001", "source": "pinned",
        "fetched_at": now}])
    mol_links.run()
    signals.run()
    eq_dates = [str((today - timedelta(days=30 * i)).isoformat()) for i in (3, 2, 1, 0)]
    results = {
        "factor": {"factors": {"momentum": {"label": "Momentum", "ic_21": 0.04, "ic_t_21": 2.1,
                                            "quintiles_63": [-0.02, -0.01, 0, 0.01, 0.03],
                                            "spread_63": 0.05, "top_hit_rate": 0.6}},
                   "dates": 40, "universe": 3,
                   "equity": {"date": eq_dates, "top": [1, 1.05, 1.1, 1.2],
                              "universe": [1, 1.01, 1.02, 1.04], "xbi": [1, 1.0, 1.01, 1.03]}},
        "events": {"n_events": 12, "by_code": {"golden_cross": {
            "side": "BUY", "n": 12, "tickers": 3, "mean_63": 0.03, "hit_63": 0.6,
            "t_63": 1.4}}},
        "track": {"n": 2, "by_label": {"BUY": {"n": 2, "x_21": 0.02, "hit_21": 0.5}},
                  "recent": [{"ticker": "AAAA", "asof": str(today), "label": "BUY",
                              "ret_21": 0.04, "ret_open": 0.05}]},
    }
    bulk_upsert(backtests, [{"id": f"{k}|{today}", "kind": k, "ts": now,
                             "params": json.dumps({"horizons": [21, 63, 126]}),
                             "results": json.dumps(v)} for k, v in results.items()])


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_data(page):
    _seed()
    at = _render(page, ticker="AAAA") if page == "stock" else _render(page)
    assert not at.exception, [e.value for e in at.exception]


def test_stock_page_deep_link_selects_the_ticker():
    _seed()
    at = _render("stock", ticker="BBBB")
    assert at.selectbox[0].value == "BBBB"


def test_focus_page_scope_filter_narrows_the_list():
    _seed()
    at = _render("focus")
    n_all = len(at.dataframe[0].value)
    at.pills[0].set_value(["Watchlist"]).run()
    assert len(at.dataframe[0].value) < n_all
    assert not at.exception


def test_portfolio_price_follows_the_ticker():
    _seed()
    at = _render("portfolio")
    at.selectbox(key="pf_tk").select("AAAA").run()
    a = at.number_input(key="pf_px::AAAA").value
    at.selectbox(key="pf_tk").select("CCCC").run()
    c = at.number_input(key="pf_px::CCCC").value
    assert a > 0 and c > 0 and a != c


def test_signals_board_and_drill_down():
    _seed()
    at = _render("signals")
    assert not at.exception
    assert at.selectbox(key="sg_pick").value in {"AAAA", "BBBB", "CCCC"}
    at.selectbox(key="sg_pick").select("CCCC").run()
    assert not at.exception
    at.segmented_control(key="sg_side").set_value("Sell side").run()
    assert not at.exception


def test_molecule_editor_tracks_a_new_molecule():
    _seed()
    at = _render("molecules")
    assert not at.exception
    from bioterm import store

    n0 = len(store.get_molecules())
    at.selectbox(key="mol_add_tk").select("BBBB")
    at.text_input(key="mol_add_name").input("bbbbnib")
    at.text_input(key="mol_add_aliases").input("BB-202, Bbrand")
    at.text_input(key="mol_add_ncts").input("NCT01234567, not-an-id")
    next(b for b in at.button if b.label == "Track molecule").click().run()
    assert not at.exception
    mols = {m["name"]: m for m in store.get_molecules()}
    assert len(mols) == n0 + 1
    assert mols["bbbbnib"]["aliases"] == ["BB-202", "Bbrand"]
    assert mols["bbbbnib"]["nct_ids"] == ["NCT01234567"]


def test_settings_adds_and_deletes_an_llm_key():
    from bioterm import vault

    at = _render("settings")
    assert not at.exception
    at.text_input(key="in_ANTHROPIC_API_KEY").input("sk-ant-api03-test-key-9876")
    next(b for b in at.button if b.label == "Save without testing").click().run()
    assert not at.exception
    assert vault.get("ANTHROPIC_API_KEY") == "sk-ant-api03-test-key-9876"
    listing = {r["name"]: r for r in vault.listing()}
    assert listing["ANTHROPIC_API_KEY"]["hint"] == "…9876"
    at = _render("settings")
    next(b for b in at.button if b.label == "Delete permanently").click().run()
    assert not at.exception
    vault.reset_key_cache()
    assert vault.get("ANTHROPIC_API_KEY") is None


def test_owner_passcode_makes_the_terminal_read_only():
    from bioterm import auth, store

    _seed()
    auth.claim("owner passcode 1")
    store.set_note("AAAA", "secret thesis")
    at = _render("watchlist")
    assert not at.exception
    assert next(b for b in at.button if b.label == "Save watchlist").disabled
    at = _render("stock", ticker="AAAA")
    assert not at.exception
    assert not any("secret thesis" in (t.value or "") for t in at.text_area)
    at = _render("settings")
    at.text_input(key="unlock_header_code").input("owner passcode 1")   # header chip
    next(b for b in at.button if b.label == "Unlock").click().run()
    assert not at.exception and at.session_state["bt_owner"]


def test_copilot_page_explains_how_to_switch_it_on():
    at = _render("copilot")
    assert not at.exception
    assert any("Copilot is off" in (h.value or "") for h in at.get("html")) or \
        any("Settings" in str(p.label) for p in at.get("page_link"))
