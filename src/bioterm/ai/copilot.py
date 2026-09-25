"""Research Copilot: a tool-using conversation over the BioTerm database with
numbered source citations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from . import run_agent
from .tools import TOOLS, Sources, executor

SYSTEM = """\
You are BioTerm Copilot, the research assistant inside BioTerm - a monitoring terminal for \
US-listed biotech and pharma with a six-month swing horizon. BioTerm tracks prices, catalysts \
(PDUFA dates, advisory committees, trial readouts), ClinicalTrials.gov records, SEC filings, \
insider trades, specialist-fund 13F holdings, news, options and short-sale flow, and computes a \
Focus Score and screening signals.

How to answer:
- Get facts from the tools. Don't rely on memory for prices, dates, holdings, trial status or \
filings; when the tools don't have something, say so plainly.
- Cite sources: tool rows carrying a "ref" number are sources - put [n] right after the claim it \
supports, using only refs the tools returned.
- Give absolute dates (YYYY-MM-DD) and say how fresh data is when it matters (13F holdings are \
quarter-end positions filed up to 45 days later; fundamentals update daily).
- BioTerm's signal labels (STRONG BUY ... STRONG SELL) and Focus Score are screening states \
computed from evidence, not recommendations. Explain what drives them. Never tell the user to \
buy or sell, and never give price targets or position sizes.
- Lead with the answer, then the evidence. Prefer short bullets or a compact table. Keep it \
under about 250 words unless the user asks for depth.
"""


@dataclass
class Turn:
    text: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    model: str = ""
    cost: float = 0.0


def ask(question: str, history: list[dict[str, str]], *,
        on_text: Callable[[str], None], on_step: Callable[[int], None],
        on_tool: Callable[[str, dict], None], now: datetime | None = None) -> Turn:
    from ..market_calendar import NY, session

    t = (now or datetime.now(NY)).astimezone(NY)
    _, label = session(t)
    src = Sources()
    used: list[str] = []

    def tool_seen(name: str, args: dict) -> None:
        used.append(name)
        on_tool(name, args)

    framed = (f"(Context: today is {t:%Y-%m-%d}, {t:%H:%M} New York time - {label}.)\n\n"
              f"{question.strip()}")
    res = run_agent(framed, history, tools=TOOLS, execute=executor(src), on_text=on_text,
                    on_step=on_step, on_tool=tool_seen, system=SYSTEM)
    return Turn(text=res.text, sources=src.cited(res.text), tools_used=used,
                model=res.model, cost=res.cost)
