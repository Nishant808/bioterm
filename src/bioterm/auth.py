"""Owner passcode for the dashboard's write actions.

BioTerm is a single-owner terminal published at a public URL: anyone may read
it, only the owner may change it (watchlist, notes, molecules, portfolios,
screens, alert rules, API keys). The passcode is stored as a salted
PBKDF2-SHA256 hash in ``app_meta``; ``BIOTERM_ADMIN_PASSWORD`` (env / Streamlit
secret) overrides it - which is also how a forgotten passcode is reset.

An unclaimed terminal (no hash, no env) stays writable, and the dashboard says
so until the owner sets a passcode.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as _secrets
import time

META_KEY = "admin_auth"
_ITER = 240_000


def _hash(passcode: str, salt: bytes | None = None, iterations: int = _ITER) -> str:
    salt = salt or _secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", passcode.encode(), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(iterations, base64.b64encode(salt).decode(),
                                            base64.b64encode(dk).decode())


def _check(passcode: str, encoded: str) -> bool:
    try:
        algo, iters, salt, digest = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", passcode.encode(), base64.b64decode(salt),
                                 int(iters))
        return hmac.compare_digest(base64.b64encode(dk).decode(), digest)
    except (ValueError, TypeError):
        return False


def _stored() -> str | None:
    from .store import get_meta

    v = get_meta(META_KEY)
    return v.get("hash") if isinstance(v, dict) else None


def env_override() -> bool:
    return bool(os.environ.get("BIOTERM_ADMIN_PASSWORD"))


def is_claimed() -> bool:
    return env_override() or bool(_stored())


def claim(passcode: str) -> None:
    """First-run: set the owner passcode. Refuses if one already exists."""
    if is_claimed():
        raise PermissionError("this terminal already has an owner passcode")
    _validate(passcode)
    from .store import set_meta

    set_meta(META_KEY, {"hash": _hash(passcode), "claimed_at": time.time()})


def verify(passcode: str) -> bool:
    if not passcode:
        return False
    env = os.environ.get("BIOTERM_ADMIN_PASSWORD")
    if env:
        ok = hmac.compare_digest(passcode.encode(), env.encode())
    else:
        stored = _stored()
        ok = bool(stored) and _check(passcode, stored)
    if not ok:
        time.sleep(0.6)          # slow down guessing
    return ok


def change(old: str, new: str) -> None:
    if env_override():
        raise PermissionError("the passcode is set by BIOTERM_ADMIN_PASSWORD - change it there")
    if not verify(old):
        raise PermissionError("current passcode is wrong")
    _validate(new)
    from .store import set_meta

    set_meta(META_KEY, {"hash": _hash(new), "claimed_at": time.time()})


def _validate(passcode: str) -> None:
    if len(passcode or "") < 8:
        raise ValueError("use at least 8 characters")
