"""Shared HTTP helpers: a pooled session, polite defaults, retry/backoff."""
from __future__ import annotations

import logging
import time
from typing import Any

import requests
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import load_settings

log = logging.getLogger("bioterm.http")

_SESSION: requests.Session | None = None
_LAST_CALL: dict[str, float] = {}


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
        retry=retry_if_exception_type((requests.RequestException,)),
    )
    to = timeout if timeout is not None else load_settings().http_timeout

    def _once():
        _throttle(_host(url), min_interval)
        resp = session().get(url, params=params, headers=headers,
                             timeout=(5, to))  # (connect, read)
        if resp.status_code == 429:
            log.warning("429 from %s - backing off %ss", _host(url), backoff_429)
            time.sleep(backoff_429)
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
