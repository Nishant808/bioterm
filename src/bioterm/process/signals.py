"""Signal engine: early BUY / SELL detection -> ``signals`` + ``signal_scores``.

Where the Focus Score ranks how much *attention* a name deserves, this module
says which *direction* the open evidence leans, and why. It is a panel of small,
transparent detectors - each one a rule over data BioTerm already stores:

  price/volume  52-week breakouts, SMA crosses, RSI reversals, Chaikin money
                flow (accumulation / distribution), volume surges, crash days,
                cross-sectional relative strength
  pipeline      a binary readout ahead with the stock not yet extended (buy the
                setup), a run-up into one (sell-the-news risk), a new Phase 3
  capital       dilution filings, runway crunch, going-concern language
  people        insider cluster buying / heavy selling (Form 4), specialist
                funds initiating / exiting (13F)
  flow          unusual call or put activity, short-volume pressure, squeeze setups
  news          positive / negative biotech events, FDA designations, tone shifts
                (FinBERT when installed, VADER otherwise)

Each firing detector has a strength in [0, 1]. Strengths are adjusted for the
biotech tape (XBI trend regime), the user's watchlist conviction (buy side only)
and - when a recent event study exists - each price detector's *measured* edge.
Per ticker:  bull = 1 - prod(1 - s_buy),  bear = 1 - prod(1 - s_sell),
net = bull - bear, mapped to STRONG BUY ... STRONG SELL (thresholds in settings).

History is kept (``signals.keep_days``) so the calls can be scored against what
the stock did next - see process/backtest.py. Screening output, not advice.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ..config import load_settings
from ..db import bulk_upsert, get_engine, read_sql, signal_scores, signals
from .technicals import rsi

log = logging.getLogger("bioterm.process.signals")

LABELS = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]
BINARY_TYPES = {"phase3_readout", "pdufa", "adcom", "fda_action"}
CLINICAL_TYPES = BINARY_TYPES | {"phase2_readout", "phase1_readout", "data_presentation",
                                 "trial_completion"}
DESIGNATION_TAGS = {"breakthrough therapy", "fast track", "priority review", "orphan drug",
                    "accelerated approval"}
EDGE_LOOKBACK = 5   # trading days an edge-type technical event stays live

# ================================================================ price features
def price_features(df: pd.DataFrame) -> pd.DataFrame:
    """Daily indicator frame for one ticker (date-sorted OHLCV in). Pure - the
    live engine and the backtest compute signals from the same function."""
    df = df.sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    high = pd.to_numeric(df.get("high", close), errors="coerce").astype(float).fillna(close)
    low = pd.to_numeric(df.get("low", close), errors="coerce").astype(float).fillna(close)
    vol = pd.to_numeric(df.get("volume", 0), errors="coerce").astype(float).fillna(0.0)
    f = pd.DataFrame({"date": pd.to_datetime(df["date"]), "close": close})
    f["ret_1"] = close.pct_change()
    for n in (5, 21, 63, 126, 252):
        f[f"ret_{n}"] = close.pct_change(n)
    f["sma20"] = close.rolling(20).mean()
    f["sma50"] = close.rolling(50).mean()
    f["sma200"] = close.rolling(200).mean()
    f["rsi14"] = rsi(close)
    vmean = vol.rolling(20).mean()
    vstd = vol.rolling(20).std().replace(0.0, np.nan)
    f["vol_z20"] = ((vol - vmean) / vstd).fillna(0.0)
    f["hi_252_prev"] = close.shift(1).rolling(252, min_periods=120).max()
    f["lo_252_prev"] = close.shift(1).rolling(252, min_periods=120).min()
    rng = (f["hi_252_prev"] - f["lo_252_prev"]).replace(0.0, np.nan)
    f["pct_52w"] = ((close - f["lo_252_prev"]) / rng).clip(0, 1)
    f["bb_upper"] = f["sma20"] + 2 * close.rolling(20).std()
    span = (high - low).replace(0.0, np.nan)
    mfm = (((close - low) - (high - close)) / span).fillna(0.0)
    f["cmf20"] = (mfm * vol).rolling(20).sum() / vol.rolling(20).sum().replace(0.0, np.nan)
    f["rs_raw"] = 0.5 * f["ret_63"] + 0.3 * f["ret_126"] + 0.2 * f["ret_252"].fillna(f["ret_126"])
    return f


def add_rs_rating(feats: dict[str, pd.DataFrame]) -> None:
    """Cross-sectional relative strength (0-100 percentile of rs_raw per date),
    written into each frame in place."""
    if not feats:
        return
    wide = pd.concat({tk: f.set_index("date")["rs_raw"] for tk, f in feats.items()}, axis=1)
    pct = wide.rank(axis=1, pct=True) * 100
    for tk, f in feats.items():
        f["rs"] = f["date"].map(pct[tk]).astype(float)


# ================================================================ technical detectors
def _p(cfg: dict, code: str, key: str, default):
    return (cfg.get(code) or {}).get(key, default)


def technical_events(f: pd.DataFrame, det: dict | None = None) -> pd.DataFrame:
    """Every technical detector over a feature frame, vectorised.

    Returns one row per (date, code) where the detector fired, with side,
    base strength, kind ('edge' = an event on that day, 'state' = a condition
    that holds) and a short human title. Edges fire on the day the condition
    turns true; states on every day it holds.
    """
    det = det or {}
    c, prev = f, f.shift(1)
    specs: list[tuple[str, str, str, pd.Series]] = []

    def add(code, side, kind, mask):
        specs.append((code, side, kind, mask.fillna(False).astype(bool)))

    mv = _p(det, "breakout_52w", "min_vol_z", 1.0)
    add("breakout_52w", "BUY", "edge",
        (c["close"] > c["hi_252_prev"]) & (prev["close"] <= prev["hi_252_prev"])
        & (c["vol_z20"] >= mv))
    add("golden_cross", "BUY", "edge", (c["sma50"] > c["sma200"]) & (prev["sma50"] <= prev["sma200"]))
    add("death_cross", "SELL", "edge", (c["sma50"] < c["sma200"]) & (prev["sma50"] >= prev["sma200"]))
    add("reclaim_sma200", "BUY", "edge",
        (c["close"] > c["sma200"]) & (prev["close"] <= prev["sma200"])
        & (c["vol_z20"] >= _p(det, "reclaim_sma200", "min_vol_z", 0.5)))
    add("breakdown_sma200", "SELL", "edge",
        (c["close"] < c["sma200"]) & (prev["close"] >= prev["sma200"])
        & (c["vol_z20"] >= _p(det, "breakdown_sma200", "min_vol_z", 0.5)))
    add("rsi_oversold_reversal", "BUY", "edge", (c["rsi14"] > 30) & (prev["rsi14"] <= 30))
    add("volume_surge_up", "BUY", "edge",
        (c["vol_z20"] >= _p(det, "volume_surge_up", "min_vol_z", 2.5))
        & (c["ret_1"] >= _p(det, "volume_surge_up", "min_ret", 0.05)))
    add("volume_surge_down", "SELL", "edge",
        (c["vol_z20"] >= _p(det, "volume_surge_down", "min_vol_z", 2.5))
        & (c["ret_1"] <= _p(det, "volume_surge_down", "min_ret", -0.05)))
    add("crash_day", "SELL", "edge", c["ret_1"] <= _p(det, "crash_day", "max_ret", -0.20))
    add("overbought_exhaustion", "SELL", "state",
        (c["rsi14"] >= _p(det, "overbought_exhaustion", "rsi", 80))
        & (c["close"] > c["bb_upper"])
        & (c["ret_21"] >= _p(det, "overbought_exhaustion", "min_ret_21", 0.35)))
    add("accumulation", "BUY", "state",
        (c["cmf20"] >= _p(det, "accumulation", "cmf", 0.20)) & c["ret_21"].between(-0.05, 0.15))
    add("distribution", "SELL", "state",
        (c["cmf20"] <= _p(det, "distribution", "cmf", -0.20)) & (c["pct_52w"] >= 0.6))
    if "rs" in c:
        add("relative_strength_leader", "BUY", "state",
            (c["rs"] >= _p(det, "relative_strength_leader", "min_rs", 90))
            & (c["close"] > c["sma50"]) & (c["sma50"] > c["sma200"]))
        add("relative_strength_laggard", "SELL", "state",
            (c["rs"] <= _p(det, "relative_strength_laggard", "max_rs", 10))
            & (c["close"] < c["sma50"]) & (c["sma50"] < c["sma200"]))

    frames = []
    for code, side, kind, mask in specs:
        if not mask.any():
            continue
        rows = f.loc[mask, ["date", "close", "ret_1", "ret_21", "vol_z20", "rsi14", "cmf20",
                            "sma50", "sma200", "hi_252_prev"] + (["rs"] if "rs" in f else [])]
        rows = rows.assign(code=code, side=side, kind=kind,
                           strength=float(_p(det, code, "strength", 0.35)),
                           pos=np.flatnonzero(mask.to_numpy()))
        frames.append(rows)
    if not frames:
        return pd.DataFrame(columns=["date", "code", "side", "kind", "strength", "pos"])
    ev = pd.concat(frames, ignore_index=True)
    ev["title"] = [_tech_title(r) for r in ev.itertuples()]
    return ev.sort_values(["date", "code"]).reset_index(drop=True)


def _fmt_pct(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{x * 100:+.0f}%"


def _tech_title(r) -> str:
    code = r.code
    if code == "breakout_52w":
        return f"New 52-week closing high on {r.vol_z20:.1f}σ volume"
    if code == "golden_cross":
        return "50-day average crossed above the 200-day (golden cross)"
    if code == "death_cross":
        return "50-day average crossed below the 200-day (death cross)"
    if code == "reclaim_sma200":
        return f"Reclaimed the 200-day average on {r.vol_z20:.1f}σ volume"
    if code == "breakdown_sma200":
        return f"Broke below the 200-day average on {r.vol_z20:.1f}σ volume"
    if code == "rsi_oversold_reversal":
        return f"RSI turned up out of oversold ({r.rsi14:.0f})"
    if code == "volume_surge_up":
        return f"{_fmt_pct(r.ret_1)} day on {r.vol_z20:.1f}σ volume (buyers in size)"
    if code == "volume_surge_down":
        return f"{_fmt_pct(r.ret_1)} day on {r.vol_z20:.1f}σ volume (sellers in size)"
    if code == "crash_day":
        return f"{_fmt_pct(r.ret_1)} in one session - post-event drift tends to persist"
    if code == "overbought_exhaustion":
        return f"Stretched: RSI {r.rsi14:.0f}, above the upper band, {_fmt_pct(r.ret_21)} in a month"
    if code == "accumulation":
        return f"Quiet accumulation: money flow {r.cmf20:+.2f} with price flat ({_fmt_pct(r.ret_21)} 1M)"
    if code == "distribution":
        return f"Distribution near highs: money flow {r.cmf20:+.2f}"
    if code == "relative_strength_leader":
        return f"Relative-strength leader (RS {getattr(r, 'rs', 0):.0f}) in an uptrend"
    if code == "relative_strength_laggard":
        return f"Relative-strength laggard (RS {getattr(r, 'rs', 0):.0f}) in a downtrend"
    return code.replace("_", " ")


def live_technical(ev: pd.DataFrame, n_rows: int) -> list[dict]:
    """Technical detectors live *today*: edges from the last few sessions
    (fading with age), states holding on the last row."""
    out: list[dict] = []
    if ev.empty:
        return out
    last = n_rows - 1
    for code, g in ev.groupby("code"):
        r = g.iloc[-1]
        age = last - int(r["pos"])
        if r["kind"] == "state" and age != 0:
            continue
        if r["kind"] == "edge" and age >= EDGE_LOOKBACK:
            continue
        decay = 1.0 if r["kind"] == "state" else 1.0 - 0.08 * age
        detail = {k: (None if pd.isna(r.get(k)) else round(float(r[k]), 4))
                  for k in ("close", "ret_1", "ret_21", "vol_z20", "rsi14", "cmf20", "rs")
                  if k in r}
        detail["date"] = str(pd.Timestamp(r["date"]).date())
        if age:
            detail["sessions_ago"] = age
        out.append({"code": code, "side": r["side"], "strength": float(r["strength"]) * decay,
                    "title": r["title"] + (f" · {age}d ago" if age else ""),
                    "detail": detail, "family": "technical"})
    return out


# ================================================================ context loading
def _load_prices(days: int = 430) -> pd.DataFrame:
    cut = (date.today() - timedelta(days=days)).isoformat()
    df = read_sql("SELECT ticker, date, open, high, low, close, volume FROM prices "
                  "WHERE date >= :c", {"c": cut})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _safe(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return read_sql(sql, params)
    except Exception:  # noqa: BLE001 - a table a fresh database hasn't populated yet
        return pd.DataFrame()


def regime_of(feat: pd.DataFrame | None) -> str:
    if feat is None or feat.empty:
        return "neutral"
    r = feat.iloc[-1]
    if pd.isna(r["sma200"]):
        return "neutral"
    if r["close"] > r["sma200"] and r["sma50"] > r["sma200"]:
        return "risk_on"
    if r["close"] < r["sma200"] and r["sma50"] < r["sma200"]:
        return "risk_off"
    return "neutral"


def calibration(min_n: int = 50, floor_buy: float = 0.5, floor_sell: float = 0.75) -> dict[str, float]:
    """Per technical detector: a strength multiplier from its measured edge in
    the most recent event study (t-stat of 3-month excess return, in the
    detector's own direction), capped at 1.3 - events overlap in time, so the
    t-stats run hot and are only trusted gently. Empty until one exists.

    The floor is asymmetric because the backtest universe is today's index
    (survivorship bias): it flatters buy detectors and penalises sell detectors
    (the losers that were delisted are missing). A buy detector that still
    tests negative has genuinely failed and may be cut to ``floor_buy``; a sell
    detector is never cut below ``floor_sell`` on this biased evidence."""
    df = _safe("SELECT results FROM backtests WHERE kind = 'events' ORDER BY ts DESC LIMIT 1")
    if df.empty:
        return {}
    try:
        by = json.loads(df.iloc[0]["results"]).get("by_code", {})
    except (TypeError, ValueError):
        return {}
    out = {}
    for code, s in by.items():
        n, t = s.get("n", 0), s.get("t_63")
        if n and n >= min_n and t is not None and not math.isnan(t):
            buy = s.get("side") == "BUY"
            directional = t if buy else -t
            out[code] = float(min(1.3, max(floor_buy if buy else floor_sell,
                                           1.0 + 0.1 * directional)))
    return out


# ================================================================ event detectors
def _days_to(d, today: date) -> int:
    return (pd.Timestamp(d).date() - today).days


def event_detectors(tk: str, ctx: dict, feat: pd.DataFrame | None, det: dict,
                    today: date) -> list[dict]:
    """Every non-price detector for one ticker. ``ctx`` holds pre-grouped frames."""
    out: list[dict] = []
    last = feat.iloc[-1] if feat is not None and not feat.empty else None

    def fire(code, side, strength, title, detail=None, family="event"):
        out.append({"code": code, "side": side, "strength": float(max(0.0, min(0.95, strength))),
                    "title": title, "detail": detail or {}, "family": family})

    fund = ctx["fund"].get(tk, {})
    runway = fund.get("runway_quarters")
    runway = None if runway is None or pd.isna(runway) else float(runway)
    mcap = fund.get("market_cap")

    # ---------------------------------------------------------- pipeline / catalysts
    cats = ctx["cats"].get(tk)
    if cats is not None and not cats.empty:
        cats = cats.assign(days=[_days_to(d, today) for d in cats["date"]])
        tw = ctx["type_weights"]
        conf = {"high": 1.0, "medium": 0.8, "low": 0.55}
        p = det.get("pre_catalyst_setup", {})
        lo, hi = int(p.get("min_days", 10)), int(p.get("max_days", 120))
        ahead = cats[cats["type"].isin(CLINICAL_TYPES) & cats["days"].between(lo, hi)]
        if not ahead.empty and last is not None:
            ahead = ahead.assign(w=[float(tw.get(t, 0.4)) * conf.get(c, 0.6)
                                    * (1.0 - 0.45 * (d - lo) / max(1, hi - lo))
                                    for t, c, d in zip(ahead["type"], ahead["confidence"],
                                                       ahead["days"])])
            best = ahead.sort_values("w", ascending=False).iloc[0]
            extended = (last["ret_21"] is not None and not pd.isna(last["ret_21"])
                        and last["ret_21"] > float(p.get("max_ret_21", 0.30))) \
                or float(last["rsi14"]) > float(p.get("max_rsi", 72))
            funded = runway is None or runway >= 4
            if not extended and funded:
                size = _size_factor(mcap)
                fire("pre_catalyst_setup", "BUY", float(p.get("strength", 0.6)) * best["w"] * size,
                     f"{_type_label(best['type'])} in {int(best['days'])} days and the stock "
                     f"isn't extended yet", {"catalyst": str(best["title"])[:140],
                                             "date": str(pd.Timestamp(best["date"]).date()),
                                             "type": best["type"], "size_factor": round(size, 2)})
        q = det.get("sell_the_news_risk", {})
        near = cats[cats["type"].isin(BINARY_TYPES) & cats["days"].between(-3, int(q.get("max_days", 14)))]
        if not near.empty and last is not None and not pd.isna(last["ret_63"]) \
                and last["ret_63"] >= float(q.get("min_ret_63", 0.40)):
            c0 = near.sort_values("days").iloc[0]
            fire("sell_the_news_risk", "SELL",
                 float(q.get("strength", 0.45)) * min(1.3, 0.8 + last["ret_63"]),
                 f"Up {_fmt_pct(last['ret_63'])} in 3 months into a binary "
                 f"{_type_label(c0['type']).lower()} {'in ' + str(int(c0['days'])) + ' days' if c0['days'] >= 0 else 'just passed'}",
                 {"catalyst": str(c0["title"])[:140], "ret_63": round(float(last["ret_63"]), 3)})
        recent = cats[cats["type"].isin(CLINICAL_TYPES) & cats["days"].between(-60, -1)]
        upcoming = cats[cats["type"].isin(CLINICAL_TYPES) & cats["days"].between(0, 183)]
        if not recent.empty and upcoming.empty:
            fire("catalyst_vacuum", "SELL", float(det.get("catalyst_vacuum", {}).get("strength", 0.15)),
                 "Readout just passed and nothing dated in the next six months")

    trials = ctx["new_p3"].get(tk)
    if trials is not None and not trials.empty:
        t0 = trials.sort_values("start_date", ascending=False).iloc[0]
        fire("pipeline_advance", "BUY", float(det.get("pipeline_advance", {}).get("strength", 0.3)),
             f"New {t0['phase']} trial started {pd.Timestamp(t0['start_date']):%b %d}",
             {"nct_id": t0["nct_id"], "title": str(t0["title"])[:140]})

    tc = ctx.get("trial_changes", {}).get(tk)
    if tc is not None and not tc.empty:
        late = tc["phase"].fillna("").str.contains("P2|P3")
        now_utc = pd.Timestamp.now(tz="UTC")
        p = det.get("trial_halted", {})
        stop = tc[late & tc["kind"].isin(["suspended", "terminated", "withdrawn"])
                  & (tc["detected_at"] >= now_utc - pd.Timedelta(days=int(p.get("days", 30))))]
        if not stop.empty:
            r0 = stop.iloc[0]
            fire("trial_halted", "SELL", float(p.get("strength", 0.6)),
                 f"{r0['phase']} trial {r0['nct_id']} {r0['kind']} ({r0['old']} -> {r0['new']})",
                 {"nct_id": r0["nct_id"], "kind": r0["kind"]})
        p = det.get("readout_delay", {})
        slip = tc[late & (tc["kind"] == "date_slip")
                  & (tc["days"].fillna(0) >= float(p.get("min_days", 90)))
                  & (tc["detected_at"] >= now_utc - pd.Timedelta(days=int(p.get("days", 30))))]
        if not slip.empty:
            r0 = slip.sort_values("days", ascending=False).iloc[0]
            fire("readout_delay", "SELL",
                 float(p.get("strength", 0.35)) * min(1.3, 0.7 + float(r0["days"]) / 365),
                 f"{r0['phase']} readout pushed back {int(r0['days'])} days ({r0['old']} -> "
                 f"{r0['new']}) on {r0['nct_id']}", {"nct_id": r0["nct_id"],
                                                     "days": float(r0["days"])})
        p = det.get("enrollment_complete", {})
        enr = tc[late & (tc["kind"] == "enrollment_complete")
                 & (tc["detected_at"] >= now_utc - pd.Timedelta(days=int(p.get("days", 45))))]
        if not enr.empty:
            r0 = enr.iloc[0]
            fire("enrollment_complete", "BUY", float(p.get("strength", 0.3)),
                 f"{r0['phase']} trial {r0['nct_id']} finished enrolling - the readout clock "
                 f"is running", {"nct_id": r0["nct_id"]})

    # ---------------------------------------------------------- capital
    fl = ctx["filings"].get(tk)
    d = det.get("dilution_filing", {})
    if fl is not None and not fl.empty:
        recent = fl[fl["filed_date"] >= pd.Timestamp(today - timedelta(days=int(d.get("days", 30))))]
        if not recent.empty:
            sev = {"424B5": 1.0, "424B4": 1.0, "424B3": 0.7, "S-1": 0.85, "S-3": 0.6,
                   "S-3ASR": 0.6}
            f0 = recent.assign(sev=recent["form"].map(sev).fillna(0.5)).sort_values("sev").iloc[-1]
            fire("dilution_filing", "SELL", float(d.get("strength", 0.5)) * f0["sev"],
                 f"{f0['form']} filed {pd.Timestamp(f0['filed_date']):%b %d} - an offering "
                 f"{'priced' if f0['form'] == '424B5' else 'is possible'}",
                 {"form": f0["form"], "url": f0.get("url")}, family="capital")
    rc = det.get("runway_crunch", {})
    if runway is not None and runway < float(rc.get("max_quarters", 3.0)):
        raised = fl is not None and not fl.empty and (
            fl["filed_date"] >= pd.Timestamp(today - timedelta(days=90))).any()
        if not raised:
            fire("runway_crunch", "SELL",
                 float(rc.get("strength", 0.4)) * (1 - runway / (2 * float(rc.get("max_quarters", 3.0)))),
                 f"{runway:.1f} quarters of cash and no raise yet - financing likely ahead",
                 {"runway_quarters": runway}, family="capital")
    if tk in ctx["going_concern"]:
        fire("going_concern", "SELL", float(det.get("going_concern", {}).get("strength", 0.6)),
             "Latest 10-K/10-Q carries going-concern doubt", family="capital")

    # ---------------------------------------------------------- insiders
    ins = ctx["insiders"].get(tk)
    if ins is not None and not ins.empty:
        b = ins[ins["code"] == "P"]
        s = ins[ins["code"] == "S"]
        p = det.get("insider_cluster_buy", {})
        nb, vb = int(b["owner"].nunique()), float(b["value"].sum())
        if nb >= int(p.get("min_buyers", 2)) or vb >= float(p.get("min_value", 250000)):
            fire("insider_cluster_buy", "BUY",
                 float(p.get("strength", 0.55)) * min(1.2, 0.6 + 0.15 * nb + 0.3 * math.tanh(vb / 2e6)),
                 f"{nb} insider{'s' if nb != 1 else ''} bought ${vb / 1e6:.2f}M on the open market (60 days)",
                 {"buyers": nb, "value": round(vb)}, family="people")
        q = det.get("insider_heavy_selling", {})
        ns, vs = int(s["owner"].nunique()), float(-s["value"].sum())
        if ns >= int(q.get("min_sellers", 3)) and vs >= float(q.get("min_value", 2e6)):
            fire("insider_heavy_selling", "SELL",
                 float(q.get("strength", 0.3)) * min(1.3, 0.8 + 0.1 * ns),
                 f"{ns} insiders sold ${vs / 1e6:.1f}M on the open market (60 days)",
                 {"sellers": ns, "value": round(vs)}, family="people")

    ac = ctx.get("activist", {}).get(tk)
    if ac is not None and not ac.empty:
        p = det.get("activist_stake", {})
        r0 = ac.sort_values("filed_date").iloc[-1]
        fire("activist_stake", "BUY", float(p.get("strength", 0.3)),
             f"Schedule 13D filed {pd.Timestamp(r0['filed_date']):%b %d} - a holder with 5%+ "
             f"and intent to influence", {"form": r0["form"], "url": r0.get("url")},
             family="people")

    # ---------------------------------------------------------- specialist funds (13F)
    sm = ctx["smart"].get(tk)
    if sm is not None:
        buying = int(sm["new"]) + int(sm["added"])
        selling = int(sm["exited"]) + int(sm["trimmed"])
        # a 13F is news the day it's filed and history a quarter later
        filed = pd.to_datetime(sm.get("filed"), errors="coerce")
        age = (pd.Timestamp(today) - filed).days if pd.notna(filed) else 90
        fresh = min(1.0, max(0.35, 1.0 - max(0, age - 14) / 150))
        p = det.get("specialist_accumulation", {})
        if buying >= int(p.get("min_funds", 2)) and buying > selling:
            fire("specialist_accumulation", "BUY",
                 fresh * float(p.get("strength", 0.5))
                 * min(1.3, 0.7 + 0.15 * buying + 0.1 * int(sm["new"])),
                 f"{buying} specialist funds initiated or added ({', '.join(sm['funds_buying'][:4])})",
                 {"new": int(sm["new"]), "added": int(sm["added"]), "period": str(sm["period"])[:10],
                  "filed_days_ago": age},
                 family="people")
        q = det.get("specialist_exit", {})
        if selling >= int(q.get("min_funds", 2)) and selling > buying:
            fire("specialist_exit", "SELL",
                 fresh * float(q.get("strength", 0.45))
                 * min(1.3, 0.7 + 0.15 * selling + 0.1 * int(sm["exited"])),
                 f"{selling} specialist funds cut or exited ({', '.join(sm['funds_selling'][:4])})",
                 {"exited": int(sm["exited"]), "trimmed": int(sm["trimmed"])}, family="people")

    # ---------------------------------------------------------- news
    nw = ctx["news"].get(tk)
    if nw is not None and not nw.empty:
        now = pd.Timestamp.now(tz="UTC")
        p = det.get("positive_event", {})
        pos = nw[(nw["published"] >= now - pd.Timedelta(days=int(p.get("days", 3))))
                 & (nw["event_score"] >= float(p.get("min_event", 0.9)))]
        if not pos.empty:
            top = pos.sort_values("event_score", ascending=False).iloc[0]
            fire("positive_event", "BUY", float(p.get("strength", 0.5)) * min(1.2, top["event_score"] / 1.5 + 0.4),
                 f"Positive catalyst headline: {str(top['title'])[:110]}",
                 {"tags": top["event_tags"], "url": top["url"]}, family="news")
        q = det.get("negative_event", {})
        neg = nw[(nw["published"] >= now - pd.Timedelta(days=int(q.get("days", 5))))
                 & (nw["event_score"] <= float(q.get("max_event", -0.8)))]
        if not neg.empty:
            top = neg.sort_values("event_score").iloc[0]
            fire("negative_event", "SELL", float(q.get("strength", 0.6)) * min(1.2, -top["event_score"] / 1.5 + 0.4),
                 f"Negative catalyst headline: {str(top['title'])[:110]}",
                 {"tags": top["event_tags"], "url": top["url"]}, family="news")
        r = det.get("regulatory_designation", {})
        recent = nw[nw["published"] >= now - pd.Timedelta(days=int(r.get("days", 14)))]
        des = [t for tags in recent["event_tags"].fillna("") for t in tags.split(",")
               if t in DESIGNATION_TAGS]
        if des:
            fire("regulatory_designation", "BUY", float(r.get("strength", 0.4)),
                 f"FDA {sorted(set(des))[0]} headline in the last {int(r.get('days', 14))} days",
                 {"tags": sorted(set(des))}, family="news")
        s = det.get("sentiment_inflection", {})
        w7 = nw[nw["published"] >= now - pd.Timedelta(days=7)]
        base = nw[(nw["published"] < now - pd.Timedelta(days=7))
                  & (nw["published"] >= now - pd.Timedelta(days=28))]
        if len(w7) >= int(s.get("min_headlines", 3)) and len(base) >= 3:
            delta = float(w7["sentiment"].mean() - base["sentiment"].mean())
            if abs(delta) >= float(s.get("min_delta", 0.3)):
                side = "BUY" if delta > 0 else "SELL"
                fire("sentiment_inflection", side, float(s.get("strength", 0.3)) * min(1.3, abs(delta) / 0.3 * 0.8),
                     f"Headline tone {'improved' if delta > 0 else 'deteriorated'} by {delta:+.2f} "
                     f"vs the prior three weeks ({len(w7)} headlines this week)",
                     {"delta": round(delta, 3), "n_7d": int(len(w7))}, family="news")

    ev = ctx.get("ai_events", {}).get(tk)
    if ev is not None and not ev.empty:
        codes = {o["code"] for o in out}
        good = {"topline_data", "interim_data", "fda_approval", "adcom_outcome",
                "partnership_or_licensing", "m_and_a"}
        bad = {"topline_data", "interim_data", "fda_crl", "trial_halt_or_hold",
               "trial_discontinued", "adcom_outcome", "financing"}
        p = det.get("ai_event_positive", {})
        pos = ev[(ev["outcome"] == "positive") & ev["event_type"].isin(good)]
        if not pos.empty and "positive_event" not in codes:
            r0 = pos.sort_values("confidence", ascending=False).iloc[0]
            fire("ai_event_positive", "BUY", float(p.get("strength", 0.45)) * float(r0["confidence"]),
                 f"AI-read {str(r0['event_type']).replace('_', ' ')}: {str(r0['summary'])[:110]}",
                 {"event_type": r0["event_type"], "id": r0["id"]}, family="news")
        q = det.get("ai_event_negative", {})
        neg = ev[(ev["outcome"] == "negative") & ev["event_type"].isin(bad)]
        if not neg.empty and "negative_event" not in codes:
            r0 = neg.sort_values("confidence", ascending=False).iloc[0]
            fire("ai_event_negative", "SELL", float(q.get("strength", 0.5)) * float(r0["confidence"]),
                 f"AI-read {str(r0['event_type']).replace('_', ' ')}: {str(r0['summary'])[:110]}",
                 {"event_type": r0["event_type"], "id": r0["id"]}, family="news")

    # ---------------------------------------------------------- options / shorts
    op = ctx["options"].get(tk)
    if op is not None:
        vol_oi, pcv = op.get("vol_oi_ratio"), op.get("pc_volume_ratio")
        cv, pv = op.get("call_volume") or 0, op.get("put_volume") or 0
        p = det.get("unusual_call_activity", {})
        if vol_oi and pcv is not None and vol_oi >= float(p.get("min_vol_oi", 1.5)) \
                and pcv <= float(p.get("max_pc", 0.5)) and cv >= 500:
            fire("unusual_call_activity", "BUY", float(p.get("strength", 0.35)) * min(1.3, vol_oi / 2),
                 f"Call volume {cv:,.0f} ({vol_oi:.1f}× open interest, put/call {pcv:.2f})",
                 {"vol_oi": round(vol_oi, 2), "pc": round(pcv, 2)}, family="flow")
        q = det.get("unusual_put_activity", {})
        if vol_oi and pcv is not None and vol_oi >= float(q.get("min_vol_oi", 1.5)) \
                and pcv >= float(q.get("min_pc", 2.0)) and pv >= 500:
            fire("unusual_put_activity", "SELL", float(q.get("strength", 0.35)) * min(1.3, vol_oi / 2),
                 f"Put volume {pv:,.0f} ({vol_oi:.1f}× open interest, put/call {pcv:.2f})",
                 {"vol_oi": round(vol_oi, 2), "pc": round(pcv, 2)}, family="flow")
    sh = ctx["short"].get(tk)
    spf = fund.get("short_percent_float")
    p = det.get("short_squeeze_setup", {})
    if spf is not None and not pd.isna(spf) and spf >= float(p.get("min_short_float", 0.2)) \
            and last is not None and last["close"] > last["sma20"] and (last["ret_5"] or 0) > 0 \
            and (sh is None or sh["delta"] <= 0):
        fire("short_squeeze_setup", "BUY", float(p.get("strength", 0.35)) * min(1.3, spf / 0.3),
             f"{spf * 100:.0f}% of float short with price turning up and shorts not adding",
             {"short_float": round(float(spf), 3),
              "days_to_cover": fund.get("short_ratio")}, family="flow")
    q = det.get("short_pressure_rising", {})
    if sh is not None and sh["ratio_5d"] >= float(q.get("min_ratio", 0.55)) \
            and sh["delta"] >= float(q.get("min_delta", 0.08)):
        fire("short_pressure_rising", "SELL", float(q.get("strength", 0.3)) * min(1.3, sh["delta"] / 0.1),
             f"Short share of volume {sh['ratio_5d'] * 100:.0f}% this week vs "
             f"{sh['ratio_20d'] * 100:.0f}% over 20 days", {k: round(float(sh[k]), 3)
                                                          for k in ("ratio_5d", "ratio_20d", "delta")},
             family="flow")
    return out


def _size_factor(mcap) -> float:
    if mcap is None or pd.isna(mcap) or mcap <= 0:
        return 0.9
    return float(max(0.45, min(1.0, 1.15 - 0.28 * math.log10(max(mcap / 1e9, 1.0)))))


def _type_label(t: str) -> str:
    return {"phase3_readout": "Phase 3 readout", "phase2_readout": "Phase 2 readout",
            "phase1_readout": "Phase 1 readout", "pdufa": "PDUFA date", "adcom": "AdCom",
            "fda_action": "FDA decision", "data_presentation": "Data presentation",
            "trial_completion": "Trial completion"}.get(t, str(t).replace("_", " "))


# ================================================================ composition
def composite(fired: list[dict], regime: str, conv_mult: float, calib: dict[str, float],
              cfg) -> tuple[list[dict], dict]:
    """Adjust strengths and fold them into bull / bear / net / label."""
    rm = (cfg.get("signals", "regime_mult", default={}) or {}).get(regime, {}) or {}
    cw = float(cfg.get("signals", "conviction_weight", default=0.5))
    use_cal = bool(cfg.get("signals", "calibrate", default=True))
    adj = []
    for s in fired:
        k = float(rm.get("buy" if s["side"] == "BUY" else "sell", 1.0))
        if use_cal and s["code"] in calib:
            k *= calib[s["code"]]
        if s["side"] == "BUY":
            k *= 1.0 + (conv_mult - 1.0) * cw
        adj.append({**s, "strength": round(float(min(0.95, max(0.0, s["strength"] * k))), 4)})
    bull = 1.0 - float(np.prod([1 - s["strength"] for s in adj if s["side"] == "BUY"] or [1.0]))
    bear = 1.0 - float(np.prod([1 - s["strength"] for s in adj if s["side"] == "SELL"] or [1.0]))
    net = bull - bear
    th = cfg.get("signals", "labels", default={}) or {}
    if net >= float(th.get("strong_buy", 0.55)):
        label = "STRONG BUY"
    elif net >= float(th.get("buy", 0.25)):
        label = "BUY"
    elif net <= float(th.get("strong_sell", -0.55)):
        label = "STRONG SELL"
    elif net <= float(th.get("sell", -0.25)):
        label = "SELL"
    else:
        label = "NEUTRAL"
    # A STRONG call needs confluence: evidence from at least two independent
    # families (price action alone - however loud - is one family). On random
    # walks the technical detectors by themselves produced "strong" calls.
    if label.startswith("STRONG"):
        side = "BUY" if label == "STRONG BUY" else "SELL"
        fams = {s["family"] for s in adj if s["side"] == side and s["strength"] >= 0.15}
        if len(fams) < int(cfg.get("signals", "strong_min_families", default=2)):
            label = side
    return adj, {"bull": round(bull, 4), "bear": round(bear, 4), "net": round(net, 4),
                 "label": label}


def _group(df: pd.DataFrame, key: str = "ticker") -> dict:
    return {k: g for k, g in df.groupby(key)} if not df.empty else {}


def build_context(today: date, cfg) -> dict:
    ctx: dict = {}
    fund = _safe("SELECT * FROM fundamentals")
    ctx["fund"] = fund.set_index("ticker").to_dict("index") if not fund.empty else {}
    cats = _safe("SELECT ticker, type, title, date, confidence FROM catalysts")
    ctx["cats"] = _group(cats)
    ctx["type_weights"] = cfg.get("score", "catalyst_type_weights", default={}) or {}
    cut120 = (today - timedelta(days=120)).isoformat()
    fl = _safe("SELECT ticker, form, filed_date, url FROM filings WHERE form IN "
               "('424B5','424B4','424B3','S-1','S-3','S-3ASR') AND filed_date >= :c",
               {"c": cut120})
    if not fl.empty:
        fl["filed_date"] = pd.to_datetime(fl["filed_date"], errors="coerce")
    ctx["filings"] = _group(fl)
    gc = _safe("SELECT ticker FROM filing_risk_flags WHERE going_concern = 1")
    ctx["going_concern"] = set(gc["ticker"]) if not gc.empty else set()
    ins = _safe("SELECT ticker, owner, code, value, txn_date FROM insider_txns "
                "WHERE code IN ('P','S') AND txn_date >= :c",
                {"c": (today - timedelta(days=60)).isoformat()})
    ctx["insiders"] = _group(ins)
    news = _safe("SELECT ticker, tickers_csv, title, url, published, sentiment, event_score, "
                 "event_tags FROM news WHERE published >= :c",
                 {"c": (datetime.now(timezone.utc) - timedelta(days=28)).strftime("%Y-%m-%d %H:%M:%S")})
    if not news.empty:
        news["published"] = pd.to_datetime(news["published"], utc=True, errors="coerce")
        news["event_score"] = pd.to_numeric(news["event_score"], errors="coerce").fillna(0.0)
        news["sentiment"] = pd.to_numeric(news["sentiment"], errors="coerce").fillna(0.0)
        news["tk"] = news["tickers_csv"].fillna(news["ticker"]).fillna("").str.split(",")
        news = news.explode("tk")
        news["tk"] = news["tk"].str.strip()
        news = news[news["tk"] != ""]
    ctx["news"] = _group(news, "tk") if not news.empty else {}
    try:
        from .smart_money import ticker_summary

        sm = ticker_summary()
        sm = sm[sm["ticker"].notna() & (pd.to_datetime(sm["period"])
                                        >= pd.Timestamp(today - timedelta(days=200)))]
        ctx["smart"] = {r["ticker"]: r for _, r in sm.iterrows()}
    except Exception:  # noqa: BLE001
        ctx["smart"] = {}
    op = _safe("SELECT * FROM options_snapshots WHERE date >= :c",
               {"c": (today - timedelta(days=4)).isoformat()})
    if not op.empty:
        op = op.sort_values("date").groupby("ticker").last()
        ctx["options"] = op.to_dict("index")
    else:
        ctx["options"] = {}
    try:
        from ..ingest.short_volume import short_ratio_trend

        st = short_ratio_trend()
        ctx["short"] = st.set_index("ticker").to_dict("index") if not st.empty else {}
    except Exception:  # noqa: BLE001
        ctx["short"] = {}
    pa = cfg.get("signals", "detectors", "pipeline_advance", default={}) or {}
    cutp = (today - timedelta(days=int(pa.get("days", 120)))).isoformat()
    tr = _safe("SELECT ticker, nct_id, title, phase, start_date FROM clinical_trials "
               "WHERE start_date >= :c", {"c": cutp})
    mt = _safe("SELECT ticker, nct_id, title, phase, start_date FROM molecule_trials "
               "WHERE start_date >= :c", {"c": cutp})
    tr = pd.concat([x for x in (tr, mt) if not x.empty], ignore_index=True) \
        if not (tr.empty and mt.empty) else pd.DataFrame()
    if not tr.empty:
        tr = tr[tr["phase"].fillna("").str.contains("P3")].drop_duplicates(["ticker", "nct_id"])
        tr["start_date"] = pd.to_datetime(tr["start_date"], errors="coerce")
        tr = tr[tr["start_date"] <= pd.Timestamp(today)]
    ctx["new_p3"] = _group(tr) if not tr.empty else {}
    # trial change radar (process/trial_changes.py): the last 45 days of moves
    tc = _safe("SELECT c.ticker, c.nct_id, c.kind, c.days, c.old, c.new, c.detected_at, "
               "t.phase FROM trial_changes c LEFT JOIN clinical_trials t ON t.nct_id = c.nct_id "
               "WHERE c.detected_at >= :c",
               {"c": (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")})
    if not tc.empty:
        tc["detected_at"] = pd.to_datetime(tc["detected_at"], utc=True, errors="coerce")
    ctx["trial_changes"] = _group(tc) if not tc.empty else {}
    # events read from headlines and filings by the LLM jobs (ai/jobs.py)
    ev = _safe("SELECT ticker, event_type, outcome, confidence, summary, scored_at, id "
               "FROM news_llm WHERE kind IN ('news','filing') AND scored_at >= :c "
               "AND confidence >= 0.75",
               {"c": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")})
    ctx["ai_events"] = _group(ev) if not ev.empty else {}
    d13 = _safe("SELECT ticker, form, filed_date, url FROM filings WHERE (form LIKE 'SC 13D%' "
                "OR form LIKE 'SCHEDULE 13D%') AND filed_date >= :c",
                {"c": (today - timedelta(days=30)).isoformat()})
    ctx["activist"] = _group(d13) if not d13.empty else {}
    return ctx


def run() -> dict:
    cfg = load_settings()
    det = cfg.get("signals", "detectors", default={}) or {}
    today = date.today()
    now = datetime.now(timezone.utc)
    universe = read_sql("SELECT ticker FROM securities WHERE tier IS NULL OR tier = 'core'")
    if universe.empty:
        return {"rows": 0}
    tickers = universe["ticker"].tolist()

    px = _load_prices()
    feats: dict[str, pd.DataFrame] = {}
    if not px.empty:
        for tk, g in px.groupby("ticker"):
            if len(g) >= 30:
                feats[tk] = price_features(g)
    bench = cfg.get("signals", "regime_benchmark", default="XBI")
    regime = regime_of(feats.get(bench))
    uni_feats = {tk: f for tk, f in feats.items() if tk in set(tickers)}
    add_rs_rating(uni_feats)
    calib = calibration(
        floor_buy=float(cfg.get("signals", "calibration_floor_buy", default=0.5)),
        floor_sell=float(cfg.get("signals", "calibration_floor_sell", default=0.75)))
    ctx = build_context(today, cfg)

    from ..store import get_watchlist

    conv_map = {int(k): float(v) for k, v in
                (cfg.get("score", "conviction_map", default={}) or {}).items()}
    conv = {w["ticker"].upper(): conv_map.get(int(w.get("conviction", 3)), 1.0)
            for w in get_watchlist()}

    sig_rows, score_rows = [], []
    for tk in tickers:
        f = uni_feats.get(tk)
        fired: list[dict] = []
        stale = f is None or f.empty or (pd.Timestamp(today) - f["date"].iloc[-1]).days > 7
        if not stale:
            fired.extend(live_technical(technical_events(f, det), len(f)))
        fired.extend(event_detectors(tk, ctx, None if stale else f, det, today))
        adj, comp = composite(fired, regime, conv.get(tk, 1.0), calib, cfg)
        for s in adj:
            sig_rows.append({"id": hashlib.sha1(f"{tk}|{s['code']}|{today}".encode()).hexdigest()[:48],
                             "asof": today, "ticker": tk, "side": s["side"], "code": s["code"],
                             "strength": s["strength"], "title": s["title"][:400],
                             "detail": json.dumps({**s["detail"], "family": s["family"]},
                                                  default=str), "ts": now})
        top = sorted(adj, key=lambda s: -s["strength"])[:4]
        score_rows.append({
            "ticker": tk, "asof": today, **comp,
            "n_buy": sum(1 for s in adj if s["side"] == "BUY"),
            "n_sell": sum(1 for s in adj if s["side"] == "SELL"),
            "close": None if stale else float(f["close"].iloc[-1]),
            "regime": regime,
            "top": json.dumps([{"code": s["code"], "side": s["side"], "strength": s["strength"],
                                "title": s["title"]} for s in top]),
            "ts": now})

    keep = int(cfg.get("signals", "keep_days", default=400))
    with get_engine().begin() as conn:
        # today's run replaces today's rows (a detector that stopped firing goes away)
        conn.execute(signals.delete().where(signals.c.asof == today))
        conn.execute(signals.delete().where(signals.c.asof < today - timedelta(days=keep)))
        conn.execute(signal_scores.delete().where(
            signal_scores.c.asof < today - timedelta(days=keep)))
    bulk_upsert(signals, sig_rows)
    bulk_upsert(signal_scores, score_rows)
    counts = pd.Series([r["label"] for r in score_rows]).value_counts().to_dict()
    log.info("signals: %d detectors fired across %d names, regime %s, %s",
             len(sig_rows), len(score_rows), regime, counts)
    return {"rows": len(sig_rows), "names": len(score_rows), "regime": regime,
            "labels": counts, "calibrated": len(calib)}
