"""Backtests: does any of this actually precede the move? -> ``backtests``.

Three studies, all point-in-time (every feature at date d uses prices up to d
only; future closes are used purely as the outcome):

  events  - for every price/volume detector in the signal engine, the average
            *excess* forward return (vs the equal-weight universe over the same
            window) after it fires, hit rate and t-stat at 1/3/6 months. The
            signal engine reads this back to scale each detector by its measured
            edge.
  factor  - weekly snapshots: rank the universe by (a) the Focus Score's
            momentum component, (b) the net technical signal, (c) both; report
            quintile spreads, information coefficient and a non-overlapping
            top-quintile equity curve against the universe and XBI.
  track   - the live record: every label the engine has issued (signal_scores
            history) scored against what the stock did next.

Caveats, shown on the page: the universe is today's XBI membership (names that
failed and left are missing - survivorship bias), and news, filings, 13F and
catalyst detectors can only be scored live (their history is too short or
wasn't captured point-in-time).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from ..config import load_settings
from ..db import backtests, bulk_upsert, read_sql
from .signals import add_rs_rating, price_features, technical_events

log = logging.getLogger("bioterm.process.backtest")

EDGE_LOOKBACK = 5


# ---------------------------------------------------------------- panel
def load_features(min_rows: int = 150) -> tuple[dict[str, pd.DataFrame], pd.DataFrame | None]:
    px = read_sql("SELECT ticker, date, open, high, low, close, volume FROM prices")
    if px.empty:
        return {}, None
    px["date"] = pd.to_datetime(px["date"])
    uni = set(read_sql("SELECT ticker FROM securities "
                       "WHERE tier IS NULL OR tier = 'core'")["ticker"])
    bench_tk = load_settings().get("signals", "regime_benchmark", default="XBI")
    feats, bench = {}, None
    for tk, g in px.groupby("ticker"):
        if len(g) < min_rows:
            continue
        if tk == bench_tk:
            bench = price_features(g)
        elif tk in uni:
            feats[tk] = price_features(g)
    add_rs_rating(feats)
    return feats, bench


def add_forward(f: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    for h in horizons:
        f[f"fwd_{h}"] = f["close"].shift(-h) / f["close"] - 1.0
    return f


def momentum_factor(snap: pd.DataFrame) -> pd.Series:
    """The Focus Score momentum component, recomputed point-in-time."""
    ret_rank = snap[["ret_21", "ret_63", "ret_126"]].rank(pct=True).mean(axis=1)
    vol = ((snap["vol_z20"].clip(-1, 4) + 1) / 5.0)
    rng = snap["pct_52w"].fillna(0.5)
    rsi_gate = snap["rsi14"].between(40, 75).astype(float)
    return 0.5 * ret_rank.fillna(0.5) + 0.2 * vol.fillna(0.2) + 0.2 * rng + 0.1 * rsi_gate


def technical_net(f: pd.DataFrame, ev: pd.DataFrame) -> pd.Series:
    """Daily net technical signal (bull - bear, same combination rule as live)."""
    n = len(f)
    bull = np.ones(n)
    bear = np.ones(n)
    for r in ev.itertuples():
        span = range(r.pos, min(n, r.pos + EDGE_LOOKBACK)) if r.kind == "edge" else [r.pos]
        for k, t in enumerate(span):
            s = r.strength * (1 - 0.08 * k if r.kind == "edge" else 1.0)
            if r.side == "BUY":
                bull[t] *= 1 - s
            else:
                bear[t] *= 1 - s
    return pd.Series((1 - bull) - (1 - bear), index=f.index)


# ---------------------------------------------------------------- stats
def _stats(x: pd.Series, side: str) -> dict:
    x = pd.to_numeric(x, errors="coerce").dropna()
    n = int(len(x))
    if n == 0:
        return {"n": 0}
    mean = float(x.mean())
    sd = float(x.std(ddof=1)) if n > 1 else float("nan")
    t = mean / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    hit = float((x > 0).mean()) if side == "BUY" else float((x < 0).mean())
    return {"n": n, "mean": round(mean, 5), "median": round(float(x.median()), 5),
            "hit": round(hit, 4), "t": None if math.isnan(t) else round(t, 3)}


def _clean(o):
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (pd.Timestamp, date)):
        return str(pd.Timestamp(o).date())
    return o


# ---------------------------------------------------------------- studies
def event_study(feats: dict[str, pd.DataFrame], horizons: list[int], det: dict) -> dict:
    ew = pd.concat({tk: f.set_index("date")[[f"fwd_{h}" for h in horizons]]
                    for tk, f in feats.items()}).groupby(level=1).mean()
    rows = []
    for tk, f in feats.items():
        ev = technical_events(f, det)
        if ev.empty:
            continue
        # a state that holds for weeks is one observation, counted on its first day
        ev = ev.sort_values(["code", "pos"])
        prev_pos = ev.groupby("code")["pos"].shift(1)
        ev = ev[(ev["kind"] == "edge") | (prev_pos.isna()) | (ev["pos"] - prev_pos > 1)]
        for h in horizons:
            ev[f"fwd_{h}"] = f[f"fwd_{h}"].to_numpy()[ev["pos"].to_numpy()]
            ev[f"x_{h}"] = ev[f"fwd_{h}"] - ev["date"].map(ew[f"fwd_{h}"]).to_numpy()
        ev["ticker"] = tk
        rows.append(ev)
    if not rows:
        return {"by_code": {}, "n_events": 0}
    allev = pd.concat(rows, ignore_index=True)
    by_code = {}
    for code, g in allev.groupby("code"):
        side = g["side"].iloc[0]
        d = {"side": side, "n": int(len(g)), "tickers": int(g["ticker"].nunique())}
        for h in horizons:
            s = _stats(g[f"x_{h}"], side)
            d[f"n_{h}"] = s.get("n", 0)
            d[f"mean_{h}"] = s.get("mean")
            d[f"hit_{h}"] = s.get("hit")
            d[f"t_{h}"] = s.get("t")
            d[f"raw_{h}"] = _stats(g[f"fwd_{h}"], side).get("mean")
        by_code[code] = d
    recent = allev.sort_values("date").tail(40)
    return {"by_code": by_code, "n_events": int(len(allev)),
            "recent": [{"date": r.date, "ticker": r.ticker, "code": r.code, "side": r.side,
                        "fwd_21": getattr(r, "fwd_21", None)} for r in recent.itertuples()]}


def factor_study(feats: dict[str, pd.DataFrame], bench: pd.DataFrame | None, horizons: list[int],
                 det: dict, every: int, warmup: int, q: int) -> dict:
    frames = []
    for tk, f in feats.items():
        ev = technical_events(f, det)
        g = f.assign(ticker=tk, tech=technical_net(f, ev) if not ev.empty else 0.0)
        frames.append(g.iloc[warmup:])
    if not frames:
        return {}
    panel = pd.concat(frames, ignore_index=True)
    dates = sorted(panel["date"].unique())
    snaps = dates[::every]
    main = horizons[0]
    out: dict = {"factors": {}, "dates": len(snaps), "universe": len(feats),
                 "start": dates[0] if dates else None, "end": dates[-1] if dates else None}
    by_date = {d: g for d, g in panel[panel["date"].isin(snaps)].groupby("date")}
    names = {"momentum": "Momentum (Focus Score component)", "technical": "Net technical signal",
             "combined": "Momentum + technical signal"}
    for key, label in names.items():
        ics, qrets, top_hits = {h: [] for h in horizons}, {h: [] for h in horizons}, []
        for d in snaps:
            s = by_date.get(d)
            if s is None or len(s) < q * 3:
                continue
            mom = momentum_factor(s)
            fac = {"momentum": mom, "technical": s["tech"],
                   "combined": mom.rank(pct=True) + s["tech"].rank(pct=True)}[key]
            for h in horizons:
                ok = s[f"fwd_{h}"].notna() & fac.notna()
                if ok.sum() < q * 3:
                    continue
                fr = s.loc[ok, f"fwd_{h}"]
                fv = fac[ok]
                ics[h].append(fv.rank().corr(fr.rank()))
                bucket = pd.qcut(fv.rank(method="first"), q, labels=False)
                ex = fr - fr.mean()
                qrets[h].append(ex.groupby(bucket).mean())
                if h == main:
                    top_hits.append(float(ex[bucket == q - 1].mean() > 0))
        res = {"label": label}
        for h in horizons:
            ic = pd.Series(ics[h], dtype=float).dropna()
            res[f"ic_{h}"] = round(float(ic.mean()), 4) if len(ic) else None
            res[f"ic_t_{h}"] = round(float(ic.mean() / ic.std(ddof=1) * math.sqrt(len(ic))), 3) \
                if len(ic) > 2 and ic.std(ddof=1) > 0 else None
            if qrets[h]:
                qm = pd.concat(qrets[h], axis=1).mean(axis=1)
                res[f"quintiles_{h}"] = [round(float(v), 5) for v in qm.reindex(range(q)).fillna(0)]
                res[f"spread_{h}"] = round(float(qm.iloc[-1] - qm.iloc[0]), 5)
            res[f"snapshots_{h}"] = int(len(ic))
        res["top_hit_rate"] = round(float(np.mean(top_hits)), 4) if top_hits else None
        out["factors"][key] = res

    # non-overlapping equity curve on the combined factor: rebalance every `main`
    # sessions, hold the top quintile equal-weight; each point sits at the end
    # of its holding period
    pos = {d: i for i, d in enumerate(dates)}
    bench_close = bench.set_index("date")["close"] if bench is not None else None
    eq = {"date": [], "top": [1.0], "universe": [1.0], "xbi": [1.0]}
    for d in dates[::main]:
        s = panel[(panel["date"] == d) & panel[f"fwd_{main}"].notna()]
        if len(s) < q * 3:
            continue
        fac = momentum_factor(s).rank(pct=True) + s["tech"].rank(pct=True)
        top = s[fac >= fac.quantile(1 - 1 / q)]
        end_d = dates[min(pos[d] + main, len(dates) - 1)]
        if not eq["date"]:
            eq["date"].append(d)
        eq["date"].append(end_d)
        eq["top"].append(eq["top"][-1] * (1 + float(top[f"fwd_{main}"].mean())))
        eq["universe"].append(eq["universe"][-1] * (1 + float(s[f"fwd_{main}"].mean())))
        if bench_close is not None and d in bench_close.index and end_d in bench_close.index:
            eq["xbi"].append(eq["xbi"][-1] * float(bench_close.loc[end_d] / bench_close.loc[d]))
        else:
            eq["xbi"].append(eq["xbi"][-1])
    out["equity"] = eq
    return out


def track_record(horizons: tuple[int, ...] = (5, 21, 63)) -> dict:
    ss = read_sql("SELECT ticker, asof, label, net, close FROM signal_scores "
                  "WHERE close IS NOT NULL")
    if ss.empty:
        return {"by_label": {}, "n": 0}
    px = read_sql("SELECT ticker, date, close FROM prices WHERE date >= :d",
                  {"d": str(pd.to_datetime(ss["asof"]).min().date())})
    if px.empty:
        return {"by_label": {}, "n": 0}
    px["date"] = pd.to_datetime(px["date"])
    ss["asof"] = pd.to_datetime(ss["asof"])
    wide = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    ew = wide.pct_change().mean(axis=1).fillna(0.0)
    ew_idx = (1 + ew).cumprod()
    rows = []
    # one observation per label change - consecutive days with the same label
    # are the same call, not independent evidence
    ss = ss.sort_values(["ticker", "asof"])
    ss = ss[ss["label"] != ss.groupby("ticker")["label"].shift(1)]
    for r in ss.itertuples():
        if r.ticker not in wide.columns:
            continue
        col = wide[r.ticker].dropna()
        i = col.index.searchsorted(r.asof)
        if i >= len(col):
            continue
        rec = {"ticker": r.ticker, "asof": r.asof, "label": r.label}
        base_px, base_d = col.iloc[i], col.index[i]
        for h in horizons:
            j = i + h
            if j < len(col):
                end_d = col.index[j]
                ret = col.iloc[j] / base_px - 1
                rec[f"ret_{h}"] = ret
                rec[f"x_{h}"] = ret - (ew_idx.loc[end_d] / ew_idx.loc[base_d] - 1)
        rec["ret_open"] = col.iloc[-1] / base_px - 1
        rows.append(rec)
    df = pd.DataFrame(rows)
    by_label = {}
    for lab, g in df.groupby("label"):
        side = "BUY" if "BUY" in lab else "SELL"
        d = {"n": int(len(g))}
        for h in horizons:
            if f"x_{h}" in g:
                s = _stats(g[f"x_{h}"], side if lab != "NEUTRAL" else "BUY")
                d[f"n_{h}"], d[f"x_{h}"], d[f"hit_{h}"] = s.get("n", 0), s.get("mean"), s.get("hit")
        by_label[lab] = d
    recent = df.sort_values("asof", ascending=False)
    recent = recent[recent["label"] != "NEUTRAL"].head(30)
    return {"by_label": by_label, "n": int(len(df)),
            "recent": recent.to_dict("records")}


def detector_record(horizons: tuple[int, ...] = (5, 21, 63), gap_days: int = 10) -> dict:
    """Live per-detector study: every detector that fired in production (the event
    families included - catalyst setups, dilution, insiders, 13F, news - which have
    no price-only history to backtest), followed forward. Excess return vs the
    equal-weight universe; a (ticker, detector) firing counts again only after a
    ``gap_days`` pause, so a condition that stays true isn't counted daily."""
    sg = read_sql("SELECT ticker, asof, side, code, strength FROM signals")
    if sg.empty:
        return {"by_code": {}, "n": 0}
    sg["asof"] = pd.to_datetime(sg["asof"])
    sg = sg.sort_values(["ticker", "code", "asof"])
    gap = sg.groupby(["ticker", "code"])["asof"].diff().dt.days
    sg = sg[gap.isna() | (gap > gap_days)]
    px = read_sql("SELECT ticker, date, close FROM prices WHERE date >= :d",
                  {"d": str((sg["asof"].min() - pd.Timedelta(days=7)).date())})
    if px.empty:
        return {"by_code": {}, "n": 0}
    px["date"] = pd.to_datetime(px["date"])
    wide = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    ew_idx = (1 + wide.pct_change().mean(axis=1).fillna(0.0)).cumprod()
    rows = []
    for r in sg.itertuples():
        if r.ticker not in wide.columns:
            continue
        col = wide[r.ticker].dropna()
        i = col.index.searchsorted(r.asof)
        if i >= len(col):
            continue
        rec = {"code": r.code, "side": r.side, "ticker": r.ticker, "asof": r.asof}
        base_px, base_d = col.iloc[i], col.index[i]
        for h in horizons:
            j = i + h
            if j < len(col):
                rec[f"x_{h}"] = (col.iloc[j] / base_px - 1) - (
                    ew_idx.loc[col.index[j]] / ew_idx.loc[base_d] - 1)
        rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return {"by_code": {}, "n": 0}
    by_code = {}
    for (code, side), g in df.groupby(["code", "side"]):
        d = {"side": side, "n": int(len(g)), "first": str(g["asof"].min().date()),
             "last": str(g["asof"].max().date())}
        for h in horizons:
            if f"x_{h}" in g:
                st_ = _stats(g[f"x_{h}"], side)
                d[f"n_{h}"], d[f"x_{h}"], d[f"hit_{h}"], d[f"t_{h}"] = (
                    st_.get("n", 0), st_.get("mean"), st_.get("hit"), st_.get("t"))
        by_code[code] = d
    return {"by_code": by_code, "n": int(len(df)), "horizons": list(horizons),
            "gap_days": gap_days}


def run() -> dict:
    cfg = load_settings()
    b = cfg.get("backtest", default={}) or {}
    horizons = [int(h) for h in b.get("horizons", [21, 63, 126])]
    every = int(b.get("rebalance_every", 5))
    warmup = int(b.get("warmup", 210))
    q = int(b.get("quantiles", 5))
    det = cfg.get("signals", "detectors", default={}) or {}
    feats, bench = load_features()
    if len(feats) < q * 3:
        log.warning("backtest: only %d names with enough history", len(feats))
        return {"rows": 0}
    for f in feats.values():
        add_forward(f, horizons)
    if bench is not None:
        add_forward(bench, horizons)

    now = datetime.now(timezone.utc)
    today = date.today().isoformat()
    params = {"horizons": horizons, "every": every, "warmup": warmup, "quantiles": q,
              "universe": len(feats)}
    ev = event_study(feats, horizons, det)
    fac = factor_study(feats, bench, horizons, det, every, warmup, q)
    tr = track_record()
    try:
        dr = detector_record()
    except Exception as exc:  # noqa: BLE001 - a young database, never fatal
        log.warning("detector record skipped: %s", exc)
        dr = {"by_code": {}, "n": 0}
    rows = [{"id": f"{k}|{today}", "kind": k, "ts": now, "params": json.dumps(params),
             "results": json.dumps(_clean(v))}
            for k, v in (("events", ev), ("factor", fac), ("track", tr), ("detectors", dr))]
    bulk_upsert(backtests, rows)
    best = sorted(((c, s.get(f"t_{horizons[1]}") or 0) for c, s in ev.get("by_code", {}).items()),
                  key=lambda x: -abs(x[1]))[:3]
    log.info("backtest: %d events over %d names; strongest detectors %s",
             ev.get("n_events", 0), len(feats), best)
    return {"rows": 4, "events": ev.get("n_events", 0), "names": len(feats),
            "track_calls": tr.get("n", 0), "live_detector_events": dr.get("n", 0)}


def latest(kind: str) -> dict:
    df = read_sql("SELECT results, ts, params FROM backtests WHERE kind = :k "
                  "ORDER BY ts DESC LIMIT 1", {"k": kind})
    if df.empty:
        return {}
    try:
        out = json.loads(df.iloc[0]["results"])
    except (TypeError, ValueError):
        return {}
    out["_ts"] = str(df.iloc[0]["ts"])
    try:
        out["_params"] = json.loads(df.iloc[0]["params"])
    except (TypeError, ValueError):
        out["_params"] = {}
    return out
