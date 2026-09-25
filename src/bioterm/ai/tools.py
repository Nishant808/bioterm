"""Copilot tools: read-only lookups over the BioTerm database (+ live quotes and
SEC documents). Every row that has a link gets a ``ref`` number from the
conversation's ``Sources`` registry; the model cites claims as ``[n]`` and the
UI lists the sources underneath the answer.

Tool results are compact JSON (bounded rows, trimmed text) - the model reads
them, the user never sees them raw.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

MAX_RESULT_CHARS = 14000


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., Any]


@dataclass
class Sources:
    items: list[dict[str, Any]] = field(default_factory=list)
    _by_url: dict[str, int] = field(default_factory=dict)

    def ref(self, url: Any, title: Any, kind: str, when: Any = None) -> int | None:
        u = str(url or "").strip()
        if not u.startswith(("http://", "https://")):
            return None
        if u in self._by_url:
            return self._by_url[u]
        n = len(self.items) + 1
        self.items.append({"n": n, "url": u, "title": _clip(str(title or u), 160),
                           "kind": kind, "date": _d(when)})
        self._by_url[u] = n
        return n

    def cited(self, text: str) -> list[dict[str, Any]]:
        nums = {int(m) for m in re.findall(r"\[(\d{1,3})\]", text or "")}
        return [s for s in self.items if s["n"] in nums]


# ---------------------------------------------------------------- validation
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
          "array": list, "object": dict}


def validate(value: Any, schema: dict, path: str = "input") -> str | None:
    """Check a tool input against the (small) JSON-Schema subset these tools
    use. Returns an error message, or None when valid."""
    t = schema.get("type")
    if isinstance(t, list):
        if value is None and "null" in t:
            return None
        t = next((x for x in t if x != "null"), None)
    if t:
        py = _TYPES.get(t)
        if py is not None:
            if t in ("integer", "number") and isinstance(value, bool):
                return f"{path}: expected {t}"
            if not isinstance(value, py):
                return f"{path}: expected {t}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: must be one of {schema['enum']}"
    if t in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path}: below {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path}: above {schema['maximum']}"
    if t == "string" and "maxLength" in schema and len(value) > schema["maxLength"]:
        return f"{path}: longer than {schema['maxLength']}"
    if t == "array":
        for i, v in enumerate(value):
            err = validate(v, schema.get("items") or {}, f"{path}[{i}]")
            if err:
                return err
    if t == "object":
        props = schema.get("properties") or {}
        for k in schema.get("required") or []:
            if k not in value:
                return f"{path}: missing '{k}'"
        for k, v in value.items():
            if k not in props:
                if schema.get("additionalProperties") is False:
                    return f"{path}: unexpected '{k}'"
                continue
            err = validate(v, props[k], f"{path}.{k}")
            if err:
                return err
    return None


# ---------------------------------------------------------------- helpers
def _clip(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _d(v) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        ts = pd.Timestamp(v)
    except (ValueError, TypeError):
        return str(v)
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _num(v, digits: int = 3):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    from ..db import read_sql

    try:
        return read_sql(sql, params or {})
    except Exception:  # noqa: BLE001 - a missing table on an older database
        return pd.DataFrame()


def _tk(t: str) -> str:
    return re.sub(r"[^A-Z0-9.\-]", "", str(t or "").upper())[:12]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _ts_cut(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _jloads(v, default=None):
    try:
        return json.loads(v) if isinstance(v, str) and v else (v if v is not None else default)
    except (TypeError, ValueError):
        return default


def dump(obj: Any) -> str:
    s = json.dumps(obj, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(s) > MAX_RESULT_CHARS:
        s = s[:MAX_RESULT_CHARS] + '..."[truncated]"'
    return s


# ---------------------------------------------------------------- tools
def find_companies(src: Sources, query: str, limit: int = 10):
    q = f"%{query.strip().lower()}%"
    df = _q("SELECT s.ticker, s.name, s.in_xbi, s.is_watchlist, s.tier, f.market_cap "
            "FROM securities s LEFT JOIN fundamentals f ON f.ticker = s.ticker "
            "WHERE LOWER(s.ticker) LIKE :q OR LOWER(s.name) LIKE :q "
            "ORDER BY f.market_cap DESC LIMIT :n", {"q": q, "n": limit})
    mol = _q("SELECT ticker, name, indication FROM molecules "
             "WHERE LOWER(name) LIKE :q OR LOWER(aliases) LIKE :q OR LOWER(indication) LIKE :q "
             "LIMIT :n", {"q": q, "n": limit})
    return {"companies": [{"ticker": r.ticker, "name": r.name, "in_xbi": bool(r.in_xbi),
                           "watchlist": bool(r.is_watchlist), "tier": r.tier,
                           "market_cap": _num(r.market_cap, 0)} for r in df.itertuples()],
            "molecules": [{"ticker": r.ticker, "molecule": r.name, "indication": r.indication}
                          for r in mol.itertuples()]}


def company_snapshot(src: Sources, ticker: str):
    t = _tk(ticker)
    sec = _q("SELECT * FROM securities WHERE ticker = :t", {"t": t})
    if sec.empty:
        return {"error": f"{t} is not in the BioTerm universe"}
    out: dict[str, Any] = {"ticker": t, "name": sec.iloc[0]["name"],
                           "in_xbi": bool(sec.iloc[0].get("in_xbi")),
                           "tier": sec.iloc[0].get("tier")}
    try:
        from ..quotes import quote

        qt = quote(t)
        if qt:
            out["quote"] = {"price": _num(qt["price"], 2), "change_pct": _num(qt["change_pct"], 4),
                            "asof": str(qt.get("asof")), "source": qt.get("provider")}
    except Exception:  # noqa: BLE001
        pass
    f = _q("SELECT * FROM fundamentals WHERE ticker = :t", {"t": t})
    if not f.empty:
        r = f.iloc[0]
        cash, mcap, debt = _num(r.get("cash"), 0), _num(r.get("market_cap"), 0), \
            _num(r.get("total_debt"), 0)
        out["fundamentals"] = {
            "market_cap": mcap, "cash": cash, "total_debt": debt,
            "enterprise_value": (mcap - (cash or 0) + (debt or 0)) if mcap else None,
            "annual_burn": _num(r.get("burn_ttm"), 0),
            "runway_quarters": _num(r.get("runway_quarters"), 1),
            "short_pct_float": _num(r.get("short_percent_float"), 4),
            "days_to_cover": _num(r.get("short_ratio"), 2),
            "warrants_out": _num(r.get("warrants_out"), 0),
            "next_earnings": _d(r.get("next_earnings_date")),
            "updated": _d(r.get("updated_at"))}
    s = _q("SELECT * FROM scores WHERE ticker = :t ORDER BY asof DESC LIMIT 1", {"t": t})
    if not s.empty:
        r = s.iloc[0]
        out["focus"] = {"asof": _d(r["asof"]), "rank": int(r["rank"]) if pd.notna(r["rank"])
                        else None, "score": _num(r["focus_score"]),
                        "momentum": _num(r["momentum"]), "catalyst": _num(r["catalyst"]),
                        "newsflow": _num(r["newsflow"]), "risk": _num(r["risk"])}
    sg = _q("SELECT * FROM signal_scores WHERE ticker = :t ORDER BY asof DESC LIMIT 1",
            {"t": t})
    if not sg.empty:
        r = sg.iloc[0]
        out["signal"] = {"asof": _d(r["asof"]), "label": r["label"], "net": _num(r["net"]),
                         "bull": _num(r["bull"]), "bear": _num(r["bear"]),
                         "regime": r.get("regime"),
                         "top_evidence": [
                             {"side": e.get("side"), "detector": e.get("code"),
                              "strength": _num(e.get("strength")), "what": e.get("title")}
                             for e in (_jloads(r.get("top"), []) or [])[:6]]}
    w = _q("SELECT conviction, thesis FROM watchlist WHERE ticker = :t", {"t": t})
    if not w.empty:
        out["watchlist"] = {"conviction": int(w.iloc[0]["conviction"] or 3),
                            "thesis": _clip(w.iloc[0]["thesis"] or "", 400)}
    tech = _q("SELECT * FROM technicals WHERE ticker = :t ORDER BY date DESC LIMIT 1", {"t": t})
    if not tech.empty:
        r = tech.iloc[0]
        out["technicals"] = {"date": _d(r["date"]), "ret_1m": _num(r["ret_1m"]),
                             "ret_3m": _num(r["ret_3m"]), "ret_6m": _num(r["ret_6m"]),
                             "rsi14": _num(r["rsi14"], 1),
                             "pct_52w_range": _num(r["pct_52w_range"])}
    out["next_catalysts"] = upcoming_catalysts(src, ticker=t, days_ahead=365, limit=4)["catalysts"]
    return out


def upcoming_catalysts(src: Sources, ticker: str | None = None, days_ahead: int = 120,
                       limit: int = 30):
    today = _today()
    params = {"a": today.isoformat(), "b": (today + timedelta(days=days_ahead)).isoformat(),
              "n": limit}
    where = "date >= :a AND date <= :b"
    if ticker:
        where += " AND ticker = :t"
        params["t"] = _tk(ticker)
    df = _q(f"SELECT ticker, type, title, date, confidence, source, url FROM catalysts "
            f"WHERE {where} ORDER BY date LIMIT :n", params)
    rows = []
    for r in df.itertuples():
        rows.append({"ticker": r.ticker, "date": _d(r.date), "type": r.type,
                     "title": _clip(r.title, 200), "confidence": r.confidence,
                     "source": r.source, "ref": src.ref(r.url, r.title, "catalyst", r.date)})
    return {"today": today.isoformat(), "catalysts": rows}


def clinical_trials(src: Sources, ticker: str, include_completed: bool = False,
                    limit: int = 25):
    t = _tk(ticker)
    where = "ticker = :t"
    if not include_completed:
        where += (" AND status IN ('RECRUITING','ACTIVE_NOT_RECRUITING','NOT_YET_RECRUITING',"
                  "'ENROLLING_BY_INVITATION','SUSPENDED')")
    df = _q(f"SELECT nct_id, title, phase, status, primary_completion_date, conditions, "
            f"enrollment, url FROM clinical_trials WHERE {where} "
            f"ORDER BY primary_completion_date LIMIT :n", {"t": t, "n": limit})
    ch = _q("SELECT nct_id, field, old, new, kind, days, detected_at FROM trial_changes "
            "WHERE ticker = :t ORDER BY detected_at DESC LIMIT 15", {"t": t})
    return {"trials": [{"nct_id": r.nct_id, "title": _clip(r.title, 160), "phase": r.phase,
                        "status": r.status, "primary_completion": _d(r.primary_completion_date),
                        "conditions": _clip(r.conditions, 120),
                        "enrollment": _num(r.enrollment, 0),
                        "ref": src.ref(r.url, f"{r.nct_id}: {r.title}", "trial")}
                       for r in df.itertuples()],
            "recent_changes": [{"nct_id": r.nct_id, "field": r.field, "old": r.old, "new": r.new,
                                "kind": r.kind, "days": _num(r.days, 0),
                                "detected": _d(r.detected_at)} for r in ch.itertuples()]}


def sec_filings(src: Sources, ticker: str, forms: list[str] | None = None, days: int = 120,
                limit: int = 25):
    t = _tk(ticker)
    params: dict[str, Any] = {"t": t, "c": (_today() - timedelta(days=days)).isoformat(),
                              "n": limit}
    where = "f.ticker = :t AND f.filed_date >= :c"
    if forms:
        ph = ",".join(f":f{i}" for i in range(len(forms)))
        where += f" AND f.form IN ({ph})"
        params.update({f"f{i}": str(x).upper()[:16] for i, x in enumerate(forms)})
    df = _q(f"SELECT f.id, f.form, f.filed_date, f.title, f.items, f.url, s.summary "
            f"FROM filings f LEFT JOIN filing_summaries s ON s.accession = f.id "
            f"WHERE {where} ORDER BY f.filed_date DESC LIMIT :n", params)
    return {"filings": [{"accession": r.id, "form": r.form, "filed": _d(r.filed_date),
                         "title": _clip(r.title, 160), "items": r.items,
                         "summary": _clip(r.summary, 600) if isinstance(r.summary, str) else None,
                         "url": r.url,
                         "ref": src.ref(r.url, f"{t} {r.form} {_d(r.filed_date)}", "filing",
                                        r.filed_date)}
                        for r in df.itertuples()]}


def read_sec_document(src: Sources, url: str, query: str | None = None,
                      max_chars: int = 12000):
    if not re.match(r"^https://www\.sec\.gov/", url or ""):
        return {"error": "only https://www.sec.gov/ documents can be read"}
    from ..httpx_util import get_bytes
    from ..util import strip_markup

    raw = get_bytes(url, min_interval=0.15, retries=2, timeout=20)
    text = strip_markup(raw[:3_000_000].decode("utf-8", "ignore"))
    text = re.sub(r"\s+", " ", text)
    ref = src.ref(url, url.rsplit("/", 1)[-1], "document")
    if query:
        terms = [w for w in re.findall(r"\w{3,}", query.lower())][:6]
        hits = []
        for m in re.finditer("|".join(map(re.escape, terms)) or "$^", text.lower()):
            a = max(0, m.start() - 600)
            if hits and a < hits[-1][1]:
                continue
            hits.append((a, min(len(text), m.end() + 900)))
            if len(hits) >= 8:
                break
        passages = [text[a:b] for a, b in hits]
        return {"ref": ref, "length": len(text), "passages": passages}
    return {"ref": ref, "length": len(text), "text": text[:max_chars]}


def news_headlines(src: Sources, ticker: str | None = None, days: int = 14,
                   query: str | None = None, limit: int = 25):
    params: dict[str, Any] = {"c": _ts_cut(days), "n": limit}
    where = "n.published >= :c"
    if ticker:
        where += " AND (n.ticker = :t OR n.tickers_csv LIKE :tl)"
        params.update({"t": _tk(ticker), "tl": f"%{_tk(ticker)}%"})
    if query:
        where += " AND (LOWER(n.title) LIKE :q OR LOWER(n.summary) LIKE :q)"
        params["q"] = f"%{query.lower()}%"
    df = _q(f"SELECT n.id, n.ticker, n.title, n.url, n.source, n.published, n.sentiment, "
            f"n.event_tags, l.event_type, l.outcome, l.summary AS llm_summary "
            f"FROM news n LEFT JOIN news_llm l ON l.id = n.id "
            f"WHERE {where} ORDER BY n.published DESC LIMIT :n", params)
    return {"headlines": [{"ticker": r.ticker, "published": str(r.published)[:16],
                           "title": _clip(r.title, 200), "source": r.source,
                           "tone": _num(r.sentiment, 2), "tags": r.event_tags,
                           "event": r.event_type if isinstance(r.event_type, str) else None,
                           "outcome": r.outcome if isinstance(r.outcome, str) else None,
                           "ref": src.ref(r.url, r.title, "news", r.published)}
                          for r in df.itertuples()]}


def insider_activity(src: Sources, ticker: str, days: int = 365):
    t = _tk(ticker)
    df = _q("SELECT txn_date, owner, role, code, shares, price, value, plan_10b5_1, url "
            "FROM insider_txns WHERE ticker = :t AND txn_date >= :c AND code IN ('P','S') "
            "ORDER BY txn_date DESC LIMIT 40",
            {"t": t, "c": (_today() - timedelta(days=days)).isoformat()})
    buys = df[df["code"] == "P"] if not df.empty else df
    sells = df[df["code"] == "S"] if not df.empty else df
    return {"open_market_buys_usd": _num(buys["value"].abs().sum(), 0) if not df.empty else 0,
            "open_market_sells_usd": _num(sells["value"].abs().sum(), 0) if not df.empty else 0,
            "transactions": [{"date": _d(r.txn_date), "insider": r.owner, "role": r.role,
                              "type": "buy" if r.code == "P" else "sell",
                              "shares": _num(r.shares, 0), "price": _num(r.price, 2),
                              "value": _num(r.value, 0),
                              "10b5_1_plan": bool(r.plan_10b5_1) if pd.notna(r.plan_10b5_1)
                              else None,
                              "ref": src.ref(r.url, f"Form 4 {r.owner}", "insider", r.txn_date)}
                             for r in df.head(25).itertuples()]}


def fund_ownership(src: Sources, ticker: str):
    t = _tk(ticker)
    df = _q("SELECT h.period, h.cik, f.short_name, f.name, h.shares, h.value, h.filed_date "
            "FROM inst_holdings h LEFT JOIN inst_filers f ON f.cik = h.cik "
            "WHERE h.ticker = :t ORDER BY h.period DESC", {"t": t})
    out: dict[str, Any] = {"note": "Specialist biotech funds tracked from 13F-HR filings; "
                                   "positions are as of quarter-end, filed up to 45 days later."}
    if not df.empty:
        periods = sorted(df["period"].astype(str).unique(), reverse=True)
        cur = df[df["period"].astype(str) == periods[0]]
        prev = df[df["period"].astype(str) == periods[1]] if len(periods) > 1 else df.iloc[0:0]
        pmap = dict(zip(prev["cik"], prev["shares"]))
        out["period"] = periods[0]
        out["holders"] = [{"fund": r.short_name or r.name, "shares": _num(r.shares, 0),
                           "value_usd": _num(r.value, 0),
                           "change_vs_prior_q": (_num(r.shares - pmap[r.cik], 0)
                                                 if r.cik in pmap else "new position")}
                          for r in cur.sort_values("value", ascending=False).itertuples()]
        gone = set(pmap) - set(cur["cik"])
        out["exited"] = [str(n) for n in prev[prev["cik"].isin(gone)]["short_name"].tolist()]
    wm = _q("SELECT * FROM inst_ownership WHERE ticker = :t ORDER BY period DESC LIMIT 2",
            {"t": t})
    if not wm.empty:
        r = wm.iloc[0]
        out["all_13f_filers"] = {"period": _d(r["period"]), "holders": _num(r["holders"], 0),
                                 "holders_prev": _num(r["holders_prev"], 0),
                                 "shares": _num(r["shares"], 0),
                                 "shares_prev": _num(r["shares_prev"], 0),
                                 "new_holders": _num(r["new_holders"], 0),
                                 "exited_holders": _num(r["exited_holders"], 0)}
    return out


def signal_board(src: Sources, label: str | None = None, limit: int = 25):
    params: dict[str, Any] = {"n": limit}
    where = "s.asof = (SELECT MAX(asof) FROM signal_scores)"
    if label:
        where += " AND s.label = :l"
        params["l"] = label
    df = _q(f"SELECT s.ticker, u.name, s.label, s.net, s.asof, s.top, s.regime "
            f"FROM signal_scores s JOIN securities u ON u.ticker = s.ticker WHERE {where} "
            f"ORDER BY ABS(s.net) DESC LIMIT :n", params)
    return {"asof": _d(df["asof"].iloc[0]) if not df.empty else None,
            "regime": df["regime"].iloc[0] if not df.empty else None,
            "note": "Screening states from BioTerm's detector engine, not recommendations.",
            "calls": [{"ticker": r.ticker, "name": r.name, "label": r.label, "net": _num(r.net),
                       "evidence": [e.get("title") for e in (_jloads(r.top, []) or [])[:3]]}
                      for r in df.itertuples()]}


def screen_universe(src: Sources, max_market_cap: float | None = None,
                    min_market_cap: float | None = None,
                    max_runway_quarters: float | None = None,
                    below_cash: bool | None = None, signal_labels: list[str] | None = None,
                    catalyst_within_days: int | None = None,
                    min_short_pct_float: float | None = None, limit: int = 40):
    df = _q("SELECT s.ticker, s.name, f.market_cap, f.cash, f.total_debt, f.runway_quarters, "
            "f.short_percent_float FROM securities s "
            "LEFT JOIN fundamentals f ON f.ticker = s.ticker")
    if df.empty:
        return {"matches": []}
    sig = _q("SELECT ticker, label, net FROM signal_scores "
             "WHERE asof = (SELECT MAX(asof) FROM signal_scores)")
    df = df.merge(sig, on="ticker", how="left")
    today = _today()
    cat = _q("SELECT ticker, MIN(date) AS next_cat FROM catalysts WHERE date >= :a "
             "GROUP BY ticker", {"a": today.isoformat()})
    df = df.merge(cat, on="ticker", how="left")
    df["ev"] = df["market_cap"] - df["cash"].fillna(0) + df["total_debt"].fillna(0)
    m = pd.Series(True, index=df.index)
    if max_market_cap is not None:
        m &= df["market_cap"] <= max_market_cap
    if min_market_cap is not None:
        m &= df["market_cap"] >= min_market_cap
    if max_runway_quarters is not None:
        m &= df["runway_quarters"] <= max_runway_quarters
    if below_cash:
        m &= df["ev"] < 0
    if signal_labels:
        m &= df["label"].isin(signal_labels)
    if min_short_pct_float is not None:
        m &= df["short_percent_float"] >= min_short_pct_float
    if catalyst_within_days is not None:
        nc = pd.to_datetime(df["next_cat"], errors="coerce")
        m &= nc <= pd.Timestamp(today + timedelta(days=catalyst_within_days))
    res = df[m].sort_values("market_cap", ascending=False).head(limit)
    return {"count": int(m.sum()),
            "matches": [{"ticker": r.ticker, "name": r.name, "market_cap": _num(r.market_cap, 0),
                         "cash": _num(r.cash, 0), "enterprise_value": _num(r.ev, 0),
                         "runway_quarters": _num(r.runway_quarters, 1),
                         "short_pct_float": _num(r.short_percent_float, 4),
                         "signal": r.label if isinstance(r.label, str) else None,
                         "next_catalyst": _d(r.next_cat)} for r in res.itertuples()]}


def price_summary(src: Sources, ticker: str, days: int = 365):
    t = _tk(ticker)
    df = _q("SELECT date, close, volume FROM prices WHERE ticker = :t AND date >= :c "
            "ORDER BY date", {"t": t, "c": (_today() - timedelta(days=days)).isoformat()})
    if df.empty:
        return {"error": f"no stored prices for {t}"}
    c = pd.to_numeric(df["close"], errors="coerce")
    r = c.pct_change()
    step = max(1, len(df) // 40)
    return {"ticker": t, "from": _d(df["date"].iloc[0]), "to": _d(df["date"].iloc[-1]),
            "last_close": _num(c.iloc[-1], 2), "high": _num(c.max(), 2), "low": _num(c.min(), 2),
            "return": _num(c.iloc[-1] / c.iloc[0] - 1),
            "annualised_vol": _num(r.std() * math.sqrt(252)),
            "max_drawdown": _num((c / c.cummax() - 1).min()),
            "closes": [(_d(d), _num(v, 2)) for d, v in
                       zip(df["date"].iloc[::step], c.iloc[::step])]}


def options_and_short(src: Sources, ticker: str):
    t = _tk(ticker)
    o = _q("SELECT * FROM options_snapshots WHERE ticker = :t ORDER BY date DESC LIMIT 30",
           {"t": t})
    sv = _q("SELECT date, short_volume, total_volume FROM short_volume WHERE ticker = :t "
            "ORDER BY date DESC LIMIT 20", {"t": t})
    out: dict[str, Any] = {"ticker": t}
    if not o.empty:
        r = o.iloc[0]
        ivs = pd.to_numeric(o["atm_iv"], errors="coerce").dropna()
        out["options"] = {"date": _d(r["date"]), "front_expiry": _d(r["expiry"]),
                          "atm_iv": _num(r["atm_iv"]), "iv_back_month": _num(r["iv_back"]),
                          "implied_move_to_expiry": _num(r["implied_move"]),
                          "put_call_volume": _num(r["pc_volume_ratio"]),
                          "put_call_oi": _num(r["pc_oi_ratio"]),
                          "iv_rank_30obs": _num((ivs.iloc[0] - ivs.min()) / (ivs.max() - ivs.min()))
                          if len(ivs) > 5 and ivs.max() > ivs.min() else None}
    if not sv.empty:
        ratio = pd.to_numeric(sv["short_volume"], errors="coerce") / \
            pd.to_numeric(sv["total_volume"], errors="coerce")
        out["finra_short_volume_ratio"] = {"last": _num(ratio.iloc[0]),
                                           "avg_20d": _num(ratio.mean()),
                                           "date": _d(sv["date"].iloc[0])}
    return out


def market_overview(src: Sources):
    reg = _q("SELECT regime, asof FROM signal_scores ORDER BY asof DESC LIMIT 1")
    lab = _q("SELECT label, COUNT(*) AS n FROM signal_scores "
             "WHERE asof = (SELECT MAX(asof) FROM signal_scores) GROUP BY label")
    br = _q("SELECT close, sma50, sma200 FROM technicals "
            "WHERE date = (SELECT MAX(date) FROM technicals)")
    out: dict[str, Any] = {}
    if not reg.empty:
        out["xbi_regime"] = reg.iloc[0]["regime"]
        out["signals_asof"] = _d(reg.iloc[0]["asof"])
    if not lab.empty:
        out["signal_counts"] = dict(zip(lab["label"], lab["n"].astype(int)))
    if not br.empty:
        out["breadth"] = {"pct_above_sma50": _num((br["close"] > br["sma50"]).mean()),
                          "pct_above_sma200": _num((br["close"] > br["sma200"]).mean()),
                          "names": int(len(br))}
    h = _q("SELECT ticker, reason, halt_at, resumption_trade_time FROM halts "
           "WHERE ticker IS NOT NULL ORDER BY halt_at DESC LIMIT 10")
    if not h.empty:
        out["recent_halts"] = [{"ticker": r.ticker, "reason": r.reason,
                                "halted": str(r.halt_at)[:16],
                                "resumed": r.resumption_trade_time} for r in h.itertuples()]
    return out


# ---------------------------------------------------------------- registry
def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [],
            "additionalProperties": False}


_T = {"type": "string", "description": "Ticker symbol, e.g. VRTX", "maxLength": 12}
LABELS = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]

TOOLS: list[Tool] = [
    Tool("find_companies", "Find companies or drugs in the BioTerm universe by ticker, company "
         "name, molecule name/code or indication text.",
         _obj({"query": {"type": "string", "maxLength": 80},
               "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, ["query"]),
         find_companies),
    Tool("company_snapshot", "One company: live quote, market cap, cash, debt, enterprise "
         "value, burn and runway, short interest, Focus Score and its parts, the current "
         "signal call with its strongest evidence, technicals, watchlist thesis and the next "
         "catalysts. Start here for any single-company question.",
         _obj({"ticker": _T}, ["ticker"]), company_snapshot),
    Tool("upcoming_catalysts", "Upcoming catalysts (PDUFA dates, AdComs, trial readouts, "
         "primary completions, earnings) for one ticker or the whole universe.",
         _obj({"ticker": _T, "days_ahead": {"type": "integer", "minimum": 1, "maximum": 730},
               "limit": {"type": "integer", "minimum": 1, "maximum": 80}}),
         upcoming_catalysts),
    Tool("clinical_trials", "ClinicalTrials.gov trials sponsored by a company (phase, status, "
         "primary completion date, enrollment) plus recently detected changes (date slips, "
         "enrollment complete, suspensions).",
         _obj({"ticker": _T, "include_completed": {"type": "boolean"},
               "limit": {"type": "integer", "minimum": 1, "maximum": 60}}, ["ticker"]),
         clinical_trials),
    Tool("sec_filings", "Recent SEC filings for a company (8-K, 10-Q, 10-K, S-3, 424B, SC 13D/G, "
         "Form 4, 144 ...) with AI summaries when available and document URLs.",
         _obj({"ticker": _T, "forms": {"type": "array", "items": {"type": "string",
                                                                   "maxLength": 16}},
               "days": {"type": "integer", "minimum": 1, "maximum": 1100},
               "limit": {"type": "integer", "minimum": 1, "maximum": 60}}, ["ticker"]),
         sec_filings),
    Tool("read_sec_document", "Read the text of an SEC document (a URL returned by sec_filings). "
         "Pass `query` to get only the passages mentioning those words.",
         _obj({"url": {"type": "string", "maxLength": 400},
               "query": {"type": "string", "maxLength": 120},
               "max_chars": {"type": "integer", "minimum": 1000, "maximum": 20000}}, ["url"]),
         read_sec_document),
    Tool("news_headlines", "Recent news headlines (company press releases, trade press, wires) "
         "with tone and AI event tags, for a ticker and/or a keyword.",
         _obj({"ticker": _T, "days": {"type": "integer", "minimum": 1, "maximum": 365},
               "query": {"type": "string", "maxLength": 80},
               "limit": {"type": "integer", "minimum": 1, "maximum": 60}}),
         news_headlines),
    Tool("insider_activity", "Open-market insider buys and sells (Form 4) for a company, with "
         "10b5-1 plan flags.",
         _obj({"ticker": _T, "days": {"type": "integer", "minimum": 1, "maximum": 1100}},
              ["ticker"]), insider_activity),
    Tool("fund_ownership", "Holdings of specialist biotech funds (13F) in a company, quarter "
         "over quarter, and whole-market 13F holder counts when available.",
         _obj({"ticker": _T}, ["ticker"]), fund_ownership),
    Tool("signal_board", "The latest BioTerm signal calls across the universe, strongest first; "
         "optionally only one label.",
         _obj({"label": {"type": "string", "enum": LABELS},
               "limit": {"type": "integer", "minimum": 1, "maximum": 80}}), signal_board),
    Tool("screen_universe", "Screen the universe on fundamentals, signals and catalyst timing. "
         "Market caps in USD; short interest as a fraction (0.2 = 20%).",
         _obj({"max_market_cap": {"type": "number"}, "min_market_cap": {"type": "number"},
               "max_runway_quarters": {"type": "number"},
               "below_cash": {"type": "boolean", "description": "enterprise value < 0"},
               "signal_labels": {"type": "array", "items": {"type": "string", "enum": LABELS}},
               "catalyst_within_days": {"type": "integer", "minimum": 1, "maximum": 730},
               "min_short_pct_float": {"type": "number"},
               "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
         screen_universe),
    Tool("price_summary", "Stored daily price history summary: return, high/low, volatility, "
         "drawdown and a downsampled close series.",
         _obj({"ticker": _T, "days": {"type": "integer", "minimum": 5, "maximum": 1900}},
              ["ticker"]), price_summary),
    Tool("options_and_short", "Options positioning (ATM IV, IV rank, implied move, put/call) and "
         "FINRA short-sale volume ratio for a company.",
         _obj({"ticker": _T}, ["ticker"]), options_and_short),
    Tool("market_overview", "Sector state: XBI regime, breadth, signal counts, recent trading "
         "halts.", _obj({}), market_overview),
]


def by_name() -> dict[str, Tool]:
    return {t.name: t for t in TOOLS}


def executor(src: Sources) -> Callable[[str, dict], str]:
    reg = by_name()

    def run(name: str, args: dict) -> str:
        tool = reg[name]
        return dump(tool.fn(src, **args))

    return run
