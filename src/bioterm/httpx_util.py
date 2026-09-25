"""Shared HTTP helpers: a pooled session, polite defaults, retry/backoff and a
per-host circuit breaker.

The breaker counts *transport* failures per host (connection errors, timeouts,
HTTP 429 and 5xx - never 4xx like a 404 for a missing daily file). After
``BREAKER_THRESHOLD`` in a row it opens for ``BREAKER_COOLDOWN`` seconds and
every call to that host fails immediately with ``CircuitOpen`` instead of
burning the job's wall-clock budget on a source that is down.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from .config import load_settings

log = logging.getLogger("bioterm.http")

_SESSION: requests.Session | None = None
_LAST_CALL: dict[str, float] = {}

BREAKER_THRESHOLD = 5
BREAKER_COOLDOWN = 180.0
_FAILS: dict[str, int] = {}
_OPEN_UNTIL: dict[str, float] = {}
_TRIPS: list[dict[str, Any]] = []


class CircuitOpen(requests.RequestException):
    """The host failed repeatedly; calls are short-circuited for a while."""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, CircuitOpen):
        return False
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        # SEC answers its fair-access throttle with a 403 - worth a backed-off retry
        sec_throttle = code == 403 and _host(exc.response.url or "").endswith("sec.gov")
        return code == 429 or code >= 500 or sec_throttle
    return isinstance(exc, requests.RequestException)


def _breaker_check(host: str) -> None:
    until = _OPEN_UNTIL.get(host, 0.0)
    if until and time.monotonic() < until:
        raise CircuitOpen(f"{host}: circuit open after repeated failures")


def _breaker_record(host: str, ok: bool) -> None:
    if ok:
        _FAILS[host] = 0
        return
    _FAILS[host] = _FAILS.get(host, 0) + 1
    if _FAILS[host] >= BREAKER_THRESHOLD:
        _OPEN_UNTIL[host] = time.monotonic() + BREAKER_COOLDOWN
        _FAILS[host] = 0
        _TRIPS.append({"host": host, "at": time.time()})
        log.warning("circuit breaker open for %s (%ss)", host, BREAKER_COOLDOWN)


def breaker_state() -> dict[str, Any]:
    """Hosts currently short-circuited and every trip this process saw."""
    now = time.monotonic()
    return {"open": sorted(h for h, u in _OPEN_UNTIL.items() if u > now),
            "trips": list(_TRIPS)}


def reset_breakers() -> None:
    _FAILS.clear()
    _OPEN_UNTIL.clear()
    _TRIPS.clear()


def session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": load_settings().sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        _SESSION = s
    return _SESSION


def _throttle(host: str, min_interval: float) -> None:
    now = time.monotonic()
    last = _LAST_CALL.get(host, 0.0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[host] = time.monotonic()


def _host(url: str) -> str:
    try:
        return url.split("/")[2]
    except IndexError:
        return url


def _request(url, params, headers, min_interval, *, want, retries, timeout, backoff_429):
    retryer = Retrying(
        reraise=True,
        stop=stop_after_attempt(retries),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_retryable),
    )
    to = timeout if timeout is not None else load_settings().http_timeout
    host = _host(url)

    def _once():
        _breaker_check(host)
        _throttle(host, min_interval)
        try:
            resp = session().get(url, params=params, headers=headers,
                                 timeout=(5, to))  # (connect, read)
        except requests.RequestException:
            _breaker_record(host, False)
            raise
        if resp.status_code == 429:
            log.warning("429 from %s - backing off %ss", host, backoff_429)
            time.sleep(backoff_429)
        _breaker_record(host, not (resp.status_code == 429 or resp.status_code >= 500))
        resp.raise_for_status()
        return resp.json() if want == "json" else resp.content

    return retryer(_once)


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    min_interval: float = 0.2,
    retries: int = 4,
    timeout: float | None = None,
    backoff_429: float = 5.0,
) -> Any:
    return _request(url, params, headers, min_interval, want="json", retries=retries,
                    timeout=timeout, backoff_429=backoff_429)


def get_bytes(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    min_interval: float = 0.2,
    retries: int = 4,
    timeout: float | None = None,
    backoff_429: float = 5.0,
) -> bytes:
    return _request(url, params, headers, min_interval, want="bytes", retries=retries,
                    timeout=timeout, backoff_429=backoff_429)


def post_json(
    url: str,
    payload: Any,
    *,
    headers: dict[str, str] | None = None,
    min_interval: float = 0.2,
    retries: int = 3,
    timeout: float | None = None,
    backoff_429: float = 10.0,
) -> Any:
    """POST a JSON body, return the decoded JSON reply (same politeness rules as GETs)."""
    retryer = Retrying(
        reraise=True,
        stop=stop_after_attempt(retries),
        wait=wait_exponential(multiplier=1, min=2, max=12),
        retry=retry_if_exception(_retryable),
    )
    to = timeout if timeout is not None else load_settings().http_timeout
    host = _host(url)

    def _once():
        _breaker_check(host)
        _throttle(host, min_interval)
        try:
            resp = session().post(url, json=payload, headers=headers, timeout=(5, to))
        except requests.RequestException:
            _breaker_record(host, False)
            raise
        if resp.status_code == 429:
            log.warning("429 from %s - backing off %ss", host, backoff_429)
            time.sleep(backoff_429)
        _breaker_record(host, not (resp.status_code == 429 or resp.status_code >= 500))
        resp.raise_for_status()
        return resp.json()

    return retryer(_once)
