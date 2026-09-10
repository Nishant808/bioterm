"""Paper-trading portfolio — maths (pure) + blotter CRUD.

Positions/cash/equity are *derived* from a trade blotter (BUY/SELL rows) plus
prices. Average-cost method, long-only. Simulated fills; no real orders anywhere.

Lives in its own module (not ``store.py``) so the Streamlit Cloud dashboard always
imports it fresh — a fast reboot keeps old modules in ``sys.modules``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, String,
                        Table, Text)

TRADE_COLS = ["ts", "ticker", "side", "qty", "price", "fees", "note"]

# The paper-trading tables are declared here as well as in ``bioterm.db`` (same
# names/columns). On Streamlit Cloud a fast reboot keeps the already-imported
# ``bioterm.db`` in ``sys.modules`` — if that copy predates the pf tables, a lazy
# ``from .db import pf_portfolios`` blows up. This module is always a fresh import,
# so CRUD builds its statements from these local Table objects instead. SQLAlchemy
# generates SQL by name, so a foreign MetaData is fine for insert/delete/upsert.
_meta = MetaData()

pf_portfolios = Table(
    "pf_portfolios", _meta,
    Column("id", String(32), primary_key=True),
    Column("name", String(80)),
    Column("cash_start", Float),
    Column("created_at", DateTime),
)

pf_trades = Table(
    "pf_trades", _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("portfolio_id", String(32), index=True),
    Column("ts", DateTime),
    Column("ticker", String(16), index=True),
    Column("side", String(4)),
    Column("qty", Float),
    Column("price", Float),
    Column("fees", Float),
    Column("note", Text),
)


def _norm(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame(columns=TRADE_COLS)
    t = trades.copy()
    t["ts"] = pd.to_datetime(t["ts"], errors="coerce")
    for c in ("qty", "price", "fees"):
        t[c] = pd.to_numeric(t.get(c), errors="coerce").fillna(0.0)
    t["side"] = t["side"].astype(str).str.upper()
    t["ticker"] = t["ticker"].astype(str).str.upper()
    return t.sort_values("ts").reset_index(drop=True)


def cash_balance(trades: pd.DataFrame, cash_start: float) -> float:
    t = _norm(trades)
    cash = float(cash_start)
    for _, r in t.iterrows():
        gross = r["qty"] * r["price"]
        cash += (-gross - r["fees"]) if r["side"] == "BUY" else (gross - r["fees"])
    return cash


def positions(trades: pd.DataFrame) -> pd.DataFrame:
    """Open long positions (qty > 0) with average cost + realised P&L per ticker."""
    t = _norm(trades)
    book: dict[str, dict] = {}
    for _, r in t.iterrows():
        b = book.setdefault(r["ticker"],
                            {"qty": 0.0, "cost": 0.0, "realized": 0.0, "fees": 0.0})
        if r["side"] == "BUY":
            b["qty"] += r["qty"]
            b["cost"] += r["qty"] * r["price"] + r["fees"]
        else:  # SELL
            avg = b["cost"] / b["qty"] if b["qty"] > 1e-9 else 0.0
            sell_qty = min(r["qty"], b["qty"])
            b["realized"] += sell_qty * (r["price"] - avg) - r["fees"]
            b["cost"] -= sell_qty * avg
            b["qty"] -= sell_qty
            if b["qty"] <= 1e-9:
                b["qty"], b["cost"] = 0.0, 0.0
        b["fees"] += r["fees"]

    rows = []
    for tk, b in book.items():
        rows.append({
            "ticker": tk,
            "qty": round(b["qty"], 4),
            "avg_cost": round(b["cost"] / b["qty"], 4) if b["qty"] > 1e-9 else 0.0,
            "cost_basis": round(b["cost"], 2),
            "realized_pnl": round(b["realized"], 2),
        })
    df = pd.DataFrame(rows, columns=["ticker", "qty", "avg_cost", "cost_basis",
                                     "realized_pnl"])
    return df.sort_values("ticker").reset_index(drop=True)


def mark_to_market(trades: pd.DataFrame, last_price: dict[str, float],
                   cash_start: float) -> dict:
    """Portfolio summary at the latest prices."""
    pos = positions(trades)
    open_pos = pos[pos["qty"] > 1e-9].copy()
    open_pos["last"] = open_pos["ticker"].map(lambda x: last_price.get(x))
    open_pos["mkt_value"] = open_pos["qty"] * open_pos["last"].fillna(open_pos["avg_cost"])
    open_pos["unrealized_pnl"] = open_pos["mkt_value"] - open_pos["cost_basis"]
    open_pos["return_pct"] = open_pos["unrealized_pnl"] / open_pos["cost_basis"].replace(0, pd.NA)

    cash = cash_balance(trades, cash_start)
    invested = float(open_pos["mkt_value"].sum())
    equity = cash + invested
    realized = float(pos["realized_pnl"].sum())
    unrealized = float(open_pos["unrealized_pnl"].sum())
    if not open_pos.empty:
        open_pos["weight"] = open_pos["mkt_value"] / equity
    return {
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "equity": round(equity, 2),
        "cash_start": float(cash_start),
        "total_return": (equity - cash_start) / cash_start if cash_start else 0.0,
        "total_pnl": round(equity - cash_start, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "n_positions": int(len(open_pos)),
        "positions": open_pos.sort_values("mkt_value", ascending=False).reset_index(drop=True),
    }


def equity_curve(trades: pd.DataFrame, price_hist: pd.DataFrame,
                 cash_start: float) -> pd.DataFrame:
    """Daily portfolio equity from the first trade to today.

    ``price_hist``: long DataFrame [ticker, date, close] covering the held names.
    """
    t = _norm(trades)
    if t.empty:
        return pd.DataFrame(columns=["date", "equity", "invested", "cash"])
    ph = (price_hist.copy() if price_hist is not None
          else pd.DataFrame(columns=["ticker", "date", "close"]))
    start = t["ts"].min().normalize()
    days = pd.date_range(start, pd.Timestamp.today().normalize(), freq="D")

    # cumulative signed qty per ticker per day
    t["signed"] = t.apply(lambda r: r["qty"] if r["side"] == "BUY" else -r["qty"], axis=1)
    t["day"] = t["ts"].dt.normalize()

    # price lookup: forward-fill each ticker's close onto every calendar day
    if ph.empty:
        pivot = pd.DataFrame(index=days)
    else:
        ph["date"] = pd.to_datetime(ph["date"])
        pivot = (ph.pivot_table(index="date", columns="ticker", values="close")
                 .reindex(days).ffill())

    out = []
    for d in days:
        held = (t[t["day"] <= d].groupby("ticker")["signed"].sum())
        held = held[held > 1e-9]
        inv = 0.0
        for tk, q in held.items():
            px = pivot.at[d, tk] if tk in pivot.columns and not pd.isna(pivot.at[d, tk]) else None
            if px is None:
                # fall back to the last known trade price for that ticker
                px = t[(t["ticker"] == tk) & (t["day"] <= d)]["price"].iloc[-1]
            inv += q * px
        cash = cash_balance(t[t["day"] <= d], cash_start)
        out.append({"date": d, "equity": round(cash + inv, 2),
                    "invested": round(inv, 2), "cash": round(cash, 2)})
    return pd.DataFrame(out)


def validate_trade(trades: pd.DataFrame, cash_start: float, ticker: str, side: str,
                   qty: float, price: float, fees: float) -> str | None:
    """Return an error string if the trade is not allowed, else None."""
    if qty <= 0 or price <= 0:
        return "quantity and price must be positive"
    side = side.upper()
    if side == "BUY":
        need = qty * price + fees
        have = cash_balance(trades, cash_start)
        if need > have + 1e-6:
            return f"insufficient cash — need ${need:,.0f}, have ${have:,.0f}"
    elif side == "SELL":
        pos = positions(trades)
        row = pos[pos["ticker"] == ticker.upper()]
        held = float(row["qty"].iloc[0]) if not row.empty else 0.0
        if qty > held + 1e-6:
            return f"can't sell {qty:g} — you hold {held:g} {ticker.upper()} (long-only)"
    else:
        return "side must be BUY or SELL"
    return None


# ================================================================= blotter CRUD
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:28]
    return s or "portfolio"


def list_portfolios() -> list[dict]:
    from .db import read_sql
    try:
        df = read_sql("SELECT * FROM pf_portfolios ORDER BY created_at")
    except Exception:  # noqa: BLE001
        return []
    return df.to_dict("records") if not df.empty else []


def ensure_default() -> str:
    pl = list_portfolios()
    return pl[0]["id"] if pl else create_portfolio("Strategy A", 100_000.0)


def create_portfolio(name: str, cash_start: float = 100_000.0) -> str:
    from .db import bulk_upsert
    base = _slug(name)
    existing = {p["id"] for p in list_portfolios()}
    pid, i = base, 2
    while pid in existing:
        pid = f"{base}-{i}"
        i += 1
    bulk_upsert(pf_portfolios, [{"id": pid, "name": (name or pid).strip(),
                                 "cash_start": float(cash_start),
                                 "created_at": _now()}])
    return pid


def delete_portfolio(pid: str) -> None:
    from .db import get_engine
    with get_engine().begin() as conn:
        conn.execute(pf_trades.delete().where(pf_trades.c.portfolio_id == pid))
        conn.execute(pf_portfolios.delete().where(pf_portfolios.c.id == pid))


def reset_portfolio(pid: str) -> None:
    from .db import get_engine
    with get_engine().begin() as conn:
        conn.execute(pf_trades.delete().where(pf_trades.c.portfolio_id == pid))


def get_trades(pid: str) -> pd.DataFrame:
    from .db import read_sql
    try:
        return read_sql("SELECT * FROM pf_trades WHERE portfolio_id = :p ORDER BY ts, id",
                        {"p": pid})
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def add_trade(pid: str, ticker: str, side: str, qty: float, price: float,
              fees: float = 0.0, note: str = "", ts: datetime | None = None) -> None:
    from .db import get_engine
    with get_engine().begin() as conn:
        conn.execute(pf_trades.insert(), [{
            "portfolio_id": pid, "ts": ts or _now(),
            "ticker": ticker.strip().upper(), "side": side.upper(),
            "qty": float(qty), "price": float(price), "fees": float(fees or 0.0),
            "note": (note or "").strip()}])


def delete_trade(trade_id: int) -> None:
    from .db import get_engine
    with get_engine().begin() as conn:
        conn.execute(pf_trades.delete().where(pf_trades.c.id == int(trade_id)))
