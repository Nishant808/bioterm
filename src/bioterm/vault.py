"""Encrypted secrets (API keys, webhook URLs, SMTP passwords) kept in the database.

The dashboard's Settings page adds and deletes them; the GitHub Actions runs read
them - both reach the same database, so a key entered once in the browser powers
the LLM features, notifications and data providers everywhere.

Encryption: Fernet (AES-128-CBC + HMAC-SHA256). The key is derived with
PBKDF2 from ``BIOTERM_SECRET_KEY`` when set, otherwise from the database
credentials (user + password + database name - the parts every environment's
``DATABASE_URL`` shares, whatever driver prefix, host alias or query string it
uses). A leaked backup or table dump is therefore useless without the database
password; rotating that password (or setting ``BIOTERM_SECRET_KEY`` later)
makes stored values undecryptable, and the UI then asks for them again.

Lookup order for ``get(name)``: process environment (Actions secrets, Streamlit
secrets bridged into the env, a local ``.env``) first, then the vault.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("bioterm.vault")

# name -> (label, group, help). Only catalogued names can be stored.
CATALOG: dict[str, tuple[str, str, str]] = {
    "ANTHROPIC_API_KEY": ("Anthropic API key", "llm", "Claude - Copilot, event extraction, "
                                                     "filing summaries, daily brief"),
    "OPENAI_API_KEY": ("OpenAI API key", "llm", "Alternative LLM provider"),
    "OPENAI_BASE_URL": ("OpenAI-compatible base URL", "llm",
                        "Optional - any OpenAI-compatible endpoint (OpenRouter, Groq, "
                        "Together, a local server). Leave empty for api.openai.com"),
    "FINNHUB_API_KEY": ("Finnhub API key", "data", "Secondary live-quote source (free tier)"),
    "TELEGRAM_BOT_TOKEN": ("Telegram bot token", "notify", "From @BotFather"),
    "TELEGRAM_CHAT_ID": ("Telegram chat id", "notify", "Your chat or channel id"),
    "SLACK_WEBHOOK_URL": ("Slack webhook URL", "notify", "Incoming-webhook URL"),
    "DISCORD_WEBHOOK_URL": ("Discord webhook URL", "notify", "Channel webhook URL"),
    "NTFY_TOPIC": ("ntfy topic", "notify",
                   "Phone push with no account: install the ntfy app and subscribe "
                   "to a hard-to-guess topic name"),
    "NTFY_SERVER": ("ntfy server", "notify", "Optional - defaults to https://ntfy.sh"),
    "NTFY_TOKEN": ("ntfy access token", "notify", "Optional - for protected topics"),
    "SMTP_HOST": ("SMTP host", "notify", "e.g. smtp.gmail.com"),
    "SMTP_PORT": ("SMTP port", "notify", "465 (SSL) or 587 (STARTTLS)"),
    "SMTP_USER": ("SMTP user", "notify", "Login"),
    "SMTP_PASSWORD": ("SMTP password", "notify", "App password"),
    "SMTP_FROM": ("Email from", "notify", "Sender address"),
    "SMTP_TO": ("Email to", "notify", "Recipient address(es), comma separated"),
    "BIOTERM_API_TOKEN": ("API token", "system", "Bearer token for the read-only JSON API "
                                                 "(`bioterm api`) - every call needs it"),
}

_CACHE: dict[str, tuple[float, str | None]] = {}
_TTL = 60.0
_FERNET = None


class VaultError(RuntimeError):
    pass


def _key_material() -> bytes:
    explicit = os.environ.get("BIOTERM_SECRET_KEY")
    if explicit:
        return explicit.encode()
    from sqlalchemy.engine import make_url

    from .config import load_settings

    u = make_url(load_settings().database_url)
    # driver, host, port and query differ between environments that share a
    # database (pooled vs direct Neon endpoints, psycopg vs default driver)
    return f"{u.username or ''}|{u.password or ''}|{u.database or ''}".encode()


def _fernet():
    global _FERNET
    if _FERNET is None:
        from cryptography.fernet import Fernet

        raw = hashlib.pbkdf2_hmac("sha256", _key_material(), b"bioterm-vault-v1", 120_000)
        _FERNET = Fernet(base64.urlsafe_b64encode(raw))
    return _FERNET


def reset_key_cache() -> None:
    """Forget the derived key (tests switch databases between cases)."""
    global _FERNET
    _FERNET = None
    _CACHE.clear()


def mask(value: str) -> str:
    v = str(value or "")
    if len(v) <= 8:
        return "•" * len(v)
    return f"…{v[-4:]}"


def _table():
    from .db import app_secrets

    return app_secrets


def set(name: str, value: str) -> None:  # noqa: A001 - mirrors dict-style API
    if name not in CATALOG:
        raise VaultError(f"unknown secret {name!r}")
    value = str(value or "").strip()
    if not value:
        raise VaultError("empty value - use delete() to remove a secret")
    from .db import bulk_upsert

    token = _fernet().encrypt(value.encode()).decode()
    bulk_upsert(_table(), [{"name": name, "ciphertext": token, "hint": mask(value),
                            "updated_at": datetime.now(timezone.utc)}])
    _CACHE.pop(name, None)
    log.info("vault: stored %s", name)


def delete(name: str) -> None:
    from .db import get_engine

    t = _table()
    with get_engine().begin() as conn:
        conn.execute(t.delete().where(t.c.name == name))
    _CACHE.pop(name, None)
    log.info("vault: deleted %s", name)


def _from_db(name: str) -> str | None:
    now = time.monotonic()
    hit = _CACHE.get(name)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    from sqlalchemy import select

    from .db import read_sql

    t = _table()
    try:
        df = read_sql(select(t.c.ciphertext).where(t.c.name == name))
    except Exception:  # noqa: BLE001 - table missing on a brand-new database
        return None
    value = None
    if not df.empty and df.iloc[0]["ciphertext"]:
        from cryptography.fernet import InvalidToken

        try:
            value = _fernet().decrypt(str(df.iloc[0]["ciphertext"]).encode()).decode()
        except InvalidToken:
            log.warning("vault: %s can't be decrypted (database password or "
                        "BIOTERM_SECRET_KEY changed) - re-enter it in Settings", name)
            value = None
    _CACHE[name] = (now, value)
    return value


def get(name: str, default: str | None = None) -> str | None:
    env = os.environ.get(name)
    if env:
        return env
    return _from_db(name) or default


def source(name: str) -> str | None:
    """Where a secret currently comes from: 'env', 'vault' or None."""
    if os.environ.get(name):
        return "env"
    return "vault" if _from_db(name) else None


def listing() -> list[dict[str, Any]]:
    """Every catalogued secret with its masked hint and origin - never the value."""
    from .db import read_sql

    try:
        df = read_sql("SELECT name, hint, updated_at FROM app_secrets")
        stored = {r["name"]: r for _, r in df.iterrows()}
    except Exception:  # noqa: BLE001
        stored = {}
    out = []
    for name, (label, group, help_) in CATALOG.items():
        row = stored.get(name)
        env = bool(os.environ.get(name))
        out.append({"name": name, "label": label, "group": group, "help": help_,
                    "set": env or row is not None,
                    "origin": "env" if env else ("vault" if row is not None else None),
                    "hint": mask(os.environ[name]) if env else (row["hint"] if row is not None
                                                                else None),
                    "updated_at": None if row is None else row["updated_at"]})
    return out
