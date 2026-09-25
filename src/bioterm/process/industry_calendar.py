"""Industry calendar (config/events.yml): medical meetings and EMA CHMP weeks,
with the universe names that have late-stage programmes in each meeting's area."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def events(days_ahead: int = 365, today: date | None = None) -> pd.DataFrame:
    from ..config import _read_yaml

    today = today or date.today()
    rows = (_read_yaml("events.yml") or {}).get("events") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["start"] = pd.to_datetime(df["start"]).dt.date
    df["end"] = pd.to_datetime(df.get("end", df["start"])).dt.date
    df = df[(df["end"] >= today) & (df["start"] <= today + timedelta(days=days_ahead))]
    return df.sort_values("start").reset_index(drop=True)


def presenters(area_list) -> list[str]:
    """Universe tickers with an active Phase 2/3 trial in any of ``area_list``."""
    from ..db import read_sql
    from .pos import area_of

    if not isinstance(area_list, (list, tuple)) or not area_list:
        return []
    try:
        tr = read_sql("SELECT ticker, conditions, phase FROM clinical_trials WHERE status IN "
                      "('RECRUITING','ACTIVE_NOT_RECRUITING','COMPLETED')")
    except Exception:  # noqa: BLE001
        return []
    tr = tr[tr["phase"].fillna("").str.contains("P2|P3")]
    tr["area"] = tr["conditions"].map(area_of)
    return sorted(tr[tr["area"].isin(area_list)]["ticker"].dropna().unique().tolist())
