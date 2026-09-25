"""Claude through the official Anthropic Python SDK.

- Adaptive thinking is the default on the Claude 5 models; cost and depth are
  steered with ``output_config.effort`` (low for bulk extraction, medium for the
  Copilot).
- Structured extraction uses ``output_config.format`` (JSON schema) - the answer
  is guaranteed to parse.
- Claude Opus 5's safety classifiers can decline benign life-sciences text, so
  requests to it carry ``fallbacks: "default"`` (beta
  ``server-side-fallback-2026-07-01``): a declined request is re-run server-side
  on Anthropic's recommended fallback model inside the same call. A refusal that
  survives the chain surfaces as ``ai.Refused`` - ``stop_reason`` is checked
  before any content is read.
- The Copilot streams (``client.beta.messages.stream``) and runs a manual
  tool loop; tools declare ``eager_input_streaming`` so their inputs arrive as
  generated, and every input is validated against its schema before it runs.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

import anthropic

from . import Refused, Result, Usage

log = logging.getLogger("bioterm.ai.claude")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5"}
EFFORT_MODELS = {"claude-opus-5", "claude-opus-5-5", "claude-sonnet-5"}
_NO_FALLBACK: set[str] = set()      # models the server refused fallbacks for (this process)


def _client(key: str, timeout: float = 120.0) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=key, max_retries=2, timeout=timeout)


def _params(model: str, system: str, max_tokens: int, effort: str | None,
            json_schema: dict | None = None, tools: list | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "system": system,
                         "cache_control": {"type": "ephemeral"}}
    oc: dict[str, Any] = {}
    if effort and model in EFFORT_MODELS:
        oc["effort"] = effort
    if json_schema:
        oc["format"] = {"type": "json_schema", "schema": json_schema}
    if oc:
        p["output_config"] = oc
    if tools:
        p["tools"] = tools
    if model in FALLBACK_MODELS and model not in _NO_FALLBACK:
        p["betas"] = [FALLBACK_BETA]
        p["fallbacks"] = "default"
    return p


def _drop_fallback(p: dict[str, Any], exc: Exception) -> bool:
    """A 400 about the fallback parameter: remember it and retry without."""
    if "fallbacks" in p and "fallback" in str(exc).lower():
        log.warning("fallbacks rejected for %s - continuing without: %s", p["model"], exc)
        _NO_FALLBACK.add(p["model"])
        p.pop("fallbacks", None)
        p.pop("betas", None)
        return True
    return False


def _usages(msg: Any, requested: str) -> list[Usage]:
    u = msg.usage
    its = getattr(u, "iterations", None) or []
    if its:
        return [Usage(model=getattr(it, "model", None) or requested,
                      input_tokens=it.input_tokens or 0, output_tokens=it.output_tokens or 0,
                      cache_read_tokens=it.cache_read_input_tokens or 0,
                      cache_write_tokens=it.cache_creation_input_tokens or 0)
                for it in its]
    return [Usage(model=msg.model or requested, input_tokens=u.input_tokens or 0,
                  output_tokens=u.output_tokens or 0,
                  cache_read_tokens=u.cache_read_input_tokens or 0,
                  cache_write_tokens=u.cache_creation_input_tokens or 0)]


def _check_refusal(msg: Any) -> None:
    if msg.stop_reason == "refusal":
        cat = getattr(getattr(msg, "stop_details", None), "category", None)
        raise Refused(cat)


def _text(content) -> str:
    return "".join(b.text for b in content if getattr(b, "type", "") == "text")


def _echo(content) -> list:
    """Assistant content to send back next turn. After a mid-output fallback the
    blocks the declined model produced before the final ``fallback`` marker
    (thinking, tool calls) must not be echoed; the marker itself is dropped."""
    idx = max((i for i, b in enumerate(content) if b.type == "fallback"), default=None)
    drop = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(content)
            if b.type != "fallback" and not (idx is not None and i < idx and b.type in drop)]


# ---------------------------------------------------------------- public
def test_key(key: str) -> tuple[bool, str]:
    try:
        page = _client(key, timeout=20).models.list(limit=1)
        first = next(iter(page), None)
        return True, ("Key works" + (f" - e.g. {first.display_name}" if first else ""))
    except anthropic.AuthenticationError:
        return False, "Invalid API key"
    except anthropic.PermissionDeniedError:
        return False, "This key lacks permission for the Models API"
    except anthropic.APIConnectionError:
        return False, "Can't reach api.anthropic.com from this server"
    except anthropic.APIStatusError as e:
        return False, f"Anthropic API error {e.status_code}"


def complete(key: str, *, model: str, system: str, prompt: str, max_tokens: int = 4000,
             json_schema: dict | None = None, effort: str | None = "low") -> Result:
    client = _client(key)
    p = _params(model, system, max_tokens, effort, json_schema)
    p["messages"] = [{"role": "user", "content": prompt}]
    try:
        msg = client.beta.messages.create(**p)
    except anthropic.BadRequestError as exc:
        if not _drop_fallback(p, exc):
            raise
        msg = client.beta.messages.create(**p)
    usage = _usages(msg, model)
    if msg.stop_reason == "refusal":
        from . import record

        record(usage, "anthropic")        # a declined call still costs
        _check_refusal(msg)
    text = _text(msg.content)
    data = None
    if json_schema:
        if msg.stop_reason == "max_tokens":
            raise ValueError("structured answer truncated - raise max_tokens")
        data = json.loads(text)
    return Result(text=text, data=data, model=msg.model or model, provider="anthropic",
                  usage=usage)


def run_agent(key: str, *, model: str, system: str, history: list[dict[str, str]],
              question: str, tools: list, execute: Callable[[str, dict], str],
              on_text: Callable[[str], None], on_step: Callable[[int], None],
              on_tool: Callable[[str, dict], None], max_steps: int = 10) -> Result:
    from .tools import validate

    client = _client(key, timeout=300)
    defs = [{"name": t.name, "description": t.description, "input_schema": t.schema,
             "eager_input_streaming": True} for t in tools]
    schemas = {t.name: t.schema for t in tools}
    messages: list[dict[str, Any]] = [
        {"role": m["role"], "content": m["content"]} for m in history
        if m.get("role") in ("user", "assistant") and m.get("content")]
    messages.append({"role": "user", "content": question})
    p = _params(model, system, 16000, "medium", tools=defs)
    usages: list[Usage] = []
    final, served, json_retries, step = "", model, 0, 0
    while True:
        if step >= max_steps:
            final += "\n\n*(Stopped after the maximum number of lookups - ask a narrower question.)*"
            break
        on_step(step)
        try:
            with client.beta.messages.stream(messages=messages, **p) as stream:
                for event in stream:
                    if event.type == "text":
                        on_text(event.text)
                response = stream.get_final_message()
            json_retries = 0
        except ValueError:
            # tool-input JSON the SDK could not parse at all: no tool_use id to
            # answer, so re-issue the turn (bounded). API errors aren't ValueError.
            json_retries += 1
            if json_retries > 2:
                raise
            continue
        except anthropic.BadRequestError as exc:
            if not _drop_fallback(p, exc):
                raise
            continue
        step += 1
        usages += _usages(response, model)
        served = response.model or served
        if response.stop_reason == "refusal":
            from . import record

            record(usages, "anthropic")
            _check_refusal(response)
        content = _echo(response.content)
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": content})
            continue
        final = _text(content)
        calls = [b for b in content if b.type == "tool_use"]
        if not calls:
            break
        if response.stop_reason == "max_tokens":
            final += "\n\n*(The answer hit the length limit.)*"
            break
        results = []
        for b in calls:
            schema = schemas.get(b.name)
            err = "unknown tool" if schema is None else validate(b.input, schema)
            if err:
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                "content": json.dumps({"INVALID_JSON": json.dumps(b.input),
                                                       "error": err})})
                continue
            on_tool(b.name, b.input)
            try:
                out = execute(b.name, b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            except Exception as exc:  # noqa: BLE001 - report the failure to the model
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                "content": f"Error: {exc}"})
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": results})
    return Result(text=final, model=served, provider="anthropic", usage=usages)
