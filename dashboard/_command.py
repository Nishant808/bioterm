"""Command bar: Bloomberg-style mnemonics + global search, on every page.

    VRTX            stock page            VRTX CAT / PIPE / NEWS / FIL / SIG / BS / FLOW
    MKT  market     SIG  signals          FOC  focus list      SCR  screener
    CAL  catalysts  N    news             SM   smart money     MOL  molecules
    CMP A B C       compare               WL   watchlist       ALRT alerts
    PF   paper trading   WS  workspace    AI / ASK  copilot    BT   backtest
    HLTH data health     SET settings     HELP this list

Anything else searches tickers, company names and molecules. Press "/" (or
Ctrl/Cmd+K) anywhere to jump into the bar.
"""
from __future__ import annotations

import re

import streamlit as st

PAGES = {
    "MKT": ("app_pages/market.py", "Market"), "SIG": ("app_pages/signals.py", "Signals"),
    "FOC": ("app_pages/focus.py", "Focus list"), "TOP": ("app_pages/focus.py", "Focus list"),
    "SCR": ("app_pages/screener.py", "Screener"), "EQS": ("app_pages/screener.py", "Screener"),
    "CAL": ("app_pages/catalysts.py", "Catalysts"), "N": ("app_pages/news.py", "News"),
    "NEWS": ("app_pages/news.py", "News"), "SM": ("app_pages/smart_money.py", "Smart money"),
    "HDS": ("app_pages/smart_money.py", "Smart money"),
    "MOL": ("app_pages/molecules.py", "Molecules"), "BT": ("app_pages/backtest.py", "Backtest"),
    "WL": ("app_pages/watchlist.py", "Watchlist"), "ALRT": ("app_pages/alerts.py", "Alerts"),
    "PF": ("app_pages/portfolio.py", "Paper trading"),
    "PRT": ("app_pages/portfolio.py", "Paper trading"),
    "WS": ("app_pages/workspace.py", "Workspace"), "AI": ("app_pages/copilot.py", "Copilot"),
    "ASK": ("app_pages/copilot.py", "Copilot"), "HLTH": ("app_pages/health.py", "Data health"),
    "SET": ("app_pages/settings.py", "Settings"), "HOME": ("app_pages/overview.py", "Overview"),
    "CMP": ("app_pages/compare.py", "Compare"),
}
STOCK_TABS = {  # mnemonic -> stock page tab label
    "DES": None, "GP": "Price & technicals", "CHART": "Price & technicals",
    "SIG": "Signals", "PIPE": "Pipeline", "CAT": "Catalysts", "CN": "News & sentiment",
    "NEWS": "News & sentiment", "INS": "Insiders", "FLOW": "Funds & flow",
    "HDS": "Funds & flow", "BS": "Balance sheet", "FA": "Balance sheet", "FIL": "SEC filings",
}
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$")


def parse(cmd: str, known: set[str]) -> tuple[str, dict] | tuple[None, list[str]]:
    """Command text -> (page path, query params), or (None, search tokens)."""
    toks = cmd.strip().upper().split()
    if not toks:
        return None, []
    head = toks[0].lstrip("<").rstrip(">")
    if head == "CMP" and len(toks) > 1:
        return PAGES["CMP"][0], {"tickers": ",".join(t for t in toks[1:] if t in known)}
    if head in ("TEAR", "TS") and len(toks) > 1 and toks[1] in known:
        return "app_pages/stock.py", {"ticker": toks[1], "tear": "1"}
    if head in known:
        tab = STOCK_TABS.get(toks[1]) if len(toks) > 1 else None
        q = {"ticker": head}
        if tab:
            q["tab"] = tab
        return "app_pages/stock.py", q
    if head in PAGES and len(toks) == 1:
        return PAGES[head][0], {}
    if len(toks) == 2 and toks[1] in PAGES and toks[0] in known:
        return PAGES[toks[1]][0], {}
    return None, toks


def search(text: str, limit: int = 8) -> list[tuple[str, str]]:
    """(ticker, label) matches over tickers, company names and molecules."""
    from _shared import molecules_df, universe_df

    t = text.strip().lower()
    if len(t) < 2:
        return []
    uni = universe_df()
    out: list[tuple[str, str]] = []
    if not uni.empty:
        hit = uni[uni["ticker"].str.lower().str.startswith(t)
                  | uni["name"].fillna("").str.lower().str.contains(re.escape(t))]
        out += [(r.ticker, f"{r.ticker} · {r.name}") for r in hit.head(limit).itertuples()]
    mol = molecules_df()
    if not mol.empty and len(out) < limit:
        m = mol[mol["name"].fillna("").str.lower().str.contains(re.escape(t))
                | mol["aliases"].astype(str).str.lower().str.contains(re.escape(t))]
        out += [(r.ticker, f"{r.ticker} · {r.name} (molecule)") for r in m.head(3).itertuples()]
    return out[:limit]


def _submit() -> None:
    st.session_state["bt_cmd_go"] = st.session_state.get("bt_cmd", "")
    st.session_state["bt_cmd"] = ""


_FOCUS_JS = """
<script>
(function () {
  const doc = window.parent && window.parent.document ? window.parent.document : document;
  if (doc.__btCmdKeys) return;
  doc.__btCmdKeys = true;
  doc.addEventListener('keydown', function (e) {
    const t = e.target, tag = (t && t.tagName) || '';
    const typing = tag === 'INPUT' || tag === 'TEXTAREA' || (t && t.isContentEditable);
    const k = (e.key || '').toLowerCase();
    if ((k === '/' && !typing) || (k === 'k' && (e.ctrlKey || e.metaKey))) {
      const el = doc.querySelector('input[aria-label="Command"]');
      if (el) { e.preventDefault(); el.focus(); el.select(); }
    }
  }, true);
})();
</script>
"""


def render() -> None:
    """Draw the bar; act on a submitted command (navigate or show matches)."""
    from _shared import universe_df

    go = st.session_state.pop("bt_cmd_go", None)
    with st.container(horizontal=True, vertical_alignment="center", gap="small",
                      key="bt-cmdbar"):
        st.text_input("Command", key="bt_cmd", on_change=_submit,
                      placeholder="Ticker or command - VRTX · VRTX CAT · SCR · MKT · CMP A B · "
                                  "AI · HELP   ( / to focus )",
                      label_visibility="collapsed", icon=":material/terminal:")
    st.html(_FOCUS_JS, unsafe_allow_javascript=True)
    if not go:
        return
    if go.strip().upper() in ("HELP", "?", "H"):
        st.info(__doc__.split("\n\n", 1)[1].split("Anything else")[0], icon=":material/help:")
        return
    uni = universe_df()
    known = set(uni["ticker"]) if not uni.empty else set()
    page, q = parse(go, known)
    if page:
        st.switch_page(page, query_params=q or None)
    hits = search(go)
    if len(hits) == 1:
        st.switch_page("app_pages/stock.py", query_params={"ticker": hits[0][0]})
    if hits:
        with st.container(horizontal=True, gap="small", key="bt-cmd-hits"):
            st.caption(f"Matches for “{go.strip()}”:")
            for tk, lab in hits:
                st.page_link("app_pages/stock.py", label=lab, query_params={"ticker": tk},
                             icon=":material/arrow_outward:")
    else:
        st.caption(f"No command or name matches “{go.strip()}” - type HELP for the list.")
