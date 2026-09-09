"""Focus Score: a transparent, fully-decomposed monitoring signal -> ``scores``.

    focus = conviction_mult * (w_mom*momentum + w_cat*catalyst + w_news*newsflow) - w_risk*risk

Every sub-score is in [0, 1] and every input is stored in ``scores.rationale`` (JSON)
so the dashboard can show exactly why a name is ranked where it is.

This is NOT investment advice. It ranks how much *attention* a name deserves given
its pipeline calendar, momentum and news flow - the user supplies the judgement on
whether the underlying science will work (via watchlist conviction).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from ..config import load_settings
from ..db import bulk_upsert, read_sql, scores
from .technicals import latest_technicals

log = logging.getLogger("bioterm.process.score")


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# ------------------------------------------------------------------ momentum
def _momentum_frame(tech: pd.DataFrame) -> pd.DataFrame:
    t = tech.copy()
    for col in ("ret_1m", "ret_3m", "ret_6m"):
        t[col] = pd.to_numeric(t[col], errors="coerce")
        t[f"{col}_pct"] = t[col].rank(pct=True)
    out = pd.DataFrame({"ticker": t["ticker"]})
    ret_component = t[["ret_1m_pct", "ret_3m_pct", "ret_6m_pct"]].mean(axis=1)
    vol_component = t["vol_z20"].clip(-1, 4).pipe(lambda s: (s + 1) / 5.0)
    range_component = pd.to_numeric(t["pct_52w_range"], errors="coerce").fillna(0.5)

    macd_gate = ((pd.to_numeric(t["macd"], errors="coerce")
                  > pd.to_numeric(t["macd_signal"], errors="coerce")).astype(float))
    rsi = pd.to_numeric(t["rsi14"], errors="coerce").fillna(50)
    rsi_gate = rsi.between(40, 75).astype(float) - (rsi > 82).astype(float) * 0.5

    out["momentum"] = (
        0.45 * ret_component.fillna(0.5)
        + 0.20 * vol_component.fillna(0.2)
        + 0.20 * range_component
        + 0.10 * macd_gate
        + 0.05 * rsi_gate.clip(0, 1)
    ).clip(0, 1)
    out["ret_1m"] = t["ret_1m"]
    out["ret_3m"] = t["ret_3m"]
    out["ret_6m"] = t["ret_6m"]
    out["vol_z20"] = t["vol_z20"]
    out["pct_52w_range"] = range_component
    return out


# ------------------------------------------------------------------ catalyst
def _size_factor(market_cap: float | None) -> float:
    """A catalyst moves a small biotech far more than a mega-cap. Damp mega-caps.

    ~$1B -> 1.0 ... ~$20B -> 0.75 ... ~$100B -> 0.55 ... >$300B -> ~0.4
    """
    if not market_cap or market_cap <= 0:
        return 0.9  # unknown: assume small/mid
    b = market_cap / 1e9
    return float(max(0.4, min(1.0, 1.15 - 0.28 * math.log10(max(b, 1.0)))))


def _catalyst_scores(cfg) -> pd.DataFrame:
    df = read_sql("SELECT * FROM catalysts")
    horizon = cfg.horizon_months
    tw = cfg.get("score", "catalyst_type_weights", default={}) or {}
    conf_factor = {"high": 1.0, "medium": 0.75, "low": 0.5}
    top_k = int(cfg.get("score", "catalyst_top_k", default=6))
    if df.empty:
        return pd.DataFrame(columns=["ticker", "catalyst", "catalyst_detail"])

    caps = read_sql("SELECT ticker, market_cap FROM fundamentals")
    cap_by_ticker = dict(zip(caps["ticker"], caps["market_cap"])) if not caps.empty else {}

    rows = []
    for tk, grp in df.groupby("ticker"):
        contribs: list[tuple[float, dict]] = []
        for _, c in grp.iterrows():
            ma = float(c["months_away"])
            if ma > horizon + 2 or ma < -1.5:
                continue
            proximity = max(0.0, 1.0 - max(0.0, ma) / (horizon + 1))
            w = float(tw.get(c["type"], 0.4)) * conf_factor.get(c["confidence"], 0.5)
            contrib = w * (0.35 + 0.65 * proximity)
            contribs.append((contrib, {
                "type": c["type"], "date": str(c["date"]), "months_away": round(ma, 1),
                "confidence": c["confidence"], "contrib": round(contrib, 3),
                "title": c["title"]}))
        contribs.sort(key=lambda x: x[0], reverse=True)
        # only the strongest few catalysts count - a mega-cap with 90 trials
        # shouldn't dominate a small-cap with one imminent Phase 3 readout
        raw = sum(c for c, _ in contribs[:top_k])
        sf = _size_factor(cap_by_ticker.get(tk))
        score = math.tanh(raw) * sf
        rows.append({"ticker": tk, "catalyst": round(score, 4),
                     "catalyst_detail": [d for _, d in contribs[:8]]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ news flow
def _newsflow_scores() -> pd.DataFrame:
    df = read_sql("SELECT ticker, published, sentiment, event_score FROM news")
    if df.empty:
        return pd.DataFrame(columns=["ticker", "newsflow", "news_detail"])
    df["published"] = pd.to_datetime(df["published"], errors="coerce", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    recent = df[df["published"] >= now - pd.Timedelta(days=14)]
    base = df[df["published"] >= now - pd.Timedelta(days=90)]
    base_rate = base.groupby("ticker").size() / 90.0

    rows = []
    for tk, grp in recent.groupby("ticker"):
        cnt = len(grp)
        br = float(base_rate.get(tk, 0.02))
        volume_ratio = cnt / max(br * 14.0, 1.0)
        mean_sent = float(pd.to_numeric(grp["sentiment"], errors="coerce").mean() or 0.0)
        event_sum = float(pd.to_numeric(grp["event_score"], errors="coerce").sum() or 0.0)
        score = _clip01(
            0.35 * _clip01(volume_ratio / 3.0)
            + 0.20 * ((mean_sent + 1) / 2)
            + 0.45 * _sigmoid(event_sum)
        )
        rows.append(
            {"ticker": tk, "newsflow": round(score, 4),
             "news_detail": {"recent_14d": cnt, "baseline_rate_day": round(br, 3),
                             "mean_sentiment": round(mean_sent, 3),
                             "event_score_sum": round(event_sum, 3)}}
        )
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ risk overlay
def _risk_scores(cfg) -> pd.DataFrame:
    fund = read_sql("SELECT * FROM fundamentals")
    floor = float(cfg.get("score", "risk", "runway_quarters_floor", default=4.0))
    dilut = read_sql(
        "SELECT DISTINCT ticker FROM filings WHERE form IN ('424B5','S-1','S-3') "
        "AND filed_date >= :cut", {"cut": str(date.today() - pd.Timedelta(days=75))}
    )
    dilut_tickers = set(dilut["ticker"]) if not dilut.empty else set()

    news_df = read_sql("SELECT ticker, published, event_score FROM news")
    neg_recent: dict[str, float] = {}
    if not news_df.empty:
        news_df["published"] = pd.to_datetime(news_df["published"], errors="coerce", utc=True)
        cut = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=21)
        rec = news_df[news_df["published"] >= cut]
        neg = rec[pd.to_numeric(rec["event_score"], errors="coerce") < 0]
        neg_recent = (-neg.groupby("ticker")["event_score"].sum()).to_dict()

    cols = ["ticker", "risk", "risk_detail", "runway_quarters"]
    if fund.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    tickers = fund["ticker"].tolist()
    fund_ix = fund.set_index("ticker")
    for tk in tickers:
        f = fund_ix.loc[tk]
        runway = pd.to_numeric(pd.Series([f.get("runway_quarters")]), errors="coerce").iloc[0]
        ni = pd.to_numeric(pd.Series([f.get("net_income_ttm")]), errors="coerce").iloc[0]
        parts = {}
        if pd.notna(runway):
            parts["runway"] = _clip01((floor - runway) / floor) if runway < floor else 0.0
        elif pd.notna(ni) and ni < 0:
            parts["runway"] = 0.30  # unprofitable, runway unknown
        else:
            parts["runway"] = 0.0
        parts["dilution_filing"] = 0.30 if tk in dilut_tickers else 0.0
        parts["negative_news"] = min(0.40, 0.20 * float(neg_recent.get(tk, 0.0)))
        risk = _clip01(parts["runway"] * 0.6 + parts["dilution_filing"] + parts["negative_news"])
        rows.append({"ticker": tk, "risk": round(risk, 4), "risk_detail": parts,
                     "runway_quarters": None if pd.isna(runway) else float(runway)})
    return pd.DataFrame(rows, columns=cols)


# ------------------------------------------------------------------ compose
def run() -> dict:
    cfg = load_settings()
    w = cfg.get("score", "weights", default={}) or {}
    w_mom = float(w.get("momentum", 0.3))
    w_cat = float(w.get("catalyst", 0.4))
    w_news = float(w.get("newsflow", 0.3))
    w_risk = float(w.get("risk", 0.25))
    conv_map = {int(k): float(v) for k, v in
                (cfg.get("score", "conviction_map", default={}) or {}).items()}
    default_conv = float(cfg.get("score", "default_conviction_mult", default=1.0))

    tech = latest_technicals()
    universe = read_sql("SELECT ticker, name, is_watchlist FROM securities")
    if universe.empty:
        log.warning("no securities - run universe build first")
        return {"rows": 0}

    mom = _momentum_frame(tech) if not tech.empty else pd.DataFrame(columns=["ticker", "momentum"])
    cat = _catalyst_scores(cfg)
    news_s = _newsflow_scores()
    risk = _risk_scores(cfg)

    df = universe.merge(mom, on="ticker", how="left") \
                 .merge(cat, on="ticker", how="left") \
                 .merge(news_s, on="ticker", how="left") \
                 .merge(risk, on="ticker", how="left")

    df["momentum"] = df["momentum"].fillna(0.4)
    df["catalyst"] = df["catalyst"].fillna(0.0)
    df["newsflow"] = df["newsflow"].fillna(0.05)
    df["risk"] = df["risk"].fillna(0.15)

    from ..store import get_watchlist

    conviction_by_ticker = {w["ticker"].upper(): int(w.get("conviction", 3))
                            for w in get_watchlist()}

    def conv_mult(row) -> float:
        c = conviction_by_ticker.get(str(row["ticker"]).upper())
        return conv_map.get(int(c), default_conv) if c is not None else default_conv

    df["conviction_mult"] = df.apply(conv_mult, axis=1)
    df["focus_score"] = (
        df["conviction_mult"] * (
            w_mom * df["momentum"] + w_cat * df["catalyst"] + w_news * df["newsflow"]
        ) - w_risk * df["risk"]
    ).round(4)

    df = df.sort_values("focus_score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    asof = date.today()

    rows = []
    for _, r in df.iterrows():
        rationale = {
            "weights": {"momentum": w_mom, "catalyst": w_cat, "newsflow": w_news, "risk": w_risk},
            "components": {
                "momentum": round(float(r["momentum"]), 4),
                "catalyst": round(float(r["catalyst"]), 4),
                "newsflow": round(float(r["newsflow"]), 4),
                "risk": round(float(r["risk"]), 4),
            },
            "conviction_mult": round(float(r["conviction_mult"]), 3),
            "momentum_detail": {
                k: (None if pd.isna(r.get(k)) else round(float(r.get(k)), 4))
                for k in ("ret_1m", "ret_3m", "ret_6m", "vol_z20", "pct_52w_range")
            },
            "catalyst_detail": r.get("catalyst_detail") if isinstance(r.get("catalyst_detail"), list) else [],
            "news_detail": r.get("news_detail") if isinstance(r.get("news_detail"), dict) else {},
            "risk_detail": r.get("risk_detail") if isinstance(r.get("risk_detail"), dict) else {},
            "runway_quarters": r.get("runway_quarters"),
        }
        rows.append(
            {
                "ticker": r["ticker"], "asof": asof,
                "focus_score": float(r["focus_score"]),
                "momentum": round(float(r["momentum"]), 4),
                "catalyst": round(float(r["catalyst"]), 4),
                "newsflow": round(float(r["newsflow"]), 4),
                "risk": round(float(r["risk"]), 4),
                "conviction_mult": round(float(r["conviction_mult"]), 3),
                "rank": int(r["rank"]),
                "rationale": json.dumps(rationale, default=str),
            }
        )

    n = bulk_upsert(scores, rows)

    # append a snapshot (one row / ticker / run) so movers work between runs,
    # not just day-over-day; keep ~14 days of history.
    from ..db import get_engine, score_snapshots

    ts = datetime.now(timezone.utc)
    snaps = [{"ts": ts, "ticker": r["ticker"], "focus_score": float(r["focus_score"]),
              "rank": int(r["rank"])} for _, r in df.iterrows()]
    with get_engine().begin() as conn:
        conn.execute(score_snapshots.insert(), snaps)
        cutoff = ts - pd.Timedelta(days=14)
        conn.execute(score_snapshots.delete().where(score_snapshots.c.ts < cutoff))

    log.info("scores: %d tickers ranked (asof %s), top=%s",
             n, asof, df.iloc[0]["ticker"] if not df.empty else "-")
    return {"rows": n, "asof": str(asof)}
