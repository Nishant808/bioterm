"""Pro price chart: TradingView Lightweight Charts (v5, Apache-2.0, vendored in
static/) - candlesticks, volume, moving averages, an RSI pane, and markers for
signals and catalysts. Crosshair, scroll-zoom and drag-pan like a terminal.

The library is loaded from the app's own static route (static/ is served at
<app>/app/static/); if that isn't reachable the page falls back to jsDelivr.
The chart's HTML carries only the data, so a rerun doesn't resend the library.
"""
from __future__ import annotations

import json
import math

import pandas as pd
import streamlit.components.v1 as components

from _ui import (ACCENT, BG, BORDER, GRID, MUTED, NEG, POS, SMA_COLORS, TEXT_2, VIOLET, WARN)

LIB_LOCAL = "app/static/lightweight-charts.js"
LIB_CDN = ("https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.1/dist/"
           "lightweight-charts.standalone.production.js")


def _t(v, intraday: bool):
    ts = pd.Timestamp(v)
    if intraday:
        # naive New York wall time rendered as-is (the library draws UTC)
        return int(ts.tz_localize("UTC").timestamp()) if ts.tzinfo is None else int(ts.timestamp())
    return ts.strftime("%Y-%m-%d")


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, 4)


def payload(df: pd.DataFrame, *, intraday: bool = False, markers: list[dict] | None = None,
            show_rsi: bool = True) -> dict:
    d = df.dropna(subset=["close"]).sort_values("date")
    t = [_t(v, intraday) for v in d["date"]]
    candles = [{"time": tt, "open": _f(o) or _f(c), "high": _f(h) or _f(c),
                "low": _f(lo) or _f(c), "close": _f(c)}
               for tt, o, h, lo, c in zip(t, d["open"], d["high"], d["low"], d["close"])]
    vol = [{"time": tt, "value": _f(v) or 0,
            "color": ("rgba(63,185,107,.35)" if (_f(c) or 0) >= (_f(o) or 0)
                      else "rgba(229,72,77,.35)")}
           for tt, v, o, c in zip(t, d["volume"], d["open"], d["close"])]
    lines = {}
    for k in ("sma20", "sma50", "sma200"):
        if k in d:
            lines[k] = [{"time": tt, "value": _f(v)} for tt, v in zip(t, d[k]) if _f(v) is not None]
    rsi = [{"time": tt, "value": _f(v)} for tt, v in zip(t, d["rsi14"]) if _f(v) is not None] \
        if show_rsi and "rsi14" in d else []
    ok_times = set(t)
    mk = []
    for m in markers or []:
        tt = _t(m["time"], intraday)
        if not intraday and tt not in ok_times:
            # snap a marker to the next session (weekend / holiday dates)
            later = [x for x in t if x >= tt]
            if not later:
                continue
            tt = later[0]
        mk.append({**m, "time": tt})
    mk.sort(key=lambda m: str(m["time"]))
    return {"candles": candles, "volume": vol, "lines": lines, "rsi": rsi, "markers": mk,
            "intraday": intraday}


def pro_chart(df: pd.DataFrame, *, intraday: bool = False, markers: list[dict] | None = None,
              height: int = 520, show_rsi: bool = True) -> None:
    data = payload(df, intraday=intraday, markers=markers, show_rsi=show_rsi)
    colors = {"sma20": SMA_COLORS.get("sma20", ACCENT), "sma50": SMA_COLORS.get("sma50", VIOLET),
              "sma200": SMA_COLORS.get("sma200", TEXT_2)}
    html = f"""
<div id="c" style="position:absolute;inset:0"></div>
<div id="legend" style="position:absolute;left:10px;top:6px;z-index:3;font:12px Inter,
system-ui,sans-serif;color:{TEXT_2};pointer-events:none"></div>
<script>
const D = {json.dumps(data, separators=(",", ":"))};
const C = {json.dumps(colors)};
function draw() {{
  const L = window.LightweightCharts;
  const el = document.getElementById('c');
  const chart = L.createChart(el, {{
    autoSize: true,
    layout: {{ background: {{ type: 'solid', color: '{BG}' }}, textColor: '{MUTED}',
               fontFamily: 'Inter, system-ui, sans-serif', fontSize: 11,
               panes: {{ separatorColor: '{BORDER}', separatorHoverColor: '{BORDER}' }} }},
    grid: {{ vertLines: {{ color: '{GRID}' }}, horzLines: {{ color: '{GRID}' }} }},
    rightPriceScale: {{ borderColor: '{BORDER}' }},
    timeScale: {{ borderColor: '{BORDER}', timeVisible: D.intraday, secondsVisible: false,
                  rightOffset: 4 }},
    crosshair: {{ mode: 0 }},
  }});
  const candles = chart.addSeries(L.CandlestickSeries, {{
    upColor: '{POS}', downColor: '{NEG}', borderVisible: false,
    wickUpColor: '{POS}', wickDownColor: '{NEG}' }});
  candles.setData(D.candles);
  const vol = chart.addSeries(L.HistogramSeries, {{ priceScaleId: 'vol',
    priceFormat: {{ type: 'volume' }}, lastValueVisible: false, priceLineVisible: false }});
  vol.priceScale().applyOptions({{ scaleMargins: {{ top: 0.82, bottom: 0 }} }});
  vol.setData(D.volume);
  for (const [k, pts] of Object.entries(D.lines)) {{
    if (!pts.length) continue;
    const s = chart.addSeries(L.LineSeries, {{ color: C[k], lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }});
    s.setData(pts);
  }}
  if (D.markers.length) L.createSeriesMarkers(candles, D.markers);
  if (D.rsi.length) {{
    const r = chart.addSeries(L.LineSeries, {{ color: '{WARN}', lineWidth: 1,
      priceLineVisible: false }}, 1);
    r.setData(D.rsi);
    r.createPriceLine({{ price: 70, color: '{BORDER}', lineStyle: 2, axisLabelVisible: false }});
    r.createPriceLine({{ price: 30, color: '{BORDER}', lineStyle: 2, axisLabelVisible: false }});
    const panes = chart.panes();
    if (panes.length > 1) panes[1].setHeight(Math.round({height} * 0.2));
  }}
  chart.timeScale().fitContent();
  const legend = document.getElementById('legend');
  chart.subscribeCrosshairMove(p => {{
    const b = p && p.seriesData ? p.seriesData.get(candles) : null;
    legend.textContent = b ? `O ${{b.open}}  H ${{b.high}}  L ${{b.low}}  C ${{b.close}}` : '';
  }});
}}
function load(src, next) {{
  const s = document.createElement('script');
  s.src = src; s.onload = draw; s.onerror = next; document.head.appendChild(s);
}}
let root = '/';
try {{ root = window.parent.location.pathname.replace(/[^/]*$/, ''); }} catch (e) {{}}
load(root + '{LIB_LOCAL}', () => load('{LIB_CDN}', () => {{
  document.getElementById('legend').textContent = 'Chart library unavailable';
}}));
</script>"""
    components.html(f"<body style='margin:0;background:{BG}'>{html}</body>", height=height)


def signal_markers(signals: pd.DataFrame, catalysts: pd.DataFrame | None = None) -> list[dict]:
    """Markers: signal-label changes (arrows) and catalyst dates (dots)."""
    out = []
    if signals is not None and not signals.empty:
        s = signals.sort_values("asof")
        prev = None
        for r in s.itertuples():
            lab = r.label
            if lab != prev and lab in ("BUY", "STRONG BUY", "SELL", "STRONG SELL"):
                buy = "BUY" in lab
                out.append({"time": r.asof, "position": "belowBar" if buy else "aboveBar",
                            "color": POS if buy else NEG,
                            "shape": "arrowUp" if buy else "arrowDown",
                            "text": lab.title()})
            prev = lab
    if catalysts is not None and not catalysts.empty:
        for r in catalysts.itertuples():
            out.append({"time": r.date, "position": "aboveBar", "color": WARN,
                        "shape": "circle", "text": str(r.type).replace("_", " ")[:18]})
    return out
