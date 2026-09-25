"""Alert delivery: Telegram, Slack, Discord, ntfy (phone push) and email.

Credentials come from the vault (entered on the dashboard's Settings page) or
the environment. Routing - which alert kinds go to which channel - snoozed
tickers and the daily digest switch live in ``app_meta`` and are edited on the
Alerts page. Every send is fail-soft: a broken channel is logged and skipped.
"""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Iterable

from . import vault
from .httpx_util import session

log = logging.getLogger("bioterm.notify")

CHANNELS = ("telegram", "slack", "discord", "ntfy", "email")
LABELS = {"telegram": "Telegram", "slack": "Slack", "discord": "Discord",
          "ntfy": "Phone push (ntfy)", "email": "Email"}
KINDS = ("signal", "halt", "filing", "mover", "catalyst soon", "headline", "score move",
         "trial change", "read-through", "screen", "pdufa", "digest", "dq")
ICONS = {"score move": "📈", "catalyst soon": "🗓", "headline": "📰", "signal": "🚦",
         "halt": "⛔", "filing": "📄", "mover": "⚡", "trial change": "🧪",
         "read-through": "🔗", "screen": "🔎", "pdufa": "🏛", "digest": "🗞", "dq": "🩺"}


def configured() -> dict[str, bool]:
    g = vault.get
    return {
        "telegram": bool(g("TELEGRAM_BOT_TOKEN") and g("TELEGRAM_CHAT_ID")),
        "slack": bool(g("SLACK_WEBHOOK_URL")),
        "discord": bool(g("DISCORD_WEBHOOK_URL")),
        "ntfy": bool(g("NTFY_TOPIC")),
        "email": bool(g("SMTP_HOST") and g("SMTP_FROM") and g("SMTP_TO")),
    }


# ---------------------------------------------------------------- settings
def routes() -> dict[str, list[str]]:
    """{kind: [channel, ...]}; a kind with no entry goes to every channel."""
    from .store import get_meta

    r = get_meta("notify_routes", {}) or {}
    return {k: [c for c in v if c in CHANNELS] for k, v in r.items() if isinstance(v, list)}


def set_routes(r: dict[str, list[str]]) -> None:
    from .store import set_meta

    set_meta("notify_routes", {k: list(v) for k, v in r.items()})


def snoozes() -> dict[str, str]:
    """{TICKER: ISO timestamp until which its alerts are muted}."""
    from .store import get_meta

    s = get_meta("notify_snooze", {}) or {}
    now = datetime.now(timezone.utc).isoformat()
    return {k: v for k, v in s.items() if str(v) > now}


def snooze(ticker: str, until: datetime | None) -> None:
    from .store import set_meta

    s = snoozes()
    if until is None:
        s.pop(ticker.upper(), None)
    else:
        s[ticker.upper()] = until.astimezone(timezone.utc).isoformat()
    set_meta("notify_snooze", s)


def _wanted(channel: str, kind: str | None, rt: dict[str, list[str]]) -> bool:
    return kind is None or kind not in rt or channel in rt[kind]


# ---------------------------------------------------------------- transports
def _telegram(title: str, lines: list[str]) -> None:
    token, chat = vault.get("TELEGRAM_BOT_TOKEN"), vault.get("TELEGRAM_CHAT_ID")
    body = f"<b>{html.escape(title)}</b>\n" + "\n".join(html.escape(x) for x in lines)
    r = session().post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat, "text": body[:4000], "parse_mode": "HTML",
                             "disable_web_page_preview": True}, timeout=15)
    r.raise_for_status()


def _slack(title: str, lines: list[str]) -> None:
    r = session().post(vault.get("SLACK_WEBHOOK_URL"),
                       json={"text": f"*{title}*\n" + "\n".join(lines)}, timeout=15)
    r.raise_for_status()


def _discord(title: str, lines: list[str]) -> None:
    text = f"**{title}**\n" + "\n".join(lines)
    r = session().post(vault.get("DISCORD_WEBHOOK_URL"), json={"content": text[:1990]},
                       timeout=15)
    r.raise_for_status()


def _ntfy(title: str, lines: list[str], urgent: bool = False) -> None:
    server = (vault.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    headers = {"Title": title.encode("ascii", "ignore").decode() or "BioTerm",
               "Priority": "high" if urgent else "default", "Tags": "dna"}
    tok = vault.get("NTFY_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    r = session().post(f"{server}/{vault.get('NTFY_TOPIC')}",
                       data="\n".join(lines)[:3900].encode(), headers=headers, timeout=15)
    r.raise_for_status()


def _email(title: str, lines: list[str]) -> None:
    host = vault.get("SMTP_HOST")
    port = int(vault.get("SMTP_PORT") or 465)
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = vault.get("SMTP_FROM")
    msg["To"] = vault.get("SMTP_TO")
    msg.set_content("\n".join(lines) + "\n\n-- BioTerm (monitoring only, not investment advice)")
    user, pw = vault.get("SMTP_USER"), vault.get("SMTP_PASSWORD")
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(),
                              timeout=20) as s:
            if user:
                s.login(user, pw or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            if user:
                s.login(user, pw or "")
            s.send_message(msg)


_SENDERS = {"telegram": _telegram, "slack": _slack, "discord": _discord, "email": _email}


def _send_one(channel: str, title: str, lines: list[str], urgent: bool) -> None:
    if channel == "ntfy":
        _ntfy(title, lines, urgent)
    else:
        _SENDERS[channel](title, lines)


# ---------------------------------------------------------------- public API
def format_alert(a: dict[str, Any]) -> str:
    icon = ICONS.get(str(a.get("kind")), "•")
    tk = a.get("ticker") or ""
    return f"{icon} {tk} — {a.get('detail', '')}".strip()


def send_alerts(alerts: Iterable[dict[str, Any]], *, title: str | None = None,
                max_lines: int = 15) -> dict[str, int]:
    """Deliver alerts to every configured channel their kind is routed to,
    skipping snoozed tickers. Returns {channel: alerts sent}."""
    items = list(alerts)
    if not items:
        return {}
    conf, rt, muted = configured(), routes(), snoozes()
    items = [a for a in items if str(a.get("ticker") or "").upper() not in muted]
    sent: dict[str, int] = {}
    for ch in CHANNELS:
        if not conf.get(ch):
            continue
        mine = [a for a in items if _wanted(ch, a.get("kind"), rt)]
        if not mine:
            continue
        lines = [format_alert(a) for a in mine[:max_lines]]
        if len(mine) > max_lines:
            lines.append(f"…and {len(mine) - max_lines} more")
        urgent = any(a.get("kind") in ("halt", "signal") for a in mine)
        try:
            _send_one(ch, title or f"BioTerm — {len(mine)} new alert(s)", lines, urgent)
            sent[ch] = len(mine)
        except Exception as exc:  # noqa: BLE001 - one broken channel mustn't stop the rest
            log.warning("notify: %s failed: %s", ch, exc)
    return sent


def send_text(title: str, lines: list[str], *, kind: str | None = None,
              urgent: bool = False) -> dict[str, bool]:
    conf, rt = configured(), routes()
    out = {}
    for ch in CHANNELS:
        if conf.get(ch) and _wanted(ch, kind, rt):
            try:
                _send_one(ch, title, lines, urgent)
                out[ch] = True
            except Exception as exc:  # noqa: BLE001
                log.warning("notify: %s failed: %s", ch, exc)
                out[ch] = False
    return out


def test(channel: str) -> tuple[bool, str]:
    if not configured().get(channel):
        return False, f"{LABELS[channel]} isn't configured"
    try:
        _send_one(channel, "BioTerm test", ["If you can read this, alerts will arrive here."],
                  False)
        return True, f"Test sent to {LABELS[channel]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{LABELS[channel]}: {exc}"
