"""Screener: one row per universe name with every screenable fact, the filter
engine, saved screens and their entry alerts.

Derived scores (screening heuristics, stated plainly - not predictions):

dilution_risk (0-1)  need x capacity x overhang: short runway, an active shelf
                     (S-3 in 3 years), a recent prospectus supplement, warrants
                     and options outstanding vs shares, insiders' Form 144s
takeout_score (0-1)  the profile acquirers have historically bought: $0.5-15B
                     market cap, a Phase 3 or approved asset, an M&A-active
                     disease area, specialist funds adding, funded (not
                     distressed), no recent dilution, off its 52-week high
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .alerts import register

log = logging.getLogger("bioterm.screener")

# field -> (label, kind, help)   kind: num / pct / money / bool / text / date / label
FIELDS: dict[str, tuple[str, str, str]] = {
    "market_cap": ("Market cap", "money", "USD"),
    "price": ("Last close", "num", "last stored daily close"),
    "cash": ("Cash", "money", "cash + short-term investments"),
    "total_debt": ("Debt", "money", ""),
    "ev": ("Enterprise value", "money", "market cap - cash + debt"),
    "ev_to_cash": ("EV / cash", "num", "below 0 = trading under net cash"),
    "below_cash": ("Trades below cash", "bool", "enterprise value < 0"),
    "runway_quarters": ("Runway (quarters)", "num", "cash / quarterly burn"),
    "burn_ttm": ("Burn / year", "money", ""),
    "short_pct_float": ("Short % float", "pct", ""),
    "days_to_cover": ("Days to cover", "num", ""),
    "focus_score": ("Focus Score", "num", ""),
    "focus_rank": ("Focus rank", "num", ""),
    "signal": ("Signal", "label", "STRONG BUY ... STRONG SELL"),
    "signal_net": ("Signal net", "num", "-1 .. 1"),
    "ret_1m": ("1-month return", "pct", ""),
    "ret_3m": ("3-month return", "pct", ""),
    "pct_52w": ("Position in 52-week range", "pct", "0 = low, 1 = high"),
    "next_catalyst_days": ("Days to next catalyst", "num", ""),
    "next_catalyst_type": ("Next catalyst type", "text", ""),
    "binary_within_90d": ("Binary event in 90 days", "bool", "PDUFA / AdCom / Phase 3"),
    "top_phase": ("Most advanced phase", "text", "P1 / P2 / P3 / approved"),
    "n_p3": ("Active Phase 3 trials", "num", ""),
    "funds_holding": ("Specialist funds holding", "num", "13F, latest quarter"),
    "funds_net": ("Specialist funds net adds", "num", "initiated/added - cut/exited"),
    "holders_13f": ("All 13F holders", "num", "whole-market 13F"),
    "holders_13f_change": ("13F holder change", "num", "vs prior quarter"),
    "insider_buys_90d": ("Insider buys 90d", "money", "open market, USD"),
    "dilution_risk": ("Dilution risk", "num", "0-1 screen"),
    "shelf_active": ("Shelf registration active", "bool", "S-3 in the last 3 years"),
    "raised_90d": ("Raised in 90 days", "bool", "424B prospectus supplement"),
    "warrant_overhang": ("Warrant overhang", "pct", "warrants / shares"),
    "takeout_score": ("Takeout profile", "num", "0-1 screen"),
    "loe_years": ("Years to first LOE", "num", "marketed drugs, Orange Book"),
    "gov_awards": ("Government awards", "money", "USAspending, 5 years"),
    "watchlist": ("On watchlist", "bool", ""),
}
OPS = {"num": [">=", "<=", "between"], "pct": [">=", "<=", "between"],
       "money": [">=", "<=", "between"], "bool": ["is"], "text": ["in"],
       "label": ["in"], "date": [">=", "<="]}
HOT_AREAS = {"oncology", "autoimmune", "neurology", "metabolic", "hematology", "endocrine"}

PRESETS: dict[str, list[dict]] = {
    "Below cash, funded": [{"field": "below_cash", "op": "is", "value": True},
                           {"field": "runway_quarters", "op": ">=", "value": 4}],
    "Binary event ahead, not extended": [
        {"field": "binary_within_90d", "op": "is", "value": True},
        {"field": "ret_3m", "op": "<=", "value": 0.3}],
    "Dilution risk": [{"field": "dilution_risk", "op": ">=", "value": 0.5}],
    "Takeout profile": [{"field": "takeout_score", "op": ">=", "value": 0.55}],
    "Smart money buying": [{"field": "funds_net", "op": ">=", "value": 2}],
    "Squeeze candidates": [{"field": "short_pct_float", "op": ">=", "value": 0.2},
                           {"field": "signal", "op": "in", "value": ["BUY", "STRONG BUY"]}],
}


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    from .db import read_sql

    try:
        return read_sql(sql, params or {})
    except Exception as exc:  # noqa: BLE001 - a table missing on an older database
        log.info("screener query skipped: %s", exc)
        return pd.DataFrame()


def frame() -> pd.DataFrame:
    """Every screenable field per universe ticker (stored data only - fast)."""
    today = date.today()
    df = _q("SELECT s.ticker, s.name, s.is_watchlist, f.market_cap, f.cash, f.total_debt, "
            "f.runway_quarters, f.burn_ttm, f.short_percent_float, f.short_ratio, "
            "f.shares_out, f.xbrl_shares_out, f.warrants_out, f.options_out FROM securities s "
            "LEFT JOIN fundamentals f ON f.ticker = s.ticker")
    if df.empty:
        return df
    df = df.rename(columns={"short_percent_float": "short_pct_float",
                            "short_ratio": "days_to_cover", "is_watchlist": "watchlist"})
    df["watchlist"] = df["watchlist"].fillna(0).astype(int).astype(bool)
    df["ev"] = df["market_cap"] - df["cash"].fillna(0) + df["total_debt"].fillna(0)
    df["ev_to_cash"] = np.where(df["cash"] > 0, df["ev"] / df["cash"], np.nan)
    df["below_cash"] = df["ev"] < 0
    sh = df["shares_out"].fillna(df["xbrl_shares_out"])
    df["warrant_overhang"] = np.where(sh > 0, df["warrants_out"] / sh, np.nan)
    df["option_overhang"] = np.where(sh > 0, df["options_out"] / sh, np.nan)

    sc = _q("SELECT ticker, focus_score, rank FROM scores WHERE asof = "
            "(SELECT MAX(asof) FROM scores)")
    df = df.merge(sc.rename(columns={"rank": "focus_rank"}), on="ticker", how="left")
    sg = _q("SELECT ticker, label AS signal, net AS signal_net FROM signal_scores "
            "WHERE asof = (SELECT MAX(asof) FROM signal_scores)")
    df = df.merge(sg, on="ticker", how="left")
    te = _q("SELECT ticker, close AS price, ret_1m, ret_3m, pct_52w_range AS pct_52w "
            "FROM technicals WHERE date = (SELECT MAX(date) FROM technicals)")
    df = df.merge(te, on="ticker", how="left")

    cats = _q("SELECT ticker, type, date FROM catalysts WHERE date >= :a", {"a": today.isoformat()})
    if not cats.empty:
        cats["date"] = pd.to_datetime(cats["date"])
        nxt = cats.sort_values("date").groupby("ticker").first()
        df["next_catalyst_days"] = df["ticker"].map((nxt["date"] - pd.Timestamp(today)).dt.days)
        df["next_catalyst_type"] = df["ticker"].map(nxt["type"])
        binary = cats[cats["type"].isin(["pdufa", "adcom", "phase3_readout", "fda_action"])
                      & (cats["date"] <= pd.Timestamp(today + timedelta(days=90)))]
        df["binary_within_90d"] = df["ticker"].isin(set(binary["ticker"]))
    else:
        df["next_catalyst_days"], df["next_catalyst_type"], df["binary_within_90d"] = \
            np.nan, None, False

    tr = _q("SELECT ticker, phase, status, conditions FROM clinical_trials WHERE status IN "
            "('RECRUITING','ACTIVE_NOT_RECRUITING','NOT_YET_RECRUITING',"
            "'ENROLLING_BY_INVITATION')")
    fda = _q("SELECT DISTINCT ticker FROM fda_events WHERE kind = 'approval' "
             "AND description LIKE 'ORIG%'")
    approved = set(fda["ticker"]) if not fda.empty else set()
    if not tr.empty:
        rank = {"P3": 3, "P2/P3": 2.5, "P2": 2, "P1/P2": 1.5, "P1": 1, "EP1": 0.5}
        tr["r"] = tr["phase"].map(lambda p: rank.get(str(p), 0))
        best = tr.sort_values("r").groupby("ticker").last()
        df["top_phase"] = df["ticker"].map(best["phase"])
        df["n_p3"] = df["ticker"].map(tr[tr["phase"].fillna("").str.contains("P3")]
                                      .groupby("ticker").size()).fillna(0)
        from .process.pos import area_of

        areas = tr.assign(area=tr["conditions"].map(area_of)).groupby("ticker")["area"] \
            .agg(lambda s: set(s))
        df["hot_area"] = df["ticker"].map(lambda t: bool(areas.get(t, set()) & HOT_AREAS))
    else:
        df["top_phase"], df["n_p3"], df["hot_area"] = None, 0, False
    df.loc[df["ticker"].isin(approved), "top_phase"] = "approved"

    try:
        from .process.smart_money import ticker_summary

        sm = ticker_summary()
        sm = sm[sm["ticker"].notna()].groupby("ticker").first()
        df["funds_holding"] = df["ticker"].map(sm["holders"])
        df["funds_net"] = df["ticker"].map(sm["net_flow"])
    except Exception:  # noqa: BLE001
        df["funds_holding"], df["funds_net"] = np.nan, np.nan
    io_ = _q("SELECT ticker, holders, holders_prev FROM inst_ownership WHERE period = "
             "(SELECT MAX(period) FROM inst_ownership)")
    if not io_.empty:
        io_ = io_.set_index("ticker")
        df["holders_13f"] = df["ticker"].map(io_["holders"])
        df["holders_13f_change"] = df["ticker"].map(io_["holders"] - io_["holders_prev"])
    else:
        df["holders_13f"], df["holders_13f_change"] = np.nan, np.nan

    ins = _q("SELECT ticker, SUM(value) AS v FROM insider_txns WHERE code = 'P' "
             "AND txn_date >= :c GROUP BY ticker", {"c": (today - timedelta(days=90)).isoformat()})
    df["insider_buys_90d"] = df["ticker"].map(ins.set_index("ticker")["v"]) if not ins.empty \
        else np.nan

    fl = _q("SELECT ticker, form, filed_date FROM filings WHERE filed_date >= :c",
            {"c": (today - timedelta(days=3 * 365)).isoformat()})
    if not fl.empty:
        fl["filed_date"] = pd.to_datetime(fl["filed_date"])
        shelf = fl[fl["form"].isin(["S-3", "S-3ASR"])]
        rec = fl[fl["form"].str.startswith("424B") & (fl["filed_date"] >= pd.Timestamp(
            today - timedelta(days=90)))]
        f144 = fl[(fl["form"] == "144") & (fl["filed_date"] >= pd.Timestamp(
            today - timedelta(days=90)))]
        df["shelf_active"] = df["ticker"].isin(set(shelf["ticker"]))
        df["raised_90d"] = df["ticker"].isin(set(rec["ticker"]))
        df["form144_90d"] = df["ticker"].map(f144.groupby("ticker").size()).fillna(0)
    else:
        df["shelf_active"], df["raised_90d"], df["form144_90d"] = False, False, 0

    loe = _q("SELECT ticker, MIN(loe_date) AS loe FROM loe_calendar WHERE loe_date >= :a "
             "GROUP BY ticker", {"a": today.isoformat()})
    df["loe_years"] = df["ticker"].map(
        (pd.to_datetime(loe.set_index("ticker")["loe"]) - pd.Timestamp(today)).dt.days / 365.25) \
        if not loe.empty else np.nan
    ga = _q("SELECT ticker, SUM(amount) AS a FROM gov_awards GROUP BY ticker")
    df["gov_awards"] = df["ticker"].map(ga.set_index("ticker")["a"]) if not ga.empty else np.nan

    df["dilution_risk"] = dilution_risk(df)
    df["takeout_score"] = takeout_score(df)
    return df


def dilution_risk(df: pd.DataFrame) -> pd.Series:
    rw = df["runway_quarters"]
    need = np.where(rw < 4, 0.4, np.where(rw < 8, 0.2, 0.0))
    need = np.where(rw.isna(), 0.1, need)
    cap = np.where(df["shelf_active"], 0.2, 0.0)
    over = np.clip(df["warrant_overhang"].fillna(0) * 1.5, 0, 0.2) + \
        np.clip(df["option_overhang"].fillna(0) * 0.5, 0, 0.05)
    recent = np.where(df["raised_90d"], 0.1, 0.0)
    f144 = np.clip(df["form144_90d"].fillna(0) * 0.02, 0, 0.05)
    return pd.Series(np.clip(need + cap + over + recent + f144, 0, 1), index=df.index).round(3)


def takeout_score(df: pd.DataFrame) -> pd.Series:
    mc = df["market_cap"]
    s = np.where(mc.between(5e8, 15e9), 0.2, np.where(mc.between(3e8, 3e10), 0.08, 0.0))
    s = s + np.where(df["top_phase"].isin(["P3", "P2/P3", "approved"]), 0.2, 0.0)
    s = s + np.where(df.get("hot_area", False).fillna(False).astype(bool), 0.15, 0.0) \
        if "hot_area" in df else s
    s = s + np.clip(df["funds_net"].fillna(0) * 0.05, 0, 0.15)
    s = s + np.where(df["runway_quarters"] >= 8, 0.1, 0.0)
    s = s + np.where(~df["raised_90d"].fillna(False).astype(bool), 0.1, 0.0)
    s = s + np.where(df["pct_52w"] <= 0.6, 0.1, 0.0)
    return pd.Series(np.clip(s, 0, 1), index=df.index).round(3)


# ---------------------------------------------------------------- filters
def apply(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    for f in filters or []:
        col, op, v = f.get("field"), f.get("op"), f.get("value")
        if col not in df:
            continue
        s = df[col]
        if op == ">=":
            m &= pd.to_numeric(s, errors="coerce") >= float(v)
        elif op == "<=":
            m &= pd.to_numeric(s, errors="coerce") <= float(v)
        elif op == "between" and isinstance(v, (list, tuple)) and len(v) == 2:
            x = pd.to_numeric(s, errors="coerce")
            m &= (x >= float(v[0])) & (x <= float(v[1]))
        elif op == "is":
            m &= s.fillna(False).astype(bool) == bool(v)
        elif op == "in":
            m &= s.isin(list(v) if isinstance(v, (list, tuple, set)) else [v])
    return df[m]


# ---------------------------------------------------------------- saved screens
def list_screens() -> pd.DataFrame:
    return _q("SELECT * FROM screens ORDER BY name")


def save_screen(name: str, filters: list[dict], alert: bool = False,
                sid: str | None = None) -> str:
    from .db import bulk_upsert, screens

    now = datetime.now(timezone.utc)
    sid = sid or uuid.uuid4().hex[:12]
    members = apply(frame(), filters)["ticker"].tolist() if alert else []
    bulk_upsert(screens, [{"id": sid, "name": name[:80], "filters": json.dumps(filters),
                           "alert": int(bool(alert)), "members": json.dumps(members),
                           "created_at": now, "updated_at": now}])
    return sid


def delete_screen(sid: str) -> None:
    from .db import get_engine, screens

    with get_engine().begin() as conn:
        conn.execute(screens.delete().where(screens.c.id == sid))


_PENDING: dict[str, list[str]] = {}


@register("screen")
def _alerts(rules: dict) -> list[dict]:
    """New names entering an alerting screen since the last alert run. Pure: the
    new memberships are only written by ``_commit`` after alerts.run() persists."""
    sc = list_screens()
    if sc.empty or not sc["alert"].fillna(0).astype(int).any():
        return []
    df = frame()
    out = []
    _PENDING.clear()
    for r in sc[sc["alert"].fillna(0).astype(int) == 1].itertuples():
        try:
            filters = json.loads(r.filters or "[]")
            before = set(json.loads(r.members or "[]"))
        except (TypeError, ValueError):
            continue
        now_in = apply(df, filters)["ticker"].tolist()
        _PENDING[r.id] = now_in
        for t in sorted(set(now_in) - before):
            out.append({"kind": "screen", "ticker": t, "key": f"{r.id}|{date.today()}",
                        "detail": f"entered screen '{r.name}'", "weight": 0.8})
    return out


def _commit() -> None:
    from .db import bulk_upsert, screens

    rows = [{"id": sid, "members": json.dumps(m), "updated_at": datetime.now(timezone.utc)}
            for sid, m in _PENDING.items()]
    if rows:
        bulk_upsert(screens, rows, update_only=["members", "updated_at"])
    _PENDING.clear()


_alerts.commit = _commit
