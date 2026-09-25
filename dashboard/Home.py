"""BioTerm - app router (the Streamlit entrypoint).

Streamlit runs this file on every rerun. It sets the page config, logo and
stylesheet, builds the navigation, runs the selected page inside a
database-error guard, and renders the shared footer. Pages live in
``app_pages/`` and are plain scripts.

Each page keeps the URL it had before navigation moved here
(``/Stocks_in_Focus``, ``/Stock_Detail?ticker=...``, ``/Portfolio?pf=...`` ...),
so bookmarks and shared links keep working.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path

import streamlit as st

_ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="BioTerm", page_icon=str(_ASSETS / "mark.svg"),
                   layout="wide")

log = logging.getLogger("bioterm.dashboard")


def _fresh(name: str):
    """Import a dashboard helper module, reloading it if its file changed since
    it was loaded. A Streamlit Cloud fast reboot pulls new source but keeps
    already-imported modules in sys.modules, so a page importing a helper that
    was added in the same push would crash with an ImportError. This router
    runs on every rerun, so one stat() per module keeps the helpers current.

    A module that was already loaded but carries no timestamp was imported by
    code that predates this check - reload it once too."""
    was_loaded = name in sys.modules
    mod = importlib.import_module(name)
    try:
        mtime = os.path.getmtime(mod.__file__)
    except (OSError, TypeError):
        return mod
    if was_loaded and getattr(mod, "__bt_mtime__", None) != mtime:
        log.info("reloading %s (source changed since it was imported)", name)
        mod = importlib.reload(mod)
    mod.__bt_mtime__ = mtime
    return mod


_fresh("_shared")  # secrets bridge + src/ on sys.path - must precede bioterm imports
_fresh("_auth")
_ui = _fresh("_ui")
_fresh("_live")


def _page(path: str, title: str, icon: str, url_path: str | None = None,
          default: bool = False):
    return st.Page(f"app_pages/{path}", title=title, icon=f":material/{icon}:",
                   url_path=url_path, default=default)


# Pages under "" sit directly in the top bar; each named section is a dropdown.
nav = st.navigation(
    {
        "": [
            _page("overview.py", "Overview", "space_dashboard", default=True),
            _page("signals.py", "Signals", "swap_vert", "Signals"),
            _page("stock.py", "Stock detail", "query_stats", "Stock_Detail"),
            _page("copilot.py", "Copilot", "smart_toy", "Copilot"),
        ],
        "Intelligence": [
            _page("focus.py", "Focus list", "leaderboard", "Stocks_in_Focus"),
            _page("smart_money.py", "Smart money & flow", "account_balance", "Smart_Money"),
            _page("molecules.py", "Molecules", "science", "Molecules"),
            _page("backtest.py", "Backtest", "history", "Backtest"),
        ],
        "Markets": [
            _page("catalysts.py", "Catalysts", "event_upcoming", "Catalyst_Calendar"),
            _page("news.py", "News", "newspaper", "News_Firehose"),
            _page("compare.py", "Compare", "compare_arrows", "Compare"),
        ],
        "Workspace": [
            _page("watchlist.py", "Watchlist", "bookmark_star", "Watchlist"),
            _page("alerts.py", "Alerts", "notifications_active", "Alerts"),
            _page("portfolio.py", "Paper trading", "account_balance_wallet", "Portfolio"),
            _page("health.py", "Data health", "monitor_heart", "Health"),
            _page("settings.py", "Settings", "settings", "Settings"),
        ],
    },
    position="top",
)

st.set_page_config(page_title=f"{nav.title} · BioTerm")
# the full wordmark in both states: with top navigation there is no sidebar, so
# Streamlit always shows icon_image
st.logo(str(_ASSETS / "logo.svg"), size="large", icon_image=str(_ASSETS / "logo.svg"))
_ui.inject_css()

try:
    nav.run()
except Exception as exc:  # noqa: BLE001 - only database errors are handled here
    from sqlalchemy.exc import SQLAlchemyError

    if not isinstance(exc, SQLAlchemyError):
        raise
    # Neon auto-suspends when idle; a cold start or a dropped connection
    # shouldn't dump a stack trace on the reader. st.cache_data never caches
    # an exception, so a plain rerun genuinely retries the query.
    log.warning("database error while rendering %s: %s", nav.title, exc)
    _ui.empty_state("Can't reach the database right now",
                    "The database may be waking up from idle. This usually clears "
                    "within a few seconds.", "cloud_off")
    with st.container(horizontal=True, horizontal_alignment="center"):
        if st.button("Try again", icon=":material/refresh:", type="primary"):
            st.rerun()

_ui.footer()
