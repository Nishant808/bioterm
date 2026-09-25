"""LLM features: provider choice, model settings, spend tracking, one call API.

Claude (Anthropic) is the primary provider, called through the official
``anthropic`` SDK in ``claude.py``. Any OpenAI-compatible endpoint (OpenAI,
OpenRouter, Groq, Together, a local server) is the alternative, in
``openai_compat.py``. Keys live in the encrypted vault (Settings page) or the
environment - ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` (+ ``OPENAI_BASE_URL``).

Everything here is optional: with no key the terminal works exactly as before
and the AI surfaces say how to switch them on.

Spend is metered per call into ``llm_usage`` (tokens + an estimate in USD) and a
daily budget, set on the Settings page, stops the background jobs - never a
half-written answer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

log = logging.getLogger("bioterm.ai")

META_KEY = "ai_settings"

# Claude models offered in Settings (exact API ids)
CLAUDE_MODELS = {
    "claude-opus-5": "Claude Opus 5 - most capable (default)",
    "claude-sonnet-5": "Claude Sonnet 5 - balanced, ~60% cheaper",
    "claude-haiku-4-5": "Claude Haiku 4.5 - fastest, cheapest",
}
DEFAULT_CLAUDE = "claude-opus-5"

# USD per million tokens: input, output, cache read. Cache writes bill at 1.25x input.
PRICES = {
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
    "claude-opus-4-8": (5.0, 25.0, 0.50),      # server-side fallback target
}
UNKNOWN_PRICE = (3.0, 15.0, 0.30)      # conservative guess for other providers' models

DEFAULTS: dict[str, Any] = {
    "provider": "auto",                 # auto | anthropic | openai
    "model_copilot": DEFAULT_CLAUDE,     # interactive: Copilot, brief
    "model_bulk": DEFAULT_CLAUDE,        # background: news/filing extraction, summaries
    "openai_model": "",                 # e.g. the model name your endpoint serves
    "daily_budget_usd": 2.0,
    "jobs": {"news": True, "filings": True, "brief": True, "risk": True, "pdufa": True},
}


class AIUnavailable(RuntimeError):
    """No provider configured (no key) - the feature is off."""


class BudgetExceeded(RuntimeError):
    pass


class Refused(RuntimeError):
    """The model (or its safety classifier) declined the request."""

    def __init__(self, category: str | None = None, message: str = ""):
        self.category = category
        super().__init__(message or f"the model declined this request"
                         f"{f' ({category})' if category else ''}")


# ---------------------------------------------------------------- settings
def settings() -> dict[str, Any]:
    from ..store import get_meta

    s = dict(DEFAULTS)
    stored = get_meta(META_KEY, {}) or {}
    if isinstance(stored, dict):
        s.update({k: v for k, v in stored.items() if k in DEFAULTS})
        s["jobs"] = {**DEFAULTS["jobs"], **(stored.get("jobs") or {})}
    return s


def save_settings(**changes: Any) -> dict[str, Any]:
    from ..store import set_meta

    s = settings()
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise KeyError(k)
        if k == "jobs":
            s["jobs"] = {**s["jobs"], **(v or {})}
        else:
            s[k] = v
    set_meta(META_KEY, s)
    return s


# ---------------------------------------------------------------- provider
def _key(name: str) -> str | None:
    from .. import vault

    return vault.get(name)


def provider() -> str | None:
    """The provider calls go to, or None when no key is configured."""
    pref = settings().get("provider", "auto")
    have_a, have_o = bool(_key("ANTHROPIC_API_KEY")), bool(_key("OPENAI_API_KEY"))
    if pref == "anthropic":
        return "anthropic" if have_a else None
    if pref == "openai":
        return "openai" if have_o else None
    return "anthropic" if have_a else ("openai" if have_o else None)


def available() -> bool:
    return provider() is not None


def model_for(role: str = "copilot") -> str:
    s = settings()
    if provider() == "openai":
        m = (s.get("openai_model") or "").strip()
        if not m:
            raise AIUnavailable("set the OpenAI-compatible model name on the Settings page")
        return m
    m = s.get("model_bulk" if role == "bulk" else "model_copilot") or DEFAULT_CLAUDE
    return m if m in PRICES else DEFAULT_CLAUDE


def status() -> dict[str, Any]:
    p = provider()
    try:
        m = model_for("copilot") if p else None
    except AIUnavailable:
        m = None
    return {"provider": p, "model": m, "spent_today": spent_today(),
            "budget": float(settings().get("daily_budget_usd") or 0)}


# ---------------------------------------------------------------- usage / budget
@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def cost(self) -> float:
        pin, pout, pcache = PRICES.get(self.model, UNKNOWN_PRICE)
        return (self.input_tokens * pin + self.output_tokens * pout
                + self.cache_read_tokens * pcache
                + self.cache_write_tokens * pin * 1.25) / 1e6


def record(usages: list[Usage], provider_name: str) -> float:
    """Add calls to today's ``llm_usage`` row per model; returns their USD cost."""
    from sqlalchemy import select

    from ..db import bulk_upsert, get_engine, llm_usage

    total = 0.0
    day = datetime.now(timezone.utc).date()
    by_model: dict[str, list[Usage]] = {}
    for u in usages:
        by_model.setdefault(u.model, []).append(u)
    try:
        for model, us in by_model.items():
            with get_engine().connect() as conn:
                row = conn.execute(select(llm_usage).where(
                    (llm_usage.c.day == day) & (llm_usage.c.model == model))).mappings().first()
            cost = sum(u.cost for u in us)
            total += cost
            base = dict(row) if row else {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                          "cache_read_tokens": 0, "cost_usd": 0.0}
            bulk_upsert(llm_usage, [{
                "day": day, "model": model, "provider": provider_name,
                "calls": int(base.get("calls") or 0) + len(us),
                "input_tokens": int(base.get("input_tokens") or 0)
                + sum(u.input_tokens + u.cache_write_tokens for u in us),
                "output_tokens": int(base.get("output_tokens") or 0)
                + sum(u.output_tokens for u in us),
                "cache_read_tokens": int(base.get("cache_read_tokens") or 0)
                + sum(u.cache_read_tokens for u in us),
                "cost_usd": float(base.get("cost_usd") or 0.0) + cost,
            }])
    except Exception as exc:  # noqa: BLE001 - metering must never break a feature
        log.warning("llm usage not recorded: %s", exc)
    return total


def spent_today() -> float:
    from ..db import read_sql

    try:
        df = read_sql("SELECT SUM(cost_usd) AS c FROM llm_usage WHERE day = :d",
                      {"d": datetime.now(timezone.utc).date()})
        v = df.iloc[0]["c"] if not df.empty else 0.0
        return float(v or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def usage_history(days: int = 30):
    from ..db import read_sql

    cut = (datetime.now(timezone.utc).date().toordinal() - days)
    return read_sql("SELECT * FROM llm_usage WHERE day >= :c ORDER BY day",
                    {"c": date.fromordinal(cut)})


def check_budget(interactive: bool = False) -> None:
    """Background jobs stop at the daily budget; interactive use (Copilot) gets
    50% headroom on top so a question asked late in the day still works."""
    budget = float(settings().get("daily_budget_usd") or 0)
    if budget <= 0:
        return
    cap = budget * (1.5 if interactive else 1.0)
    spent = spent_today()
    if spent >= cap:
        raise BudgetExceeded(f"today's AI budget is used up (${spent:.2f} of ${budget:.2f}) - "
                             "raise it on the Settings page")


# ---------------------------------------------------------------- one-call API
@dataclass
class Result:
    text: str
    data: Any = None                        # parsed JSON when a schema was given
    model: str = ""
    provider: str = ""
    usage: list[Usage] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return sum(u.cost for u in self.usage)


def complete(prompt: str, *, system: str, role: str = "bulk", max_tokens: int = 4000,
             json_schema: dict | None = None, effort: str = "low",
             interactive: bool = False) -> Result:
    """One request -> text (or schema-valid JSON in ``Result.data``)."""
    p = provider()
    if p is None:
        raise AIUnavailable("no LLM key configured - add one on the Settings page")
    check_budget(interactive)
    model = model_for(role)
    if p == "anthropic":
        from . import claude

        res = claude.complete(_key("ANTHROPIC_API_KEY"), model=model, system=system,
                              prompt=prompt, max_tokens=max_tokens, json_schema=json_schema,
                              effort=effort)
    else:
        from . import openai_compat

        res = openai_compat.complete(_key("OPENAI_API_KEY"), _key("OPENAI_BASE_URL"),
                                     model=model, system=system, prompt=prompt,
                                     max_tokens=max_tokens, json_schema=json_schema)
    record(res.usage, p)
    return res


def test_key(provider_name: str, key: str, base_url: str | None = None) -> tuple[bool, str]:
    """Validate a key before it is stored (no tokens spent)."""
    if provider_name == "anthropic":
        from . import claude

        return claude.test_key(key)
    from . import openai_compat

    return openai_compat.test_key(key, base_url)


def run_agent(question: str, history: list[dict[str, str]], *, tools: list,
              execute: Callable[[str, dict], str], on_text: Callable[[str], None],
              on_step: Callable[[int], None], on_tool: Callable[[str, dict], None],
              system: str, max_steps: int = 10) -> Result:
    """Tool-using conversation turn for the Copilot (streams text via ``on_text``)."""
    p = provider()
    if p is None:
        raise AIUnavailable("no LLM key configured - add one on the Settings page")
    check_budget(interactive=True)
    model = model_for("copilot")
    if p == "anthropic":
        from . import claude

        res = claude.run_agent(_key("ANTHROPIC_API_KEY"), model=model, system=system,
                               history=history, question=question, tools=tools,
                               execute=execute, on_text=on_text, on_step=on_step,
                               on_tool=on_tool, max_steps=max_steps)
    else:
        from . import openai_compat

        res = openai_compat.run_agent(_key("OPENAI_API_KEY"), _key("OPENAI_BASE_URL"),
                                      model=model, system=system, history=history,
                                      question=question, tools=tools, execute=execute,
                                      on_text=on_text, on_step=on_step, on_tool=on_tool,
                                      max_steps=max_steps)
    record(res.usage, p)
    return res
