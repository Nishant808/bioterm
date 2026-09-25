"""AI layer: provider routing, the Claude adapter (SDK faked - no network),
spend metering and budget, Copilot tools with citations, and the background
extraction jobs."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest


def _usage(i=100, o=50):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=0,
              cache_creation_input_tokens=0, iterations=None)


def _msg(content, stop="end_turn", model="claude-opus-5", usage=None):
    return NS(content=content, stop_reason=stop, model=model, usage=usage or _usage(),
              stop_details=None)


def _text(t):
    return NS(type="text", text=t)


class FakeStream:
    def __init__(self, msg, events):
        self._msg, self._events = msg, events

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._msg


class FakeClient:
    """Stands in for anthropic.Anthropic: records every request."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        outer = self

        class _Msgs:
            def create(self, **kw):
                outer.calls.append(kw)
                return outer.replies.pop(0)

            def stream(self, **kw):
                outer.calls.append({**kw, "messages": list(kw["messages"])})
                m = outer.replies.pop(0)
                ev = [NS(type="text", text=b.text) for b in m.content if b.type == "text"]
                return FakeStream(m, ev)

        self.beta = NS(messages=_Msgs())


@pytest.fixture
def db():
    from bioterm.db import init_db

    init_db()


@pytest.fixture
def claude_key(monkeypatch, db):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _fake(monkeypatch, replies):
    from bioterm.ai import claude

    fc = FakeClient(replies)
    monkeypatch.setattr(claude, "_client", lambda key, timeout=120.0: fc)
    return fc


# ---------------------------------------------------------------- routing
def test_provider_routing(monkeypatch, db):
    from bioterm import ai

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai.provider() is None and not ai.available()
    with pytest.raises(ai.AIUnavailable):
        ai.complete("x", system="y")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
    assert ai.provider() == "openai"
    with pytest.raises(ai.AIUnavailable):          # no model name set yet
        ai.model_for("copilot")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
    assert ai.provider() == "anthropic" and ai.model_for() == "claude-opus-5"
    ai.save_settings(provider="openai", openai_model="some-model")
    assert ai.provider() == "openai" and ai.model_for() == "some-model"
    ai.save_settings(provider="auto", model_bulk="claude-haiku-4-5")
    assert ai.model_for("bulk") == "claude-haiku-4-5"


# ---------------------------------------------------------------- claude adapter
def test_structured_completion_uses_fallbacks_and_meters_cost(monkeypatch, claude_key):
    from bioterm import ai

    fc = _fake(monkeypatch, [_msg([NS(type="thinking", thinking=""), _text('{"a": 1}')],
                                  usage=_usage(1_000_000, 100_000))])
    res = ai.complete("hi", system="sys", json_schema={"type": "object"}, effort="low")
    assert res.data == {"a": 1}
    call = fc.calls[0]
    assert call["model"] == "claude-opus-5" and call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"] == {"effort": "low",
                                     "format": {"type": "json_schema",
                                                "schema": {"type": "object"}}}
    assert abs(ai.spent_today() - (5.0 + 2.5)) < 1e-6       # $5/M in + $25/M out


def test_haiku_gets_no_effort_or_fallback(monkeypatch, claude_key):
    from bioterm import ai

    ai.save_settings(model_bulk="claude-haiku-4-5")
    fc = _fake(monkeypatch, [_msg([_text("ok")], model="claude-haiku-4-5")])
    ai.complete("hi", system="sys", role="bulk")
    assert "fallbacks" not in fc.calls[0] and "output_config" not in fc.calls[0]


def test_refusal_is_raised_before_content_is_read(monkeypatch, claude_key):
    from bioterm import ai

    m = _msg([], stop="refusal")
    m.stop_details = NS(category="bio")
    _fake(monkeypatch, [m])
    with pytest.raises(ai.Refused) as ei:
        ai.complete("x", system="y")
    assert ei.value.category == "bio"
    assert ai.spent_today() > 0                               # the declined call is metered


def test_budget_stops_background_jobs_but_copilot_gets_headroom(monkeypatch, claude_key):
    from bioterm import ai

    ai.save_settings(daily_budget_usd=1.0)
    ai.record([ai.Usage("claude-opus-5", input_tokens=220_000)], "anthropic")   # $1.10
    with pytest.raises(ai.BudgetExceeded):
        ai.check_budget()
    ai.check_budget(interactive=True)                         # 1.5x headroom


# ---------------------------------------------------------------- copilot loop
def _seed_company():
    from bioterm.db import bulk_upsert, catalysts, filings, fundamentals, securities

    today = date.today()
    now = datetime.now(timezone.utc)
    bulk_upsert(securities, [{"ticker": "AAAA", "name": "AAAA BIO INC", "in_xbi": 1},
                             {"ticker": "BBBB", "name": "BBBB PHARMA", "in_xbi": 1}])
    bulk_upsert(fundamentals, [
        {"ticker": "AAAA", "market_cap": 1.0e8, "cash": 2.0e8, "total_debt": 0,
         "runway_quarters": 6, "updated_at": now},
        {"ticker": "BBBB", "market_cap": 5.0e9, "cash": 1.0e9, "runway_quarters": 20,
         "updated_at": now}])
    bulk_upsert(catalysts, [{"id": "c1", "ticker": "AAAA", "type": "pdufa",
                             "title": "PDUFA for aaaamab", "date": today + timedelta(days=30),
                             "confidence": "high", "source": "manual",
                             "url": "https://example.com/pr", "created_at": now}])
    bulk_upsert(filings, [{"id": "AAAA:0000000000-26-000001", "ticker": "AAAA", "cik": "1",
                           "form": "8-K", "filed_date": today, "title": "8-K", "items": "8.01",
                           "url": "https://www.sec.gov/Archives/edgar/data/1/x/a.htm",
                           "fetched_at": now}])


def test_copilot_runs_tools_and_cites_sources(monkeypatch, claude_key):
    from bioterm.ai import copilot

    _seed_company()
    tool_call = NS(type="tool_use", id="tu_1", name="upcoming_catalysts",
                   input={"ticker": "AAAA", "days_ahead": 90})
    bad_call = NS(type="tool_use", id="tu_2", name="company_snapshot", input={"tkr": "X"})
    fc = _fake(monkeypatch, [
        _msg([_text("Checking the calendar."), tool_call, bad_call], stop="tool_use"),
        _msg([_text("AAAA has a PDUFA date in 30 days [1].")]),
    ])
    steps, tools, streamed = [], [], []
    turn = copilot.ask("When is AAAA's PDUFA?", [], on_text=streamed.append,
                       on_step=steps.append, on_tool=lambda n, a: tools.append(n))
    assert turn.text == "AAAA has a PDUFA date in 30 days [1]."
    assert turn.sources and turn.sources[0]["url"] == "https://example.com/pr"
    assert tools == ["upcoming_catalysts"] and steps == [0, 1]
    second = fc.calls[1]["messages"]
    results = second[-1]["content"]
    assert results[0]["tool_use_id"] == "tu_1" and "PDUFA for aaaamab" in results[0]["content"]
    assert results[1]["is_error"] and "INVALID_JSON" in results[1]["content"]
    assert all(t.get("eager_input_streaming") for t in fc.calls[0]["tools"])
    assert "today is" in fc.calls[0]["messages"][-1]["content"]


def test_tools_screen_and_validate(db):
    from bioterm.ai import tools

    _seed_company()
    src = tools.Sources()
    res = tools.screen_universe(src, below_cash=True)
    assert [m["ticker"] for m in res["matches"]] == ["AAAA"]
    snap = tools.company_snapshot(src, "aaaa")
    assert snap["fundamentals"]["enterprise_value"] == -1.0e8
    assert snap["next_catalysts"][0]["ref"] == 1
    assert tools.validate({"ticker": "AAAA"}, tools.by_name()["company_snapshot"].schema) is None
    assert tools.validate({}, tools.by_name()["company_snapshot"].schema)
    assert tools.validate({"label": "MAYBE"}, tools.by_name()["signal_board"].schema)
    assert tools.validate({"limit": True},
                          tools.by_name()["signal_board"].schema)   # bool is not an int
    assert "only https://www.sec.gov" in json.dumps(
        tools.read_sec_document(src, "https://evil.example.com/x"))


# ---------------------------------------------------------------- jobs
def test_news_events_extracts_pdufa_dates(monkeypatch, claude_key):
    from bioterm.ai import jobs
    from bioterm.db import bulk_upsert, news, read_sql

    now = datetime.now(timezone.utc)
    pdufa = (date.today() + timedelta(days=120)).isoformat()
    bulk_upsert(news, [
        {"id": "n1", "ticker": "AAAA", "tickers_csv": "AAAA",
         "title": "AAAA announces FDA acceptance of BLA with PDUFA date", "summary": "",
         "url": "https://x/1", "source": "GlobeNewswire", "published": now},
        {"id": "n2", "ticker": "AAAA", "tickers_csv": "AAAA",
         "title": "AAAA to ring the opening bell", "summary": "", "url": "https://x/2",
         "source": "PR", "published": now}])
    reply = {"items": [{"id": "n1", "ticker": "AAAA", "event_type": "pdufa_date_set",
                        "outcome": "positive", "endpoint_met": None, "drug": "aaaamab",
                        "indication": "X", "pdufa_date": pdufa, "adcom_date": "1999-01-01",
                        "summary": "FDA accepted the BLA.", "confidence": 0.9}]}
    fc = _fake(monkeypatch, [_msg([_text(json.dumps(reply))])])
    out = jobs.news_events()
    assert out["rows"] == 1 and out["scanned"] == 1          # the bell-ringing PR is skipped
    sent = json.loads(fc.calls[0]["messages"][0]["content"])["items"]
    assert [i["id"] for i in sent] == ["n1"]
    row = read_sql("SELECT * FROM news_llm").iloc[0]
    assert str(row["pdufa_date"])[:10] == pdufa and row["adcom_date"] is None  # implausible


def test_risk_factor_diff():
    from bioterm.ai import jobs

    old = ("Item 1A. Risk Factors " + "We depend on the success of our lead product candidate "
           "which is in clinical development. " * 1 +
           "We may need to raise additional capital to fund our operations in the future. "
           "Item 1B. Unresolved Staff Comments")
    new = ("Item 1A. Risk Factors We depend on the success of our lead product candidate "
           "which is in clinical development. The FDA has placed a clinical hold on our Phase 2 "
           "trial of our lead product candidate and it may not be lifted. "
           "Item 1B. Unresolved Staff Comments")
    added, removed = jobs.diff_risks(jobs.risk_section(old), jobs.risk_section(new))
    assert len(added) == 1 and "clinical hold" in added[0]
    assert len(removed) == 1 and "raise additional capital" in removed[0]


def test_openai_compatible_provider(monkeypatch, db):
    from bioterm import ai
    from bioterm.ai import openai_compat

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
    ai.save_settings(openai_model="m-1")
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {"model": "m-1", "choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    def fake_post(url, headers=None, data=None, timeout=None):
        seen["url"], seen["body"] = url, json.loads(data)
        return _R()

    monkeypatch.setattr(openai_compat.requests, "post", fake_post)
    res = ai.complete("x", system="s", json_schema={"type": "object"})
    assert res.data == {"ok": True} and res.provider == "openai"
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["body"]["max_completion_tokens"] == 4000
    assert seen["body"]["response_format"]["type"] == "json_schema"
