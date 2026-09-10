"""Paper-trading portfolio maths — positions, cash, equity curve, P&L.

Pure functions over a trade blotter (a DataFrame of BUY/SELL rows) plus prices.
Average-cost method, long-only. Simulated fills; no real orders anywhere.
"""
from __future__ import annotations

import pandas as pd

TRADE_COLS = ["ts", "ticker", "side", "qty", "price", "fees", "note"]


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
    ph = price_hist.copy()
    ph["date"] = pd.to_datetime(ph["date"])
    start = t["ts"].min().normalize()
    days = pd.date_range(start, pd.Timestamp.today().normalize(), freq="D")

    # cumulative signed qty per ticker per day
    t["signed"] = t.apply(lambda r: r["qty"] if r["side"] == "BUY" else -r["qty"], axis=1)
    t["day"] = t["ts"].dt.normalize()

    # price lookup: forward-fill each ticker's close onto every calendar day
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
