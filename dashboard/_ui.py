"""Design system for the BioTerm dashboard: theme CSS, headers, small components.

One import surface so every page looks the same. Call ``page_setup(title, subtitle)``
at the top of each page (it also renders the sidebar and injects the CSS once).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

# ---- palette -----------------------------------------------------------------
BG          = "#0b0e14"
SURFACE     = "#141a24"
SURFACE_2   = "#1b2330"
BORDER      = "#26303f"
TEXT        = "#e7ebf3"
MUTED       = "#8a94a6"
ACCENT      = "#5b9dff"
POS         = "#3fb96b"
NEG         = "#e5484d"
WARN        = "#e0a33e"

# consistent series colours for charts
PHASE_COLORS = {"P3": "#e5484d", "P2/P3": "#e5484d", "P2": "#e0a33e",
                "P1/P2": "#d9b44a", "P1": "#5b9dff", "EP1": "#7c8698", "NA": "#7c8698"}
SMA_COLORS = {"sma20": "#5b9dff", "sma50": "#b07cff", "sma200": "#e0a33e"}

PLOTLY_TEMPLATE = "plotly_dark"


def plotly_layout(**over) -> dict:
    """Shared Plotly layout — transparent bg, faint grid, Inter font."""
    base = dict(
        template=PLOTLY_TEMPLATE,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", size=12, color=TEXT),
        margin=dict(l=8, r=8, t=34, b=8),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        hoverlabel=dict(font=dict(family="Inter, sans-serif", size=12)),
        title=dict(font=dict(size=13, color=MUTED)),
    )
    base.update(over)
    return base


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{
  --bg:{BG}; --surface:{SURFACE}; --surface2:{SURFACE_2}; --border:{BORDER};
  --text:{TEXT}; --muted:{MUTED}; --accent:{ACCENT};
}}

html, body, [class*="css"], .stApp, [data-testid="stMarkdownContainer"] {{
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  color: var(--text);
}}
.stApp {{ background: var(--bg); }}

/* tighten the giant default top padding, cap width for readability */
.block-container, [data-testid="stMainBlockContainer"] {{
  padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1360px;
}}

/* trim Streamlit chrome: toolbar (Fork/Deploy), top gradient bar, footer badge */
[data-testid="stToolbar"], [data-testid="stDecoration"], footer {{ display: none !important; }}
[data-testid="stHeader"] {{ background: transparent; }}

/* headings */
h1 {{ font-size: 1.5rem !important; font-weight: 700; letter-spacing:-0.01em;
      margin-bottom:.15rem !important; }}
h2 {{ font-size: 1.12rem !important; font-weight: 650; letter-spacing:-0.005em;
      margin: 1.1rem 0 .4rem !important; color: var(--text); }}
h3 {{ font-size: .98rem !important; font-weight: 600; color: var(--text); }}

/* numbers & tickers = mono */
code, kbd, pre, .mono,
[data-testid="stMetricValue"], [data-testid="stMetricDelta"],
[data-testid="stDataFrame"] {{ font-family: 'JetBrains Mono', ui-monospace, monospace; }}
code {{ background: var(--surface2); color: var(--accent);
       padding: .05rem .3rem; border-radius: 4px; font-size: .82em; }}

/* metric -> card */
[data-testid="stMetric"] {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: .7rem .9rem;
}}
[data-testid="stMetricLabel"] {{ white-space: normal !important; overflow: visible; }}
[data-testid="stMetricLabel"] p {{
  font-size: .68rem !important; line-height:1.15; letter-spacing:.04em;
  text-transform: uppercase; color: var(--muted); font-family:'Inter',sans-serif;
  white-space: normal !important;
}}
[data-testid="stMetricValue"] {{ font-size: 1.3rem !important; font-weight:500;
  line-height:1.2; }}
[data-testid="stMetricDelta"] {{ font-size: .74rem !important; }}
[data-testid="stMetricDelta"] svg {{ display:none; }}

/* dividers */
hr {{ margin: 1.1rem 0 !important; border-color: var(--border) !important; opacity:.6; }}

/* captions / small text */
[data-testid="stCaptionContainer"], .stCaption, small {{
  color: var(--muted) !important; font-size: .8rem;
}}

/* dataframe */
[data-testid="stDataFrame"] {{ border:1px solid var(--border); border-radius:10px; }}

/* tabs */
.stTabs [data-baseweb="tab-list"] {{ gap: .25rem; border-bottom:1px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{
  font-size:.86rem; padding:.4rem .7rem; color:var(--muted);
}}
.stTabs [aria-selected="true"] {{ color: var(--text) !important; }}

/* buttons */
.stButton button, .stDownloadButton button {{
  border-radius: 8px; border:1px solid var(--border); font-weight:500;
  font-size:.84rem;
}}
.stButton button[kind="primary"] {{ border-color: var(--accent); }}

/* links */
a, a:visited {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* sidebar */
[data-testid="stSidebar"] {{ background: #0d1219; border-right:1px solid var(--border); }}
[data-testid="stSidebarNav"] a {{ font-size:.88rem; }}

/* --- custom helpers --- */
.bt-brand {{ display:flex; align-items:center; gap:.5rem; font-weight:700;
  font-size:1.05rem; letter-spacing:-.01em; margin-bottom:.1rem; }}
.bt-sub {{ color:var(--muted); font-size:.82rem; margin:-.1rem 0 1rem; }}
.bt-eyebrow {{ text-transform:uppercase; letter-spacing:.08em; font-size:.7rem;
  color:var(--muted); font-weight:600; margin:1.2rem 0 .4rem; }}
.bt-card {{ background:var(--surface); border:1px solid var(--border);
  border-radius:10px; padding:.7rem .85rem; margin-bottom:.5rem; }}
.bt-row {{ display:flex; justify-content:space-between; gap:.6rem; align-items:baseline; }}
.bt-tk {{ font-family:'JetBrains Mono',monospace; font-weight:600; color:var(--text); }}
.bt-meta {{ color:var(--muted); font-size:.76rem; }}
.bt-pos {{ color:{POS}; }} .bt-neg {{ color:{NEG}; }} .bt-warn {{ color:{WARN}; }}
.bt-dot {{ display:inline-block; width:.55rem; height:.55rem; border-radius:50%;
  vertical-align:middle; }}
.bt-statline {{ display:flex; flex-wrap:wrap; gap:.35rem .1rem; align-items:baseline;
  margin:.2rem 0 1rem; }}
.bt-stat {{ background:var(--surface); border:1px solid var(--border);
  border-radius:7px; padding:.28rem .6rem; font-size:.82rem; white-space:nowrap; }}
.bt-stat b {{ font-family:'JetBrains Mono',monospace; font-weight:600; margin-left:.3rem; }}
.bt-stat .k {{ color:var(--muted); text-transform:uppercase; letter-spacing:.04em;
  font-size:.68rem; }}
</style>
"""


def page_setup(title: str, subtitle: str | None = None, icon: str = "") -> None:
    """Inject the theme, render the sidebar, and the compact page header.

    The CSS must go in on every page run — Streamlit drops a prior page's
    ``st.markdown`` output when you navigate, so a once-per-session guard would
    leave pages 2+ unstyled.
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    _sidebar()
    head = f"{icon} {title}".strip()
    st.markdown(f"<div class='bt-brand'>{head}</div>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='bt-sub'>{subtitle}</div>", unsafe_allow_html=True)
    else:
        st.write("")


def eyebrow(text: str) -> None:
    st.markdown(f"<div class='bt-eyebrow'>{text}</div>", unsafe_allow_html=True)


def stat_strip(items: list[tuple[str, str, str | None]]) -> None:
    """items = [(label, value, color|None), …] rendered as a wrapping chip row."""
    chips = []
    for k, v, c in items:
        style = f" style='color:{c}'" if c else ""
        chips.append(f"<span class='bt-stat'><span class='k'>{k}</span>"
                     f"<b{style}>{v}</b></span>")
    st.markdown(f"<div class='bt-statline'>{''.join(chips)}</div>",
                unsafe_allow_html=True)


def signal_dot(val: float | None) -> str:
    """−1..+1 → a coloured dot + label, as an HTML span."""
    if val is None or pd.isna(val):
        return "<span class='bt-meta'>–</span>"
    v = float(val)
    color = POS if v > 0.12 else NEG if v < -0.12 else WARN if abs(v) > 0.04 else MUTED
    return f"<span class='bt-dot' style='background:{color}'></span> <span class='mono'>{v:+.2f}</span>"


def sentiment_word(val: float | None) -> tuple[str, str]:
    if val is None or pd.isna(val):
        return "n/a", MUTED
    v = float(val)
    if v > 0.25:
        return "bullish", POS
    if v > 0.08:
        return "positive", POS
    if v < -0.25:
        return "bearish", NEG
    if v < -0.08:
        return "negative", NEG
    return "neutral", MUTED


def _sidebar() -> None:
    from _shared import ingest_status, trigger_workflow
    import os

    sb = st.sidebar
    sb.markdown("<div class='bt-brand'>🧬 BioTerm</div>"
                "<div class='bt-sub'>catalyst-monitoring terminal</div>",
                unsafe_allow_html=True)

    stt = ingest_status()
    if not stt.empty:
        last = pd.to_datetime(stt["finished_at"]).max()
        sb.markdown(f"<span class='bt-meta'>updated {last:%b %d · %H:%M} UTC</span>",
                    unsafe_allow_html=True)
        latest = stt.sort_values("started_at").groupby("job").last()
        errs = latest[latest["status"] == "error"].index.tolist()
        if errs:
            sb.warning("last run failed: " + ", ".join(errs), icon="⚠️")

    if os.environ.get("GH_DISPATCH_TOKEN") and os.environ.get("GH_REPO"):
        if sb.button("↻ refresh data", use_container_width=True):
            ok, msg = trigger_workflow("ingest-fast.yml")
            (sb.success if ok else sb.error)(msg)

    sb.markdown(
        "<div style='margin-top:2rem;padding-top:.8rem;border-top:1px solid var(--border)'>"
        "<span class='bt-meta'>Monitoring &amp; screening only — not investment "
        "advice. You supply the judgement on the science.<br>"
        "Data: yfinance · SEC EDGAR · ClinicalTrials.gov · openFDA · RSS</span></div>",
        unsafe_allow_html=True)
