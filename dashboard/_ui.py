"""BioTerm design system: tokens, page chrome, components and chart helpers.

Colours, fonts, radius and borders live in ``.streamlit/config.toml`` (native
theming reaches every element and survives Streamlit upgrades). This module
mirrors those tokens for Plotly and custom HTML, and adds only what config
can't express: page header/footer, list rows, badges, empty states, motion.

Every page is a plain script run by the router (``dashboard/Home.py``), which
injects the stylesheet and renders the footer - a page only calls
``page_header()`` and then composes cards, metrics, tables and charts.
"""
from __future__ import annotations

import html as _html
import os
import re
from typing import Iterable

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------- tokens
# Mirror of .streamlit/config.toml - keep the two in sync.
BG            = "#0B0E14"   # page plane
SURFACE       = "#121821"   # widgets, table headers, raised rows
SURFACE_2     = "#19212D"   # hover / tooltip
BORDER        = "#232C3A"   # hairlines
BORDER_STRONG = "#334055"   # hover borders, axis zero line
GRID          = "#1A2230"   # chart gridlines - one step off the plane
TEXT          = "#E6EAF2"   # 16.0:1 on BG
TEXT_2        = "#B4BCCB"   # 10.1:1
MUTED         = "#8A94A6"   #  6.3:1 - labels, captions, axis ticks
FAINT         = "#6B7485"   #  4.1:1 - separators and non-essential meta only
PRIMARY       = "#3D84FA"   # buttons, focus, active state
ACCENT        = "#5B9DFF"   # links, single-series lines, highlights
POS           = "#3FB96B"   # gain / good
NEG           = "#E5484D"   # loss / bad
WARN          = "#E0A33E"   # attention (dated catalysts, stale data)
VIOLET        = "#9085E9"

# Categorical series, in the order validated for colour-vision deficiency on
# BG (dataviz validate_palette.js, adjacent pairs): blue, orange, violet, aqua.
SERIES = ("#3987E5", "#D95926", "#9085E9", "#199E70")

# Moving averages sit on green/red candles and amber catalyst marks, so they
# avoid all three: blue -> violet -> a light neutral for the long baseline.
SMA_COLORS = {"sma20": ACCENT, "sma50": VIOLET, "sma200": "#C9D1DD"}

# ---------------------------------------------------------------- taxonomy
# Catalyst types fold into three families for colour (a scatter can only
# carry ~3 distinguishable hues - validated all-pairs: blue/orange + a
# de-emphasised neutral for the low-weight corporate events).
CATALYST_TYPES: dict[str, tuple[str, str]] = {
    "pdufa":             ("PDUFA date", "regulatory"),
    "adcom":             ("Advisory committee", "regulatory"),
    "fda_action":        ("FDA action", "regulatory"),
    "phase3_readout":    ("Phase 3 readout", "clinical"),
    "phase2_readout":    ("Phase 2 readout", "clinical"),
    "phase1_readout":    ("Phase 1 readout", "clinical"),
    "trial_completion":  ("Trial completion", "clinical"),
    "data_presentation": ("Data presentation", "clinical"),
    "earnings":          ("Earnings", "corporate"),
    "other":             ("Other", "corporate"),
}
FAMILIES: dict[str, tuple[str, str, str]] = {
    # key: (label, chart colour, badge colour)
    "regulatory": ("Regulatory", SERIES[1], "orange"),
    "clinical":   ("Clinical", SERIES[0], "blue"),
    "corporate":  ("Corporate", MUTED, "gray"),
}

# Trial phase is ordinal (maturity), so it gets one hue stepped light -> strong
# rather than status red/amber. Grouped exactly like the catalyst model does
# (P2/P3 counts as phase 3, P1/P2 as phase 2) - validated as an ordinal ramp.
PHASE_COLORS = {"Phase 1": "#1C5CAB", "Phase 2": "#3987E5", "Phase 3": "#9EC5F4",
                "Other": FAINT}


def catalyst_label(ctype: str) -> str:
    return CATALYST_TYPES.get(str(ctype), (str(ctype).replace("_", " ").capitalize(), ""))[0]


def catalyst_family(ctype: str) -> str:
    return CATALYST_TYPES.get(str(ctype), ("", "corporate"))[1]


def phase_group(phase: str | None) -> str:
    p = (phase or "").upper()
    if "P3" in p:
        return "Phase 3"
    if "P2" in p:
        return "Phase 2"
    if "P1" in p:
        return "Phase 1"
    return "Other"


# ---------------------------------------------------------------- formatting
def esc(x) -> str:
    """HTML-escape anything that came from outside (RSS titles, notes...)."""
    return _html.escape("" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))


# mirrors bioterm.util.strip_markup (kept local: a brand-new symbol imported from a
# long-lived bioterm module breaks Streamlit Cloud's fast reboot). Tag-shaped only -
# "p<0.001" is prose - plus a tag cut off by truncation in older alert rows.
_TAG_RE = re.compile(r"<[A-Za-z/!?][^<>]*>|<[A-Za-z][\w-]*\s+[\w:-]+=[^<>]*$")


def plain(x) -> str:
    """Text content of a feed field. Some RSS titles embed markup (FierceBiotech
    wraps the title in its own <a href=...>), so tags are dropped and entities
    decoded before the text is escaped for display."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return " ".join(_html.unescape(_TAG_RE.sub(" ", str(x))).split())


_KEEP_UPPER = {"AB", "AG", "AS", "BV", "LP", "NV", "SA", "SE", "UK", "US", "USA", "II", "III"}
_CORP_WORDS = {"INC", "CORP", "LTD", "PLC", "CO", "LLC", "HOLDINGS", "GROUP"}


def display_name(name) -> str:
    """SEC/ETF feeds deliver some names in ALL CAPS ("EXELIXIS INC"). Those read
    as shouting next to mixed-case names, so all-caps names are title-cased,
    keeping short acronyms ("TG", "BV") intact. Mixed-case names pass through."""
    s = plain(name)
    if not s or not s.isupper():
        return s
    words = []
    for w in s.split():
        core = w.strip(".,&")
        if core in _KEEP_UPPER or (len(core) <= 3 and core not in _CORP_WORDS and core.isalpha()):
            words.append(w)
        else:
            words.append(w.capitalize())
    return " ".join(words)


def safe_url(u) -> str:
    """Only http(s) links make it into an href - never javascript: or data:."""
    u = "" if u is None else str(u).strip()
    return _html.escape(u, quote=True) if u.lower().startswith(("http://", "https://")) else ""


def usd(x, digits: int = 0, sign: bool = False) -> str:
    """$1,234 / −$1,234 / +$1,234 - the sign goes before the currency symbol."""
    if x is None or pd.isna(x):
        return "–"
    v = float(x)
    s = "−" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{s}${abs(v):,.{digits}f}"


def md_safe(s: str) -> str:
    """Escape dollar signs for Streamlit markdown, where two of them on one line
    otherwise open a LaTeX formula and swallow the text in between."""
    return str(s).replace("$", "\\$")


def signed(x, digits: int = 2) -> str:
    return "–" if x is None or pd.isna(x) else f"{float(x):+.{digits}f}"


def num(x, digits: int = 2) -> str:
    return "–" if x is None or pd.isna(x) else f"{float(x):.{digits}f}"


def tone_of(signal) -> tuple[str, str]:
    """-1..+1 sentiment -> (word, colour). Words carry the meaning; colour
    only reinforces it."""
    if signal is None or pd.isna(signal):
        return "No data", MUTED
    v = float(signal)
    if v > 0.25:
        return "Bullish", POS
    if v > 0.08:
        return "Positive", POS
    if v < -0.25:
        return "Bearish", NEG
    if v < -0.08:
        return "Negative", NEG
    return "Neutral", MUTED


# Back-compat alias used by older call sites.
def sentiment_word(val) -> tuple[str, str]:
    w, c = tone_of(val)
    return w.lower(), c


# ---------------------------------------------------------------- icons
def icon(name: str, cls: str = "") -> str:
    """A Material Symbols glyph for custom HTML (the font ships with Streamlit)."""
    return f"<span class='bt-i {cls}' aria-hidden='true'>{esc(name)}</span>"


# ---------------------------------------------------------------- page chrome
def _freshness() -> tuple[str, str, str]:
    """(state, label, tooltip) for the data-freshness chip - state is
    ok / stale / error so a stopped ingestion job is visible at a glance."""
    from _shared import ingest_status

    try:
        stt = ingest_status()
    except Exception:  # noqa: BLE001 - the chip must never break a page
        return "error", "Data status unavailable", ""
    if stt.empty:
        return "stale", "Waiting for first data run", ""
    last = pd.to_datetime(stt["finished_at"], utc=True, errors="coerce").max()
    latest = stt.sort_values("started_at").groupby("job").last()
    errs = latest[latest["status"] == "error"].index.tolist()
    when = f"{last:%b %d · %H:%M} UTC" if pd.notna(last) else "unknown"
    if errs:
        return "error", f"Updated {when}", "Last run failed: " + ", ".join(errs)
    age_h = (pd.Timestamp.now(tz="UTC") - last).total_seconds() / 3600 if pd.notna(last) else 99
    if age_h > 26:
        return "stale", f"Stale · {when}", "No successful refresh in over a day"
    return "ok", f"Updated {when}", "All ingestion jobs succeeded on the last run"


def page_header(title: str, subtitle: str | None = None) -> None:
    """Title + one-line description on the left, data freshness on the right."""
    state, label, tip = _freshness()
    with st.container(horizontal=True, horizontal_alignment="distribute",
                      vertical_alignment="center", key="bt-header"):
        with st.container(gap=None, width="stretch"):
            st.title(title, anchor=False)
            if subtitle:
                st.caption(subtitle)
        with st.container(horizontal=True, vertical_alignment="center",
                          gap="small", width="content"):
            st.html(f"<div class='bt-status {state}' title='{esc(tip)}'>"
                    f"<span class='bt-pulse'></span>{esc(label)}</div>")
            import _auth

            _auth.header_chip()
            if os.environ.get("GH_DISPATCH_TOKEN") and os.environ.get("GH_REPO") \
                    and _auth.can_edit():
                if st.button("Refresh", icon=":material/refresh:", type="tertiary",
                             help="Queue a data refresh (ingest-fast workflow)",
                             key="bt-refresh"):
                    from _shared import trigger_workflow

                    ok, msg = trigger_workflow("ingest-fast.yml")
                    (st.toast(msg, icon=":material/check_circle:") if ok
                     else st.toast(msg, icon=":material/error:"))


def footer() -> None:
    st.html(
        "<div class='bt-footer'>"
        "<span><b>BioTerm</b> · biotech intelligence terminal</span>"
        "<span>Monitoring and screening only — not investment advice. "
        "Data: Yahoo Finance · SEC EDGAR · ClinicalTrials.gov · openFDA · FDA Orange Book · "
        "Federal Register · Nasdaq Trader · FINRA · USAspending · SSGA · Europe PMC · "
        "OpenFIGI · company press releases</span>"
        "</div>")


# ---------------------------------------------------------------- containers
def card(title: str | None = None, *, icon_name: str | None = None,
         meta: str | None = None, key: str | None = None, height=None):
    """A bordered section with an optional compact header. Use as a context
    manager: ``with card("Next catalysts", icon_name="event_upcoming"): ...``"""
    kwargs = {"border": True, "key": key}
    if height is not None:
        kwargs["height"] = height
    c = st.container(**kwargs)
    if title:
        ic = icon(icon_name, "bt-card-ic") if icon_name else ""
        mt = f"<span class='bt-card-meta'>{esc(meta)}</span>" if meta else ""
        c.html(f"<div class='bt-card-h'>{ic}<span>{esc(title)}</span>{mt}</div>")
    return c


def kpi_row(n: int, name: str):
    """A row of ``n`` metric cards that wraps into balanced rows (4 -> 2x2 on a
    tablet, never 3 + a stretched 1) and keeps every card the same height.
    ``name`` just has to be unique on the page."""
    return st.container(horizontal=True, gap="small", key=f"bt-kpis-{n}-{name}")


def label(text: str, meta: str | None = None) -> None:
    """A small uppercase group label for stacking sections inside a card."""
    mt = f"<span class='bt-card-meta'>{esc(meta)}</span>" if meta else ""
    st.html(f"<div class='bt-label'><span>{esc(text)}</span>{mt}</div>")


def empty_state(title: str, body: str = "", icon_name: str = "inbox") -> None:
    st.html(f"<div class='bt-empty'>{icon(icon_name)}<div class='t'>{esc(title)}</div>"
            f"<div class='b'>{esc(body)}</div></div>")


def badge(text: str, color: str = "gray") -> str:
    """Inline badge for custom HTML rows (native st.badge for everything else)."""
    return f"<span class='bt-badge {esc(color)}'>{esc(text)}</span>"


def catalyst_badge(ctype: str) -> str:
    fam = FAMILIES.get(catalyst_family(ctype), FAMILIES["corporate"])
    return badge(catalyst_label(ctype), fam[2])


def kv_list(rows: Iterable[tuple[str, str, str | None]]) -> None:
    """Key/value list. rows = (label, value, colour|None); a row whose value
    is None renders as a group label."""
    parts = []
    for k, v, c in rows:
        if v is None:
            parts.append(f"<div class='bt-kv-group'>{esc(k)}</div>")
            continue
        style = f" style='color:{c}'" if c else ""
        parts.append(f"<div class='bt-kv'><span>{esc(k)}</span><b{style}>{esc(v)}</b></div>")
    st.html(f"<div class='bt-kvs'>{''.join(parts)}</div>")


# ---------------------------------------------------------------- list rows
def _list(rows: list[str]) -> None:
    st.html("<div class='bt-list'>" + "".join(rows) + "</div>")


def _when(ts, fmt: str = "%b %d") -> str:
    try:
        return pd.Timestamp(ts).strftime(fmt) if pd.notna(ts) else ""
    except (TypeError, ValueError):
        return ""


def headline_rows(df: pd.DataFrame, *, show_rank: dict | None = None,
                  time_fmt: str = "%b %d · %H:%M") -> None:
    """News rows: ticker column, linked title, then meta (time · source ·
    tone) and the event tags as badges."""
    out = []
    for _, r in df.iterrows():
        es = pd.to_numeric(r.get("event_score"), errors="coerce")
        es = 0.0 if pd.isna(es) else float(es)
        tone_w, tone_c = ("Positive event", POS) if es > 0.3 else \
                         ("Negative event", NEG) if es < -0.3 else ("", MUTED)
        all_tk = [t.strip() for t in str(r.get("tickers_csv") or r.get("ticker") or "").split(",")
                  if t.strip()]
        tk = all_tk[0] if all_tk else ""
        more = len(all_tk) - 1
        tk_html = (f"<span title='{esc(', '.join(all_tk))}'>{esc(tk)}<em>+{more}</em></span>"
                   if more > 0 else esc(tk))
        url = safe_url(r.get("url"))
        raw_title, source = plain(r.get("title")), plain(r.get("source"))
        # Google News titles end in " - <publisher>"; the publisher is the more
        # useful source than the aggregator's name.
        if source == "Google News" and " - " in raw_title:
            head, pub = raw_title.rsplit(" - ", 1)
            if 0 < len(pub) <= 48 and head:
                raw_title, source = head, pub
        title = esc(raw_title)
        title_html = (f"<a href='{url}' target='_blank' rel='noopener'>{title}</a>"
                      if url else title)
        tags = [t for t in str(r.get("event_tags") or "").split(",") if t.strip()]
        badges = "".join(badge(t.strip(), "green" if es > 0 else "red" if es < 0 else "gray")
                         for t in tags[:3])
        meta = [_when(r.get("published"), time_fmt), esc(source)]
        if tone_w:
            meta.append(f"<span style='color:{tone_c}'>● {tone_w}</span>")
        if show_rank is not None and tk in show_rank:
            meta.append(f"Focus #{int(show_rank[tk])}")
        out.append(
            "<div class='bt-row'>"
            f"<div class='bt-row-l'><span class='bt-tk'>{tk_html}</span></div>"
            "<div class='bt-row-m'>"
            f"<div class='bt-row-t'>{title_html}</div>"
            f"<div class='bt-row-s'>{' · '.join(m for m in meta if m)}{badges}</div>"
            "</div></div>")
    _list(out)


SOURCE_LABELS = {"news-extraction": "from news", "clinicaltrials.gov": "ClinicalTrials.gov",
                 "yfinance": "earnings calendar", "manual": "pinned by you",
                 "molecule-tracking": "molecule tracking", "ai-news": "AI-read headline",
                 "ai-filing": "AI-read filing", "sec-filing": "SEC filing",
                 "fda-notice": "FDA meeting notice"}


def catalyst_title(title) -> str:
    """The pipeline tags news-derived titles "(news) ..." - that's provenance,
    shown separately, not part of the headline."""
    t = plain(title)
    return t[7:] if t.lower().startswith("(news) ") else t


def catalyst_rows(df: pd.DataFrame, *, title_chars: int = 140) -> None:
    """Catalyst rows: a date block, ticker + type badge + confidence + source,
    then the title."""
    out = []
    for _, r in df.iterrows():
        d = pd.Timestamp(r["date"])
        conf = str(r.get("confidence") or "").lower()
        conf_html = f"<span class='bt-conf {esc(conf)}' title='{esc(conf)} confidence'>" \
                    f"<i></i><i></i><i></i></span>" if conf else ""
        src = SOURCE_LABELS.get(str(r.get("source") or ""), "")
        src_html = f"<span class='bt-src'>{esc(src)}</span>" if src else ""
        out.append(
            "<div class='bt-row'>"
            f"<div class='bt-row-l bt-date'><b>{d:%b} {d.day}</b><span>{d:%a}</span></div>"
            "<div class='bt-row-m'>"
            f"<div class='bt-row-h'><span class='bt-tk'>{esc(r['ticker'])}</span>"
            f"{catalyst_badge(r.get('type'))}{conf_html}{src_html}</div>"
            f"<div class='bt-row-s wrap'>"
            f"{esc(_clip(catalyst_title(r.get('title')), title_chars))}</div>"
            "</div></div>")
    _list(out)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


ALERT_ICONS = {"score move": ("trending_up", ACCENT), "catalyst soon": ("event_upcoming", WARN),
               "headline": ("newspaper", VIOLET), "signal": ("swap_vert", POS)}


def alert_detail(detail) -> str:
    """Alert details are composed by the engine from raw fields - feed titles
    (which can carry markup), catalyst type keys and the "(news)" provenance
    tag. Tidy all three for reading; the stored alert is untouched."""
    d = plain(detail).replace("— (news) ", "— ")
    head, sep, rest = d.partition(" · ")
    if sep and head in CATALYST_TYPES:
        d = catalyst_label(head) + sep + rest
    return d


def ticker_tape(items: list[tuple[str, float, float]]) -> None:
    """A scrolling strip of live quotes - (ticker, price, change %) - that pauses
    on hover and sits still for reduced-motion users. Each quote links to the
    stock page."""
    if not items:
        return
    cells = "".join(
        f"<a class='bt-tape-i' href='Stock_Detail?ticker={esc(t)}' target='_self'>"
        f"<b>{esc(t)}</b><span>{p:,.2f}</span>"
        f"<span style='color:{POS if c > 0 else NEG if c < 0 else MUTED}'>{c:+.2%}</span></a>"
        for t, p, c in items)
    st.html(f"<div class='bt-tape' role='marquee' aria-label='Live quotes'>"
            f"<div class='bt-tape-track'>{cells}<span aria-hidden='true' class='bt-tape-dup'>"
            f"{cells}</span></div></div>")


def status_rows(items: list[tuple[str, str, str]]) -> None:
    """Rows of (dot colour, title, meta) - health checks, freshness, channels."""
    _list([f"<div class='bt-row'><div class='bt-row-l'><span class='bt-dot' "
           f"style='background:{esc(c)}'></span></div><div class='bt-row-m'>"
           f"<div class='bt-row-h'><b>{esc(t)}</b></div>"
           f"<div class='bt-row-s wrap'>{esc(m)}</div></div></div>" for c, t, m in items])


def alert_rows(items: list[dict]) -> None:
    out = []
    for a in items:
        ic, col = ALERT_ICONS.get(a.get("kind"), ("notifications", MUTED))
        out.append(
            "<div class='bt-row'>"
            f"<div class='bt-row-l'><span class='bt-alert-ic' style='color:{col}'>"
            f"{icon(ic)}</span></div>"
            "<div class='bt-row-m'>"
            f"<div class='bt-row-h'><span class='bt-tk'>{esc(a.get('ticker'))}</span>"
            f"<span class='bt-row-kind'>{esc(str(a.get('kind', '')).capitalize())}</span></div>"
            f"<div class='bt-row-s wrap'>{esc(alert_detail(a.get('detail')))}</div>"
            "</div></div>")
    _list(out)


# ---------------------------------------------------------------- signals
# The five calls, strongest buy first. BUY/SELL are states (good/bad for the
# name), so they take POS/NEG; the STRONG variants add weight, not a new hue.
SIGNAL_LABELS = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]
SIGNAL_BADGE = {"STRONG BUY": "green strong", "BUY": "green", "NEUTRAL": "gray",
                "SELL": "red", "STRONG SELL": "red strong"}
SIGNAL_COLORS = {"STRONG BUY": POS, "BUY": "#8FDCAA", "NEUTRAL": MUTED, "SELL": "#F4A1A4",
                 "STRONG SELL": NEG}
REGIMES = {"risk_on": ("Risk-on", POS, "XBI above a rising 50- and 200-day average: buy "
                                        "signals get more weight"),
           "neutral": ("Neutral", MUTED, "Mixed sector trend: signals count at face value"),
           "risk_off": ("Risk-off", NEG, "XBI below its 200-day average or in a steep "
                                          "drawdown: buy signals are discounted, sell "
                                          "signals weigh more")}

# Evidence families - a STRONG call needs agreement from at least two.
SIGNAL_FAMILIES = {
    "technical": ("Price & volume", "candlestick_chart"),
    "event":     ("Catalysts & pipeline", "biotech"),
    "capital":   ("Cash & dilution", "account_balance"),
    "people":    ("Insiders & specialist funds", "groups"),
    "news":      ("News & regulatory", "newspaper"),
    "flow":      ("Options & short flow", "waterfall_chart"),
}

# code -> (name, family, what it looks for)
DETECTORS: dict[str, tuple[str, str, str]] = {
    "breakout_52w": ("52-week breakout", "technical",
                     "Close above the prior 52-week high on above-average volume"),
    "golden_cross": ("Golden cross", "technical", "50-day average crosses above the 200-day"),
    "death_cross": ("Death cross", "technical", "50-day average crosses below the 200-day"),
    "reclaim_sma200": ("Reclaims 200-day", "technical",
                       "Close back above the 200-day average on rising volume"),
    "breakdown_sma200": ("Loses 200-day", "technical",
                         "Close drops below the 200-day average on rising volume"),
    "rsi_oversold_reversal": ("Oversold reversal", "technical",
                              "RSI climbs back above 30 after an oversold stretch"),
    "volume_surge_up": ("Volume surge up", "technical",
                        "Volume 2.5σ above normal on a 5%+ up day - someone is buying"),
    "volume_surge_down": ("Volume surge down", "technical",
                          "Volume 2.5σ above normal on a 5%+ down day"),
    "crash_day": ("Crash day", "technical", "A single-session drop of 20% or more"),
    "overbought_exhaustion": ("Overbought exhaustion", "technical",
                              "RSI 80+, above the upper Bollinger band after a 35%+ month"),
    "accumulation": ("Accumulation", "technical",
                     "Chaikin money flow strongly positive while price is still flat"),
    "distribution": ("Distribution", "technical",
                     "Money flow strongly negative near the top of the 52-week range"),
    "relative_strength_leader": ("RS leader", "technical",
                                 "Top-decile 12-month relative strength in a clean uptrend"),
    "relative_strength_laggard": ("RS laggard", "technical",
                                  "Bottom-decile relative strength in a downtrend"),
    "pre_catalyst_setup": ("Pre-catalyst setup", "event",
                           "A clinical/regulatory readout 10-120 days out, the stock not yet "
                           "extended, and enough cash to get there"),
    "sell_the_news_risk": ("Sell-the-news risk", "event",
                           "Up 40%+ in three months into a binary event"),
    "catalyst_vacuum": ("Catalyst vacuum", "event",
                        "A readout just passed and nothing is dated for six months"),
    "pipeline_advance": ("Pipeline advance", "event", "A new Phase 2/3 trial just started"),
    "trial_halted": ("Trial halted", "event",
                     "A Phase 2/3 trial was suspended, terminated or withdrawn (30 days)"),
    "readout_delay": ("Readout delayed", "event",
                      "A Phase 2/3 primary completion date slipped 90+ days"),
    "enrollment_complete": ("Enrollment complete", "event",
                            "A Phase 2/3 trial finished enrolling - the readout clock runs"),
    "dilution_filing": ("Dilution filing", "capital",
                        "424B prospectus / S-1 / S-3 filed in the last 30 days"),
    "runway_crunch": ("Runway crunch", "capital",
                      "Under three quarters of cash and no raise in 90 days"),
    "going_concern": ("Going-concern doubt", "capital",
                      "Auditor going-concern language in the latest 10-K/10-Q"),
    "insider_cluster_buy": ("Insider cluster buy", "people",
                            "Two or more insiders buying on the open market (60 days)"),
    "insider_heavy_selling": ("Heavy insider selling", "people",
                              "Three or more insiders selling $2M+ on the open market"),
    "specialist_accumulation": ("Specialist accumulation", "people",
                                "Two or more biotech specialist funds initiated or added (13F)"),
    "specialist_exit": ("Specialist exit", "people",
                        "Two or more specialist funds cut or exited (13F)"),
    "activist_stake": ("Activist stake", "people",
                       "A Schedule 13D (5%+ holder with intent to influence) in 30 days"),
    "positive_event": ("Positive catalyst news", "news",
                       "Topline win, approval or similar headline in the last 3 days"),
    "negative_event": ("Negative catalyst news", "news",
                       "CRL, failed trial, clinical hold or similar in the last 5 days"),
    "regulatory_designation": ("FDA designation", "news",
                               "Breakthrough, fast track, priority review or orphan headline"),
    "sentiment_inflection": ("Sentiment inflection", "news",
                             "This week's headline tone vs the prior three weeks"),
    "ai_event_positive": ("AI-read positive event", "news",
                          "The LLM read a positive topline, approval or deal in a headline or "
                          "8-K (when the keyword detector missed it)"),
    "ai_event_negative": ("AI-read negative event", "news",
                          "The LLM read a failed trial, CRL, hold or financing in a headline or "
                          "8-K (when the keyword detector missed it)"),
    "unusual_call_activity": ("Unusual call buying", "flow",
                              "Call volume 1.5x+ open interest with a low put/call ratio"),
    "unusual_put_activity": ("Unusual put buying", "flow",
                             "Put volume 1.5x+ open interest with a high put/call ratio"),
    "short_squeeze_setup": ("Short-squeeze setup", "flow",
                            "20%+ of float short, price turning up, shorts not adding"),
    "short_pressure_rising": ("Short pressure rising", "flow",
                              "FINRA short share of volume jumping vs its 20-day average"),
}


def detector_name(code: str) -> str:
    return DETECTORS.get(str(code), (str(code).replace("_", " ").capitalize(), "", ""))[0]


def detector_family(code: str) -> str:
    return DETECTORS.get(str(code), ("", "event", ""))[1]


def signal_badge(label) -> str:
    lab = str(label or "NEUTRAL")
    return badge(lab.title(), SIGNAL_BADGE.get(lab, "gray"))


def regime_word(regime) -> tuple[str, str, str]:
    return REGIMES.get(str(regime or "neutral"), REGIMES["neutral"])


def _meter(strength: float, side: str) -> str:
    """A five-tick strength meter; ticks fill in the side's colour."""
    n = max(0, min(5, int(round(float(strength or 0) / 0.19 + 0.01))))
    cls = "buy" if side == "BUY" else "sell"
    ticks = "".join(f"<i class='{'on' if i < n else ''}'></i>" for i in range(5))
    return f"<span class='bt-meter {cls}' title='strength {float(strength or 0):.2f}'>{ticks}</span>"


def signal_rows(df: pd.DataFrame, *, show_ticker: bool = True) -> None:
    """Fired detectors: side glyph, name + family, strength meter, then the
    engine's plain-language reason."""
    out = []
    for _, r in df.iterrows():
        side = str(r.get("side"))
        up = side == "BUY"
        glyph = icon("north_east" if up else "south_east")
        fam = SIGNAL_FAMILIES.get(str(r.get("family") or detector_family(r.get("code"))),
                                  ("", ""))[0]
        tk = f"<span class='bt-tk'>{esc(r.get('ticker'))}</span>" if show_ticker else ""
        out.append(
            "<div class='bt-row'>"
            f"<div class='bt-row-l'><span class='bt-side {'buy' if up else 'sell'}'>"
            f"{glyph}<b>{'Buy' if up else 'Sell'}</b></span></div>"
            "<div class='bt-row-m'>"
            f"<div class='bt-row-h'>{tk}<span class='bt-sig-name'>"
            f"{esc(detector_name(r.get('code')))}</span>{_meter(r.get('strength'), side)}"
            f"<span class='bt-src'>{esc(fam)}</span></div>"
            f"<div class='bt-row-s wrap'>{esc(_clip(plain(r.get('title')), 170))}</div>"
            "</div></div>")
    _list(out)


def call_rows(df: pd.DataFrame, *, n_reasons: int = 1) -> None:
    """Signal calls: ticker + label badge + net, then the strongest reasons."""
    out = []
    for _, r in df.iterrows():
        tops = [t for t in (r.get("top_obj") or []) if isinstance(t, dict)]
        side = "BUY" if float(r.get("net") or 0) >= 0 else "SELL"
        tops = [t for t in tops if t.get("side") == side] or tops
        why = " · ".join(esc(_clip(plain(t.get("title")), 110)) for t in tops[:n_reasons])
        was = r.get("prev_label")
        changed = (isinstance(was, str) and was and was != r.get("label"))
        chg = f"<span class='bt-src'>was {esc(str(was).title())}</span>" if changed else \
            ("<span class='bt-src'>new</span>" if not isinstance(was, str) else "")
        net = float(r.get("net") or 0)
        out.append(
            "<div class='bt-row'>"
            f"<div class='bt-row-l'><span class='bt-tk'>{esc(r.get('ticker'))}</span></div>"
            "<div class='bt-row-m'>"
            f"<div class='bt-row-h'>{signal_badge(r.get('label'))}"
            f"<span class='bt-net' style='color:{POS if net > 0 else NEG if net < 0 else MUTED}'>"
            f"{net:+.2f}</span>{chg}"
            f"<span class='bt-src'>{esc(_clip(display_name(r.get('name')), 38))}</span></div>"
            f"<div class='bt-row-s wrap'>{why}</div>"
            "</div></div>")
    _list(out)


# ---------------------------------------------------------------- charts
CHART_CONFIG = {
    "displaylogo": False,
    "displayModeBar": "hover",
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines",
                               "hoverClosestCartesian", "hoverCompareCartesian"],
}


def plotly_layout(**over) -> dict:
    """Shared Plotly layout. Deliberately sets no ``template`` - Streamlit's
    own chart theme then applies the validated categorical palette and fonts
    from config.toml, and these values refine it: recessive hairline grid,
    muted ticks, a themed hover card, and a short transition so a redrawn
    trace interpolates instead of popping.

    ``title`` may be a plain string (it gets the shared small/muted style);
    a textless title is never set - Plotly.js renders that as "undefined".
    """
    title = over.pop("title", None)
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", size=12, color=TEXT_2),
        margin=dict(l=4, r=8, t=28, b=4),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=BORDER, ticks="",
                   tickfont=dict(color=MUTED, size=11)),
        yaxis=dict(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=BORDER,
                   ticks="", tickfont=dict(color=MUTED, size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, xanchor="left",
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11, color=TEXT_2),
                    itemsizing="constant"),
        hoverlabel=dict(bgcolor=SURFACE_2, bordercolor=BORDER_STRONG,
                        font=dict(family="Inter, sans-serif", size=12, color=TEXT)),
        hoverdistance=30,
        bargap=0.35,
        barcornerradius=4,
        modebar=dict(bgcolor="rgba(0,0,0,0)", color=FAINT, activecolor=ACCENT),
        transition=dict(duration=300, easing="cubic-in-out"),
    )
    if title is not None:
        base["title"] = dict(text=title, font=dict(size=12, color=MUTED), x=0, xanchor="left") \
            if isinstance(title, str) else title
        base["margin"] = dict(base["margin"], t=40)
    base.update(over)
    return base


def chart(fig, *, key: str | None = None) -> None:
    """Render a Plotly figure with the shared, uncluttered toolbar config."""
    st.plotly_chart(fig, config=CHART_CONFIG, key=key)


def spark(values, n: int | None = None) -> list[float] | None:
    """Clean a series for st.metric(chart_data=...): finite floats only, None
    when there's too little to draw."""
    s = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if n:
        s = s.tail(n)
    return [round(float(v), 4) for v in s] if len(s) >= 2 else None


# ---------------------------------------------------------------- stylesheet
# Only what config.toml can't express. Selectors prefer our own classes and
# st-key-* hooks; the few data-testid ones are limited to hover polish, so a
# Streamlit upgrade that renames them loses a nicety, never a layout.
_CSS = f"""
<style>
:root {{
  --bt-bg:{BG}; --bt-surface:{SURFACE}; --bt-surface2:{SURFACE_2};
  --bt-border:{BORDER}; --bt-border2:{BORDER_STRONG}; --bt-text:{TEXT};
  --bt-text2:{TEXT_2}; --bt-muted:{MUTED}; --bt-faint:{FAINT};
  --bt-accent:{ACCENT}; --bt-pos:{POS}; --bt-neg:{NEG}; --bt-warn:{WARN};
  --bt-ease: cubic-bezier(.4,0,.2,1);
  --bt-shadow: 0 12px 32px -16px rgba(0,0,0,.7);
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
}}

/* layout: a readable max width; Streamlit's own top padding already clears
   the navigation bar, so only the bottom is tightened */
[data-testid="stMainBlockContainer"] {{ max-width: 1440px; padding-bottom: 2.4rem; }}
[data-testid="stDecoration"] {{ display: none; }}
* {{ scrollbar-width: thin; scrollbar-color: {BORDER} transparent; }}
::-webkit-scrollbar {{ width: 9px; height: 9px; }}
::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 9px; border: 2px solid {BG}; }}
::-webkit-scrollbar-thumb:hover {{ background: {BORDER_STRONG}; }}

/* header */
.st-key-bt-header {{ margin-bottom: .35rem; }}
.st-key-bt-header h1 {{ padding: 0 !important; letter-spacing: -.02em; }}
/* Streamlit offsets a heading's own bottom padding with a negative margin on
   its container; with the padding removed above, that margin would pull the
   subtitle up into the title */
.st-key-bt-header [data-testid="stHeading"] [data-testid="stMarkdownContainer"] {{
  margin-bottom: 0 !important; }}
.st-key-bt-header [data-testid="stCaptionContainer"] {{ margin-top: .3rem; }}
.bt-status {{
  display: inline-flex; align-items: center; gap: .5rem; white-space: nowrap;
  font-size: .8rem; color: var(--bt-text2); padding: .3rem .7rem;
  border: 1px solid var(--bt-border); border-radius: 999px; background: var(--bt-surface);
}}
.bt-pulse {{ width: 7px; height: 7px; border-radius: 50%; background: var(--bt-pos);
  box-shadow: 0 0 0 0 rgba(63,185,107,.5); animation: bt-pulse 2.4s var(--bt-ease) infinite; }}
.bt-status.stale .bt-pulse {{ background: var(--bt-warn); animation: none; }}
.bt-status.error .bt-pulse {{ background: var(--bt-neg); animation: none; }}
.bt-status.error {{ color: #F2A7A9; border-color: rgba(229,72,77,.35); }}
@keyframes bt-pulse {{
  0% {{ box-shadow: 0 0 0 0 rgba(63,185,107,.45); }}
  70% {{ box-shadow: 0 0 0 6px rgba(63,185,107,0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(63,185,107,0); }}
}}

/* cards: bordered containers + metrics lift gently on hover */
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stMetric"] {{
  transition: border-color .18s var(--bt-ease), box-shadow .18s var(--bt-ease);
}}
[data-testid="stMetric"]:hover {{ border-color: var(--bt-border2); box-shadow: var(--bt-shadow); }}

/* KPI rows: a grid whose column minimum depends on the card count, so rows
   wrap evenly at any width; cards in a row share one height */
[class*="st-key-bt-kpis-"] {{ display: grid !important; align-items: stretch; }}
[class*="st-key-bt-kpis-"] > * {{ width: auto !important; min-width: 0; }}
[class*="st-key-bt-kpis-"] [data-testid="stMetric"] {{ height: 100%; }}
[class*="st-key-bt-kpis-2-"] {{ grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
[class*="st-key-bt-kpis-3-"] {{ grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }}
[class*="st-key-bt-kpis-4-"] {{ grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }}
[class*="st-key-bt-kpis-5-"] {{ grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }}
[class*="st-key-bt-kpis-6-"] {{ grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }}
[class*="st-key-bt-kpis-7-"] {{ grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); }}
[data-testid="stMetricLabel"] p {{ color: var(--bt-muted); font-weight: 500; }}
.bt-card-h {{ display: flex; align-items: center; gap: .45rem; font-weight: 600;
  font-size: .92rem; color: var(--bt-text); margin: .1rem 0 .15rem; }}
.bt-card-ic {{ color: var(--bt-muted); font-size: 1.1rem !important; }}
.bt-card-meta {{ margin-left: auto; color: var(--bt-muted); font-weight: 400; font-size: .8rem; }}
.bt-label {{ display: flex; align-items: baseline; gap: .5rem; text-transform: uppercase;
  letter-spacing: .07em; font-size: .7rem; font-weight: 600; color: var(--bt-muted);
  margin: .5rem 0 .1rem; }}

/* identity row on the stock page */
.bt-hero {{ display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; margin: .5rem 0 .35rem; }}
.bt-hero-tk {{ font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 1.6rem;
  font-weight: 600; letter-spacing: -.01em; color: var(--bt-text); }}
.bt-hero-name {{ font-size: 1.05rem; color: var(--bt-text2); margin-right: .35rem; }}

/* material symbols inside custom html */
.bt-i {{ font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal;
  font-size: 1.15rem; line-height: 1; letter-spacing: normal; text-transform: none;
  display: inline-block; white-space: nowrap; direction: ltr; vertical-align: middle;
  -webkit-font-smoothing: antialiased; font-feature-settings: 'liga'; }}

/* list rows - one bordered list, hairline separators, a quiet hover wash */
@keyframes bt-in {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
.bt-list {{ display: flex; flex-direction: column; animation: bt-in .22s var(--bt-ease) both; }}
.bt-row {{ display: flex; gap: .85rem; padding: .62rem .5rem; border-top: 1px solid var(--bt-border);
  border-radius: 6px; transition: background-color .15s var(--bt-ease); }}
.bt-row:first-child {{ border-top: none; }}
.bt-row:hover {{ background: rgba(255,255,255,.025); }}
.bt-row-l {{ flex: 0 0 64px; min-width: 64px; padding-top: .1rem; }}
.bt-row-m {{ flex: 1; min-width: 0; }}
.bt-row-t {{ font-size: .92rem; line-height: 1.35; color: var(--bt-text); }}
.bt-row-t a {{ color: var(--bt-text); text-decoration: none; }}
.bt-row-t a:hover {{ color: var(--bt-accent); text-decoration: underline;
  text-underline-offset: 3px; text-decoration-thickness: 1px; }}
.bt-src {{ color: var(--bt-faint); font-size: .74rem; }}
.bt-row-h {{ display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }}
.bt-row-s {{ margin-top: .28rem; font-size: .78rem; color: var(--bt-muted); display: flex;
  align-items: center; gap: .4rem; flex-wrap: wrap; }}
.bt-row-s.wrap {{ display: block; color: var(--bt-text2); font-size: .84rem; line-height: 1.4; }}
.bt-row-kind {{ color: var(--bt-muted); font-size: .8rem; }}
.bt-dot {{ width: .55rem; height: .55rem; border-radius: 50%; display: inline-block;
          margin-top: .45rem; }}
.bt-tape {{ overflow: hidden; border-bottom: 1px solid var(--bt-border); margin: -.4rem 0 .6rem;
           -webkit-mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent);
           mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent); }}
.bt-tape-track {{ display: inline-flex; gap: 1.6rem; white-space: nowrap; padding: .32rem 0;
                 animation: bt-tape 70s linear infinite; }}
.bt-tape-dup {{ display: inline-flex; gap: 1.6rem; }}
.bt-tape:hover .bt-tape-track {{ animation-play-state: paused; }}
.bt-tape-i {{ display: inline-flex; gap: .45rem; font: 500 .78rem 'JetBrains Mono', monospace;
             color: var(--bt-text2); text-decoration: none; }}
.bt-tape-i b {{ color: var(--bt-text); font-weight: 600; }}
.bt-tape-i:hover b {{ color: var(--bt-accent); }}
@keyframes bt-tape {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
@media (prefers-reduced-motion: reduce) {{ .bt-tape {{ overflow-x: auto; }}
  .bt-tape-dup {{ display: none; }} }}
.bt-tk {{ font-family: 'JetBrains Mono', ui-monospace, monospace; font-weight: 600;
  font-size: .8rem; color: var(--bt-text); letter-spacing: .01em; }}
.bt-tk em {{ font-style: normal; color: var(--bt-faint); font-weight: 500; margin-left: 2px; }}
.bt-date {{ display: flex; flex-direction: column; line-height: 1.15; }}
.bt-date b {{ font-size: .84rem; font-weight: 600; color: var(--bt-text); white-space: nowrap; }}
.bt-date span {{ font-size: .72rem; color: var(--bt-muted); }}
.bt-alert-ic {{ display: inline-flex; width: 30px; height: 30px; align-items: center;
  justify-content: center; border-radius: 8px; background: var(--bt-surface); }}

/* badges - tinted fill, lighter text; colour never carries meaning alone */
.bt-badge {{ display: inline-flex; align-items: center; padding: .05rem .45rem;
  border-radius: 6px; font-size: .72rem; font-weight: 500; line-height: 1.45;
  white-space: nowrap; background: rgba(138,148,166,.16); color: #C3CAD6; }}
.bt-badge.blue   {{ background: rgba(57,135,229,.18);  color: #9DC2FF; }}
.bt-badge.orange {{ background: rgba(217,89,38,.20);   color: #F4AE8C; }}
.bt-badge.green  {{ background: rgba(63,185,107,.17);  color: #8FDCAA; }}
.bt-badge.red    {{ background: rgba(229,72,77,.18);   color: #F4A1A4; }}
.bt-badge.violet {{ background: rgba(144,133,233,.20); color: #C5BEF7; }}
.bt-badge.yellow {{ background: rgba(224,163,62,.18);  color: #F0CE8E; }}

/* confidence meter: three ticks */
.bt-conf {{ display: inline-flex; gap: 2px; align-items: flex-end; height: 11px; }}
.bt-conf i {{ width: 3px; border-radius: 1px; background: var(--bt-border2); }}
.bt-conf i:nth-child(1) {{ height: 5px; }} .bt-conf i:nth-child(2) {{ height: 8px; }}
.bt-conf i:nth-child(3) {{ height: 11px; }}
.bt-conf.low i:nth-child(1), .bt-conf.medium i:nth-child(-n+2),
.bt-conf.high i {{ background: var(--bt-text2); }}

/* key/value lists */
.bt-kvs {{ display: flex; flex-direction: column; }}
.bt-kv {{ display: flex; justify-content: space-between; gap: 1rem; padding: .34rem 0;
  border-top: 1px solid var(--bt-border); font-size: .86rem; }}
.bt-kv span {{ color: var(--bt-muted); }}
.bt-kv b {{ font-weight: 600; color: var(--bt-text); font-variant-numeric: tabular-nums; }}
.bt-kv-group {{ text-transform: uppercase; letter-spacing: .07em; font-size: .68rem;
  font-weight: 600; color: var(--bt-muted); margin: .8rem 0 .15rem; }}
.bt-kv-group:first-child {{ margin-top: .1rem; }}

/* empty state */
.bt-empty {{ display: flex; flex-direction: column; align-items: center; text-align: center;
  gap: .35rem; padding: 2.2rem 1rem; color: var(--bt-muted); }}
.bt-empty .bt-i {{ font-size: 1.9rem; color: var(--bt-faint); }}
.bt-empty .t {{ color: var(--bt-text2); font-weight: 600; font-size: .95rem; }}
.bt-empty .b {{ font-size: .84rem; max-width: 46ch; }}

/* signals: strong calls, side glyph, strength meter, net */
.bt-badge.strong {{ font-weight: 700; letter-spacing: .02em; }}
.bt-badge.green.strong {{ background: rgba(63,185,107,.30); color: #B5EBC8;
  box-shadow: inset 0 0 0 1px rgba(63,185,107,.45); }}
.bt-badge.red.strong {{ background: rgba(229,72,77,.30); color: #F8C3C5;
  box-shadow: inset 0 0 0 1px rgba(229,72,77,.45); }}
.bt-side {{ display: inline-flex; align-items: center; gap: .2rem; font-size: .74rem;
  font-weight: 600; padding: .12rem .4rem; border-radius: 6px; }}
.bt-side .bt-i {{ font-size: .95rem; }}
.bt-side.buy {{ color: #8FDCAA; background: rgba(63,185,107,.12); }}
.bt-side.sell {{ color: #F4A1A4; background: rgba(229,72,77,.12); }}
.bt-sig-name {{ font-weight: 600; font-size: .86rem; color: var(--bt-text); }}
.bt-meter {{ display: inline-flex; gap: 2px; align-items: center; }}
.bt-meter i {{ width: 9px; height: 5px; border-radius: 2px; background: var(--bt-border2); }}
.bt-meter.buy i.on {{ background: var(--bt-pos); }}
.bt-meter.sell i.on {{ background: var(--bt-neg); }}
.bt-net {{ font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: .8rem;
  font-weight: 600; font-variant-numeric: tabular-nums; }}
.bt-regime {{ display: inline-flex; align-items: center; gap: .45rem; font-size: .8rem;
  color: var(--bt-text2); padding: .3rem .7rem; border: 1px solid var(--bt-border);
  border-radius: 999px; background: var(--bt-surface); white-space: nowrap; }}
.bt-regime i {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}

/* footer */
.bt-footer {{ display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  margin-top: 2.2rem; padding-top: 1rem; border-top: 1px solid var(--bt-border);
  font-size: .76rem; color: var(--bt-faint); }}
.bt-footer b {{ color: var(--bt-muted); font-weight: 600; }}
</style>
"""


def inject_css() -> None:
    st.html(_CSS)
