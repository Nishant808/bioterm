"""Alternative LLM provider: any OpenAI-compatible Chat Completions endpoint
(OpenAI, OpenRouter, Groq, Together, vLLM/Ollama servers ...), over plain HTTPS.

Selected on the Settings page (or automatically when only an OpenAI key is
stored). The base URL defaults to https://api.openai.com/v1 and the model name
is whatever the endpoint serves - set it in Settings.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

import requests

from . import Result, Usage

log = logging.getLogger("bioterm.ai.openai")

DEFAULT_BASE = "https://api.openai.com/v1"


def _base(base_url: str | None) -> str:
    return (base_url or DEFAULT_BASE).rstrip("/")


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _post(key: str, base_url: str | None, body: dict[str, Any], timeout: float = 120) -> dict:
    r = requests.post(f"{_base(base_url)}/chat/completions", headers=_headers(key),
                      data=json.dumps(body), timeout=(10, timeout))
    if r.status_code >= 400:
        raise RuntimeError(f"LLM endpoint error {r.status_code}: {r.text[:300]}")
    return r.json()


def _usage(payload: dict, model: str) -> list[Usage]:
    u = payload.get("usage") or {}
    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    return [Usage(model=payload.get("model") or model,
                  input_tokens=max(0, int(u.get("prompt_tokens") or 0) - int(cached)),
                  output_tokens=int(u.get("completion_tokens") or 0),
                  cache_read_tokens=int(cached))]


def _limit_field(base_url: str | None) -> str:
    # OpenAI's own API renamed the output cap; most compatible servers keep max_tokens
    return "max_completion_tokens" if _base(base_url) == DEFAULT_BASE else "max_tokens"


def test_key(key: str, base_url: str | None = None) -> tuple[bool, str]:
    try:
        r = requests.get(f"{_base(base_url)}/models", headers=_headers(key), timeout=15)
    except requests.RequestException as exc:
        return False, f"Can't reach {_base(base_url)}: {exc.__class__.__name__}"
    if r.status_code in (401, 403):
        return False, "Invalid API key"
    if r.status_code >= 400:
        return False, f"Endpoint error {r.status_code}"
    try:
        n = len((r.json() or {}).get("data") or [])
    except ValueError:
        n = 0
    return True, f"Key works{f' - {n} models available' if n else ''}"


def complete(key: str, base_url: str | None, *, model: str, system: str, prompt: str,
             max_tokens: int = 4000, json_schema: dict | None = None) -> Result:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        _limit_field(base_url): max_tokens,
    }
    if json_schema:
        if _base(base_url) == DEFAULT_BASE:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "result", "schema": json_schema, "strict": False}}
        else:
            body["response_format"] = {"type": "json_object"}
            body["messages"][0]["content"] += (
                "\n\nReply with one JSON object matching this JSON Schema, nothing else:\n"
                + json.dumps(json_schema))
    payload = _post(key, base_url, body)
    choice = (payload.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    data = None
    if json_schema:
        s, e = text.find("{"), text.rfind("}")
        data = json.loads(text[s:e + 1] if s >= 0 and e > s else text)
    return Result(text=text, data=data, model=payload.get("model") or model,
                  provider="openai", usage=_usage(payload, model))


def run_agent(key: str, base_url: str | None, *, model: str, system: str,
              history: list[dict[str, str]], question: str, tools: list,
              execute: Callable[[str, dict], str], on_text: Callable[[str], None],
              on_step: Callable[[int], None], on_tool: Callable[[str, dict], None],
              max_steps: int = 10) -> Result:
    from .tools import validate

    defs = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.schema}} for t in tools]
    schemas = {t.name: t.schema for t in tools}
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history
                 if m.get("role") in ("user", "assistant") and m.get("content")]
    messages.append({"role": "user", "content": question})
    usages: list[Usage] = []
    final, served = "", model
    for step in range(max_steps):
        on_step(step)
        payload = _post(key, base_url, {"model": model, "messages": messages, "tools": defs,
                                         _limit_field(base_url): 8000}, timeout=240)
        usages += _usage(payload, model)
        served = payload.get("model") or served
        msg = ((payload.get("choices") or [{}])[0]).get("message") or {}
        text = msg.get("content") or ""
        if text:
            on_text(text)
        final = text
        calls = msg.get("tool_calls") or []
        if not calls:
            break
        messages.append({"role": "assistant", "content": text or None, "tool_calls": calls})
        for c in calls:
            fn = c.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = None
            schema = schemas.get(name)
            err = ("unknown tool" if schema is None else
                   "arguments are not valid JSON" if args is None else validate(args, schema))
            if err:
                out = json.dumps({"error": err})
            else:
                on_tool(name, args)
                try:
                    out = execute(name, args)
                except Exception as exc:  # noqa: BLE001
                    out = f"Error: {exc}"
            messages.append({"role": "tool", "tool_call_id": c.get("id"), "content": out})
    else:
        final += "\n\n*(Stopped after the maximum number of lookups - ask a narrower question.)*"
    return Result(text=final, model=served, provider="openai", usage=usages)
