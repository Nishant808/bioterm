"""Foundation: NYSE calendar, versioned migrations, encrypted vault, owner
passcode, HTTP circuit breaker and multi-channel notifications."""
from datetime import date, datetime

import pytest
import requests

from bioterm import market_calendar as cal

NY = cal.NY


# ------------------------------------------------------------------ calendar
@pytest.mark.parametrize("d,name", [
    (date(2025, 1, 1), "New Year's Day"), (date(2025, 1, 20), "Martin Luther King Jr. Day"),
    (date(2025, 2, 17), "Washington's Birthday"), (date(2025, 4, 18), "Good Friday"),
    (date(2025, 5, 26), "Memorial Day"), (date(2025, 6, 19), "Juneteenth"),
    (date(2025, 7, 4), "Independence Day"), (date(2025, 9, 1), "Labor Day"),
    (date(2025, 11, 27), "Thanksgiving Day"), (date(2025, 12, 25), "Christmas Day"),
    (date(2026, 4, 3), "Good Friday"), (date(2026, 7, 3), "Independence Day"),
    (date(2026, 11, 26), "Thanksgiving Day"), (date(2027, 3, 26), "Good Friday"),
    (date(2027, 6, 18), "Juneteenth"), (date(2027, 7, 5), "Independence Day"),
    (date(2027, 12, 24), "Christmas Day"),
])
def test_nyse_holidays(d, name):
    assert cal.holiday_name(d) == name
    assert not cal.is_trading_day(d)


def test_saturday_new_year_is_not_moved_to_friday():
    assert cal.is_trading_day(date(2027, 12, 31))          # Jan 1 2028 is a Saturday


def test_early_closes():
    assert cal.early_close(date(2025, 7, 3)) and cal.early_close(date(2025, 11, 28))
    assert cal.early_close(date(2025, 12, 24)) and cal.early_close(date(2026, 12, 24))
    assert not cal.early_close(date(2026, 7, 2))             # Jul 3 2026 is the holiday
    assert cal.close_time(date(2026, 11, 27)).hour == 13


def test_session_and_gates():
    at = lambda *a: datetime(*a, tzinfo=NY)  # noqa: E731
    assert cal.session(at(2026, 9, 25, 10, 0))[0] == "open"
    assert cal.session(at(2026, 11, 26, 11, 0)) == ("closed", "Market closed · Thanksgiving Day")
    assert cal.gate("open", at(2026, 9, 25, 9, 40))
    assert not cal.gate("open", at(2026, 9, 25, 10, 40))     # the other DST copy
    assert cal.gate("close", at(2026, 9, 25, 16, 10))
    assert cal.gate("close", at(2026, 11, 27, 13, 20))       # early-close day
    assert cal.gate("close", at(2026, 11, 27, 16, 10))       # regular cron still lands
    assert not cal.gate("close", at(2026, 11, 27, 12, 50))
    assert cal.window(at(2026, 9, 25, 9, 40)) == "open"
    assert cal.window(at(2026, 9, 25, 16, 10)) == "close"
    assert cal.window(at(2026, 9, 25, 12, 0)) is None
    assert not cal.gate("pulse", at(2026, 9, 26, 12, 0))     # Saturday
    assert cal.previous_trading_day(date(2026, 11, 27)) == date(2026, 11, 25)


# ------------------------------------------------------------------ migrations
def test_migrations_run_once():
    from bioterm.db import init_db, read_sql, run_migrations

    init_db()
    assert run_migrations() == []
    v = read_sql("SELECT version FROM schema_migrations")["version"].tolist()
    assert sorted(v) == sorted(set(v)) and 1 in v


# ------------------------------------------------------------------ vault
def test_vault_roundtrip_env_precedence_and_masking(monkeypatch):
    from bioterm import vault
    from bioterm.db import init_db, read_sql

    init_db()
    vault.reset_key_cache()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-api03-SECRETVALUE-1234")
    raw = read_sql("SELECT ciphertext, hint FROM app_secrets").iloc[0]
    assert "SECRETVALUE" not in raw["ciphertext"] and raw["hint"] == "…1234"
    vault._CACHE.clear()
    assert vault.get("ANTHROPIC_API_KEY") == "sk-ant-api03-SECRETVALUE-1234"
    assert vault.source("ANTHROPIC_API_KEY") == "vault"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert vault.get("ANTHROPIC_API_KEY") == "from-env"
    row = next(r for r in vault.listing() if r["name"] == "ANTHROPIC_API_KEY")
    assert row["origin"] == "env" and "from-env" not in str(row)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    vault.delete("ANTHROPIC_API_KEY")
    assert vault.get("ANTHROPIC_API_KEY") is None
    with pytest.raises(vault.VaultError):
        vault.set("NOT_A_KNOWN_SECRET", "x")


def test_vault_value_unreadable_after_key_change(monkeypatch):
    from bioterm import vault
    from bioterm.db import init_db

    init_db()
    vault.reset_key_cache()
    vault.set("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/XYZ")
    monkeypatch.setenv("BIOTERM_SECRET_KEY", "a different key")
    vault.reset_key_cache()
    assert vault.get("SLACK_WEBHOOK_URL") is None          # asks to be re-entered
    vault.reset_key_cache()


# ------------------------------------------------------------------ owner passcode
def test_owner_passcode(monkeypatch):
    from bioterm import auth
    from bioterm.db import init_db

    init_db()
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)
    monkeypatch.delenv("BIOTERM_ADMIN_PASSWORD", raising=False)
    assert not auth.is_claimed()
    with pytest.raises(ValueError):
        auth.claim("short")
    auth.claim("correct horse battery")
    assert auth.is_claimed() and auth.verify("correct horse battery")
    assert not auth.verify("wrong passcode")
    with pytest.raises(PermissionError):
        auth.claim("someone else's code")
    auth.change("correct horse battery", "new passcode 42")
    assert auth.verify("new passcode 42") and not auth.verify("correct horse battery")
    monkeypatch.setenv("BIOTERM_ADMIN_PASSWORD", "env-reset-passcode")
    assert auth.verify("env-reset-passcode") and not auth.verify("new passcode 42")


# ------------------------------------------------------------------ circuit breaker
def test_circuit_breaker_opens_and_stops_calling(monkeypatch):
    from bioterm import httpx_util as h

    h.reset_breakers()
    calls = []

    class _S:
        def get(self, url, params=None, headers=None, timeout=None):
            calls.append(url)
            raise requests.ConnectionError("down")

    monkeypatch.setattr(h, "session", lambda: _S())
    monkeypatch.setattr(h.time, "sleep", lambda s: None)
    monkeypatch.setattr(h, "wait_exponential", lambda **kw: (lambda rs: 0))
    for _ in range(3):
        with pytest.raises(requests.RequestException):
            h.get_json("https://down.example.com/x", retries=2, min_interval=0)
    n = len(calls)
    assert "down.example.com" in h.breaker_state()["open"]
    with pytest.raises(h.CircuitOpen):
        h.get_json("https://down.example.com/y", retries=3, min_interval=0)
    assert len(calls) == n                                   # short-circuited, no request
    h.reset_breakers()


def test_404_does_not_trip_or_retry(monkeypatch):
    from bioterm import httpx_util as h

    h.reset_breakers()
    calls = []

    class _R:
        status_code = 404
        url = "https://files.example.com/missing.txt"

        def raise_for_status(self):
            err = requests.HTTPError("404")
            err.response = self
            raise err

    class _S:
        def get(self, url, params=None, headers=None, timeout=None):
            calls.append(url)
            return _R()

    monkeypatch.setattr(h, "session", lambda: _S())
    for _ in range(8):
        with pytest.raises(requests.HTTPError):
            h.get_bytes("https://files.example.com/missing.txt", min_interval=0)
    assert len(calls) == 8 and h.breaker_state()["open"] == []


# ------------------------------------------------------------------ notifications
def test_notify_routes_snoozes_and_formats(monkeypatch):
    from datetime import timedelta, timezone

    from bioterm import notify
    from bioterm.db import init_db

    init_db()
    posts = []

    class _Resp:
        def raise_for_status(self):
            return None

    class _S:
        def post(self, url, json=None, data=None, headers=None, timeout=None):
            posts.append((url, json, data, headers))
            return _Resp()

    monkeypatch.setattr(notify, "session", lambda: _S())
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    monkeypatch.setenv("NTFY_TOPIC", "bioterm-test-topic")
    assert notify.configured()["slack"] and notify.configured()["ntfy"]
    notify.set_routes({"headline": ["slack"]})
    notify.snooze("MUTE", datetime.now(timezone.utc) + timedelta(days=1))
    sent = notify.send_alerts([
        {"kind": "headline", "ticker": "AAA", "detail": "topline"},
        {"kind": "halt", "ticker": "BBB", "detail": "T1 news pending"},
        {"kind": "halt", "ticker": "MUTE", "detail": "muted"},
    ])
    assert sent == {"slack": 2, "ntfy": 1}                   # headline only to slack
    ntfy = next(p for p in posts if "ntfy" in p[0])
    assert ntfy[3]["Priority"] == "high" and b"BBB" in ntfy[2] and b"MUTE" not in ntfy[2]
    slack = next(p for p in posts if "slack" in p[0])
    assert "📰 AAA — topline" in slack[1]["text"]


def test_claiming_a_hosted_database_needs_its_password(monkeypatch):
    from bioterm import auth
    from bioterm.db import init_db

    init_db()
    assert not auth.claim_proof_required()           # local SQLite: no proof
    monkeypatch.setattr(auth, "_db_password", lambda: "neon-db-pw")
    assert auth.claim_proof_required()
    with pytest.raises(PermissionError):
        auth.claim("a good passcode")
    with pytest.raises(PermissionError):
        auth.claim("a good passcode", "wrong")
    auth.claim("a good passcode", "neon-db-pw")
    assert auth.is_claimed() and auth.verify("a good passcode")
