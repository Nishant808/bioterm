"""Quarter-over-quarter position changes of biotech specialist funds (13F).

Pure reads over ``inst_holdings`` - shared by the signal engine and the Smart
money page. Each fund is compared with its *own* previous quarter, so a fund
that has already filed the new quarter is never diffed against one that hasn't.
"""
from __future__ import annotations

import pandas as pd

from ..db import read_sql

STATUS_ORDER = ["new", "added", "held", "trimmed", "exited"]


def load_holdings() -> pd.DataFrame:
    df = read_sql(
        "SELECT h.cik, h.period, h.filed_date, h.cusip, h.issuer, h.ticker, h.shares, "
        "h.value, COALESCE(f.short_name, f.name, h.cik) AS fund "
        "FROM inst_holdings h LEFT JOIN inst_filers f ON f.cik = h.cik")
    if not df.empty:
        df["period"] = pd.to_datetime(df["period"])
        df["filed_date"] = pd.to_datetime(df["filed_date"], errors="coerce")
    return df


def classify(shares0: float, shares1: float, band: float = 0.2) -> str:
    if shares0 <= 0 and shares1 > 0:
        return "new"
    if shares1 <= 0 and shares0 > 0:
        return "exited"
    chg = (shares1 - shares0) / shares0 if shares0 > 0 else 0.0
    if chg >= band:
        return "added"
    if chg <= -band:
        return "trimmed"
    return "held"


def usable_periods(g: pd.DataFrame, newest: pd.Timestamp | None = None,
                   max_lag_days: int = 200) -> list:
    """A fund's quarters worth diffing, newest first.

    Two things would otherwise read as a fund dumping its whole book: a fund
    that stopped filing (its "latest" quarter is years old), and a filing that
    lists almost nothing (a combination/notice report, a stub amendment).
    Quarters with under a quarter of the fund's typical position count are
    skipped, and a fund whose newest usable quarter trails the newest quarter
    on file by more than ``max_lag_days`` is dropped entirely.
    """
    n = g.groupby("period").size()
    typical = float(n.median()) if len(n) else 0.0
    ok = sorted([p for p, k in n.items() if k >= max(1.0, 0.25 * typical)], reverse=True)
    if ok and newest is not None and (newest - ok[0]).days > max_lag_days:
        return []
    return ok


def fund_changes(h: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (fund, security): the latest quarter vs the one before."""
    h = load_holdings() if h is None else h
    cols = ["cik", "fund", "cusip", "issuer", "ticker", "period", "prev_period",
            "shares0", "shares1", "value1", "pct_change", "status", "filed_date"]
    if h.empty:
        return pd.DataFrame(columns=cols)
    out = []
    newest = h["period"].max()
    for cik, g in h.groupby("cik"):
        periods = usable_periods(g, newest)
        if not periods:
            continue
        p1 = periods[0]
        p0 = periods[1] if len(periods) > 1 else None
        cur = g[g["period"] == p1].set_index("cusip")
        prev = g[g["period"] == p0].set_index("cusip") if p0 is not None else cur.iloc[0:0]
        for cusip in cur.index.union(prev.index):
            c = cur.loc[cusip] if cusip in cur.index else None
            p = prev.loc[cusip] if cusip in prev.index else None
            s1 = float(c["shares"]) if c is not None else 0.0
            s0 = float(p["shares"]) if p is not None else (s1 if p0 is None else 0.0)
            ref = c if c is not None else p
            out.append({
                "cik": cik, "fund": ref["fund"], "cusip": cusip, "issuer": ref["issuer"],
                "ticker": ref["ticker"], "period": p1, "prev_period": p0,
                "shares0": s0, "shares1": s1,
                "value1": float(c["value"]) if c is not None else 0.0,
                "pct_change": ((s1 - s0) / s0) if s0 > 0 else None,
                "status": classify(s0, s1) if p0 is not None else "held",
                "filed_date": ref["filed_date"],
            })
    return pd.DataFrame(out, columns=cols)


def ticker_summary(ch: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per security: how many tracked specialists hold it and what they did."""
    ch = fund_changes() if ch is None else ch
    cols = ["key", "ticker", "issuer", "holders", "new", "added", "held", "trimmed",
            "exited", "value", "net_flow", "funds_buying", "funds_selling", "period", "filed"]
    if ch.empty:
        return pd.DataFrame(columns=cols)
    ch = ch.copy()
    ch["key"] = ch["ticker"].fillna(ch["cusip"])
    rows = []
    for key, g in ch.groupby("key"):
        st = g["status"].value_counts()
        buying = g[g["status"].isin(["new", "added"])]["fund"].tolist()
        selling = g[g["status"].isin(["exited", "trimmed"])]["fund"].tolist()
        rows.append({
            "key": key,
            "ticker": g["ticker"].dropna().iloc[0] if g["ticker"].notna().any() else None,
            "issuer": g["issuer"].iloc[0],
            "holders": int((g["shares1"] > 0).sum()),
            **{s: int(st.get(s, 0)) for s in STATUS_ORDER},
            "value": float(g["value1"].sum()),
            "net_flow": int(st.get("new", 0) + st.get("added", 0)
                            - st.get("exited", 0) - st.get("trimmed", 0)),
            "funds_buying": sorted(set(buying)), "funds_selling": sorted(set(selling)),
            "period": g["period"].max(),
            "filed": pd.to_datetime(g["filed_date"], errors="coerce").max(),
        })
    return pd.DataFrame(rows, columns=cols).sort_values(
        ["net_flow", "holders"], ascending=False).reset_index(drop=True)
