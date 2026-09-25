"""NYSE/Nasdaq trading calendar: holidays, early closes, session state.

Standard library only, so the GitHub Actions gate can run it with the runner's
system Python before any dependency is installed:

    python3 src/bioterm/market_calendar.py gate open|close|pulse

prints ``run=true`` / ``run=false`` for ``$GITHUB_OUTPUT``.

Rules follow NYSE Rule 7.2 as applied since 2022 (Juneteenth added). One-off
closures (national days of mourning, weather) are not predictable and are not
modelled - on such a day the data simply doesn't change.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN, CLOSE, EARLY_CLOSE = time(9, 30), time(16, 0), time(13, 0)
PRE_OPEN, AFTER_CLOSE = time(4, 0), time(20, 0)


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th ``weekday`` (Mon=0) of a month; n = -1 for the last one."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date, saturday_to_friday: bool = True) -> date | None:
    if d.weekday() == 5:                     # Saturday -> Friday (unless barred)
        return d - timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:                     # Sunday -> Monday
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def holidays(year: int) -> dict[date, str]:
    out: dict[date, str] = {}

    def add(d: date | None, name: str) -> None:
        if d is not None:
            out[d] = name

    # New Year's Day: a Saturday Jan 1 is NOT moved to Friday Dec 31 (NYSE rule)
    add(_observed(date(year, 1, 1), saturday_to_friday=False), "New Year's Day")
    add(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day")
    add(_nth_weekday(year, 2, 0, 3), "Washington's Birthday")
    add(_easter(year) - timedelta(days=2), "Good Friday")
    add(_nth_weekday(year, 5, 0, -1), "Memorial Day")
    if year >= 2022:
        add(_observed(date(year, 6, 19)), "Juneteenth")
    add(_observed(date(year, 7, 4)), "Independence Day")
    add(_nth_weekday(year, 9, 0, 1), "Labor Day")
    add(_nth_weekday(year, 11, 3, 4), "Thanksgiving Day")
    add(_observed(date(year, 12, 25)), "Christmas Day")
    return out


def holiday_name(d: date) -> str | None:
    return holidays(d.year).get(d)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def early_close(d: date) -> bool:
    """13:00 close: July 3 and Christmas Eve on Mon-Thu, the day after Thanksgiving."""
    if not is_trading_day(d):
        return False
    if d.month == 7 and d.day == 3 and d.weekday() <= 3:
        return True
    if d.month == 12 and d.day == 24 and d.weekday() <= 3:
        return True
    return d == _nth_weekday(d.year, 11, 3, 4) + timedelta(days=1)


def close_time(d: date) -> time:
    return EARLY_CLOSE if early_close(d) else CLOSE


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def session(now: datetime | None = None) -> tuple[str, str]:
    """(state, label): open / pre / after / closed for US equities."""
    t = (now or datetime.now(NY)).astimezone(NY)
    d, hm = t.date(), t.time()
    if not is_trading_day(d):
        name = holiday_name(d)
        return "closed", f"Market closed · {name}" if name else "Market closed"
    close = close_time(d)
    if OPEN <= hm < close:
        return "open", "Market open" + (" · early close 1 pm" if close == EARLY_CLOSE else "")
    if PRE_OPEN <= hm < OPEN:
        return "pre", "Pre-market"
    if close <= hm < AFTER_CLOSE:
        return "after", "After hours"
    return "closed", "Market closed"


def gate(kind: str, now: datetime | None = None) -> bool:
    """Should a scheduled job run now? Windows are an hour wide because GitHub
    can start a cron run late; each UTC cron fires twice a day (DST) and only the
    copy that lands inside the New York window proceeds.

    open  : 09:30-10:30 ET on a trading day
    close : close time to +1h (16:00-17:00, or 13:00-14:00 on early-close days)
    pulse : 07:00-20:00 ET on a trading day (pre-market through after-hours)
    """
    t = (now or datetime.now(NY)).astimezone(NY)
    d = t.date()
    if not is_trading_day(d):
        return False
    mins = t.hour * 60 + t.minute
    if kind == "open":
        return 9 * 60 + 30 <= mins < 10 * 60 + 30
    if kind == "close":
        c = close_time(d)
        start = c.hour * 60 + c.minute
        return start <= mins < start + 60
    if kind == "pulse":
        return 7 * 60 <= mins < 20 * 60
    raise ValueError(f"unknown gate {kind!r}")


if __name__ == "__main__":                   # pragma: no cover - exercised in Actions
    if len(sys.argv) >= 3 and sys.argv[1] == "gate":
        ok = gate(sys.argv[2])
        print(f"New York {datetime.now(NY):%Y-%m-%d %H:%M} -> {sys.argv[2]} run={str(ok).lower()}",
              file=sys.stderr)
        print(f"run={str(ok).lower()}")
    else:
        print(session()[1])
