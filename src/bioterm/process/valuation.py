"""Risk-adjusted NPV per molecule and a sum-of-the-parts per company.

rNPV = PoS x NPV of the commercial cash flows - (1 - PoS weighting aside) the
remaining development cost, both discounted to today:

    sales    linear ramp from launch to peak over ``ramp_years``, flat until the
             loss of exclusivity, then ``erosion`` of sales lost per year after
    cash     sales x operating margin x (1 - tax); a partnered asset keeps only
             ``royalty`` of sales instead
    PoS      default = likelihood of approval from the current phase in the
             molecule's disease area (BIO/Informa/QLS 2011-2020, pos_priors.yml)

Everything is an input the owner edits on the Molecules page; nothing here is a
forecast - it makes the assumptions behind a price explicit and comparable.

SOTP per share = (sum of rNPVs + cash - debt) / shares outstanding.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

DEFAULTS = {"peak_sales": 500e6, "launch_year": date.today().year + 3, "ramp_years": 5,
            "loe_year": date.today().year + 15, "margin": 0.45, "tax": 0.21,
            "royalty": None, "discount": 0.11, "erosion": 0.6, "dev_cost": 150e6,
            "dev_years": 2, "pos": None}


@dataclass
class Inputs:
    peak_sales: float = DEFAULTS["peak_sales"]
    launch_year: int = DEFAULTS["launch_year"]
    ramp_years: int = DEFAULTS["ramp_years"]
    loe_year: int = DEFAULTS["loe_year"]
    margin: float = DEFAULTS["margin"]
    tax: float = DEFAULTS["tax"]
    royalty: float | None = None          # e.g. 0.12 for a 12% royalty (partnered)
    discount: float = DEFAULTS["discount"]
    erosion: float = DEFAULTS["erosion"]  # share of sales lost each year after LOE
    dev_cost: float = DEFAULTS["dev_cost"]  # remaining R&D to approval (total)
    dev_years: int = DEFAULTS["dev_years"]
    pos: float | None = None              # None -> the phase/area prior
    extra: dict = field(default_factory=dict)


def sales_curve(i: Inputs, start: int, end: int) -> dict[int, float]:
    out = {}
    for y in range(start, end + 1):
        if y < i.launch_year:
            s = 0.0
        elif y < i.launch_year + max(1, i.ramp_years):
            s = i.peak_sales * (y - i.launch_year + 1) / max(1, i.ramp_years)
        elif y <= i.loe_year:
            s = i.peak_sales
        else:
            s = i.peak_sales * (1 - i.erosion) ** (y - i.loe_year)
        out[y] = s
    return out


def rnpv(i: Inputs, pos: float, today: date | None = None, horizon: int = 25) -> dict[str, Any]:
    today = today or date.today()
    y0 = today.year
    curve = sales_curve(i, y0, y0 + horizon)
    npv_comm = 0.0
    for y, s in curve.items():
        t = y - y0 + 0.5                       # mid-year convention
        cash = s * i.royalty if i.royalty else s * i.margin * (1 - i.tax)
        npv_comm += cash / (1 + i.discount) ** t
    per_year = i.dev_cost / max(1, i.dev_years)
    npv_dev = sum(per_year / (1 + i.discount) ** (k + 0.5) for k in range(max(1, i.dev_years)))
    value = pos * npv_comm - npv_dev
    return {"rnpv": value, "npv_commercial": npv_comm, "npv_dev_cost": npv_dev, "pos": pos,
            "peak_sales": i.peak_sales, "launch_year": i.launch_year,
            "sales": {str(k): round(v) for k, v in curve.items() if v}}


def default_pos(molecule_id: str) -> tuple[float | None, str | None, str | None]:
    """(PoS, phase, area) from the molecule's most advanced active trial."""
    from ..db import read_sql
    from .pos import area_of, loa

    tr = read_sql("SELECT phase, conditions, status FROM molecule_trials WHERE molecule_id = :m",
                  {"m": molecule_id})
    if tr.empty:
        return None, None, None
    order = {"P3": 3, "P2/P3": 2.5, "P2": 2, "P1/P2": 1.5, "P1": 1, "EP1": 0.5}
    tr["rank"] = tr["phase"].map(lambda p: order.get(str(p), 0))
    top = tr.sort_values("rank", ascending=False).iloc[0]
    return loa(top["phase"], top["conditions"]), top["phase"], area_of(top["conditions"])


def load(molecule_id: str) -> tuple[Inputs, dict | None]:
    from ..db import read_sql

    df = read_sql("SELECT inputs, result FROM molecule_valuations WHERE molecule_id = :m",
                  {"m": molecule_id})
    if df.empty:
        return Inputs(), None
    raw = json.loads(df.iloc[0]["inputs"] or "{}")
    known = {k: v for k, v in raw.items() if k in Inputs.__dataclass_fields__}
    return Inputs(**known), json.loads(df.iloc[0]["result"] or "null")


def save(molecule_id: str, i: Inputs) -> dict[str, Any]:
    from ..db import bulk_upsert, molecule_valuations

    pos = i.pos
    if pos is None:
        pos, _, _ = default_pos(molecule_id)
    res = rnpv(i, pos if pos is not None else 0.1)
    bulk_upsert(molecule_valuations, [{"molecule_id": molecule_id,
                                       "inputs": json.dumps(asdict(i)),
                                       "result": json.dumps(res),
                                       "updated_at": datetime.now(timezone.utc)}])
    return res


def sotp(ticker: str) -> dict[str, Any] | None:
    """Sum of the parts from the saved molecule valuations + the balance sheet."""
    from ..db import read_sql

    v = read_sql("SELECT m.id, m.name, v.result FROM molecules m JOIN molecule_valuations v "
                 "ON v.molecule_id = m.id WHERE m.ticker = :t", {"t": ticker})
    if v.empty:
        return None
    parts = []
    for r in v.itertuples():
        res = json.loads(r.result or "{}")
        parts.append({"molecule": r.name, "rnpv": float(res.get("rnpv") or 0),
                      "pos": res.get("pos"), "peak_sales": res.get("peak_sales")})
    f = read_sql("SELECT cash, total_debt, shares_out, xbrl_shares_out, market_cap "
                 "FROM fundamentals WHERE ticker = :t", {"t": ticker})
    cash = float(f.iloc[0]["cash"] or 0) if not f.empty else 0.0
    debt = float(f.iloc[0]["total_debt"] or 0) if not f.empty and f.iloc[0]["total_debt"] else 0.0
    shares = None
    if not f.empty:
        shares = f.iloc[0]["shares_out"] or f.iloc[0]["xbrl_shares_out"]
    total = sum(p["rnpv"] for p in parts) + cash - debt
    return {"parts": parts, "cash": cash, "debt": debt, "equity_value": total,
            "per_share": total / float(shares) if shares else None,
            "market_cap": float(f.iloc[0]["market_cap"]) if not f.empty and
            f.iloc[0]["market_cap"] else None}
