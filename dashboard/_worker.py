"""The live pulse inside the Streamlit server process.

While the app is awake (someone has visited it recently), a daemon thread runs
``bioterm.realtime.pulse`` every few minutes during the US session - halts, new
SEC filings, wire headlines, movers, alerts. It shares a database lease with the
GitHub Actions pulse and any Docker/launchd worker, so only one of them runs a
given pass. Off switch: Settings -> System, or ``BIOTERM_INAPP_WORKER=0``.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("bioterm.dashboard.worker")

NAME = "bioterm-pulse"
INTERVAL_S = 300
TICK_S = 60


def _due() -> bool:
    import pandas as pd

    from bioterm import realtime

    last = pd.to_datetime((realtime.state() or {}).get("last_run"), utc=True, errors="coerce")
    return pd.isna(last) or (datetime.now(timezone.utc) - last).total_seconds() >= INTERVAL_S - 30


def _loop() -> None:
    from bioterm import realtime
    from bioterm.market_calendar import gate
    from bioterm.store import get_meta

    while True:
        try:
            cfg = get_meta("worker", {"enabled": True}) or {}
            if cfg.get("enabled", True) and gate("pulse") and _due() \
                    and realtime.acquire_lease(ttl_s=INTERVAL_S + 60):
                out = realtime.pulse()
                log.info("in-app pulse done in %ss", out.get("seconds"))
        except Exception as exc:  # noqa: BLE001 - never let the thread die
            log.warning("in-app pulse failed: %s", exc)
        time.sleep(TICK_S)


def ensure_started() -> None:
    """Start the thread once per server process (module reloads included)."""
    if os.environ.get("BIOTERM_INAPP_WORKER", "1") == "0":
        return
    if any(t.name == NAME and t.is_alive() for t in threading.enumerate()):
        return
    threading.Thread(target=_loop, name=NAME, daemon=True).start()
    log.info("in-app pulse thread started")
