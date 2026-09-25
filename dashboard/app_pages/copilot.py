"""Copilot - ask the terminal. A tool-using LLM reads the BioTerm database (quotes,
fundamentals, catalysts, trials, filings, insiders, 13F funds, news, options,
signals) and answers with numbered sources."""
from __future__ import annotations

import streamlit as st

import _auth
from _ui import empty_state, md_safe, page_header, usd
from bioterm import ai

page_header("Copilot", "Ask about any company, catalyst, filing or screen · answers cite the "
                       "records they come from")

TOOL_LABELS = {
    "find_companies": "Searching the universe", "company_snapshot": "Company snapshot",
    "upcoming_catalysts": "Catalyst calendar", "clinical_trials": "Clinical trials",
    "sec_filings": "SEC filings", "read_sec_document": "Reading an SEC document",
    "news_headlines": "News", "insider_activity": "Insider trades",
    "fund_ownership": "13F fund holdings", "signal_board": "Signal board",
    "screen_universe": "Screening", "price_summary": "Price history",
    "options_and_short": "Options & short flow", "market_overview": "Sector overview",
}
EXAMPLES = [
    "Which names have a PDUFA date in the next 60 days, and how much cash do they have?",
    "Summarise the latest 8-K for the top STRONG BUY name",
    "Screen for companies trading below cash with a catalyst in the next 90 days",
    "What changed in specialist-fund holdings of the watchlist last quarter?",
]

if not ai.available():
    empty_state("Copilot is off",
                "Add an Anthropic (Claude) or OpenAI-compatible API key on the Settings page "
                "to switch it on.", "smart_toy")
    st.page_link("app_pages/settings.py", label="Open Settings", icon=":material/settings:")
    st.stop()

if not _auth.can_admin():
    empty_state("Copilot is available to the owner",
                "It runs on the owner's API key. Unlock with the owner passcode to ask "
                "questions.", "lock")
    _auth.guard("use the Copilot", key="copilot", admin=True)
    st.stop()

hist: list[dict] = st.session_state.setdefault("copilot", [])

with st.container(horizontal=True, horizontal_alignment="distribute",
                  vertical_alignment="center"):
    stt = ai.status()
    st.caption(f"{stt['model']} · {usd(stt['spent_today'], 2)} spent today"
               + (f" of {usd(stt['budget'], 2)}" if stt["budget"] else ""))
    if hist and st.button("New conversation", icon=":material/add_comment:", type="tertiary"):
        st.session_state["copilot"] = []
        st.rerun()


def _sources(items: list[dict]) -> None:
    if not items:
        return
    lines = [f"[{s['n']}] [{md_safe(s['title'])}]({s['url']})"
             + (f" · {s['date']}" if s.get("date") else "") for s in items]
    st.caption("  \n".join(lines))


for m in hist:
    with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user"
                         else ":material/smart_toy:"):
        st.markdown(md_safe(m["content"]))
        if m["role"] == "assistant":
            _sources(m.get("sources") or [])

picked = None
if not hist:
    picked = st.pills("Try", EXAMPLES, label_visibility="collapsed", key="cp_examples")

q = st.chat_input("Ask about a ticker, catalyst, filing, fund or screen…") or picked
if q:
    from bioterm.ai import copilot

    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(md_safe(q))
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        status = st.status("Researching…", expanded=False)
        box = st.empty()
        buf: list[str] = []

        def on_step(i: int) -> None:
            if i and buf:
                status.markdown(md_safe("".join(buf)))
            buf.clear()
            box.empty()

        def on_text(t: str) -> None:
            buf.append(t)
            box.markdown(md_safe("".join(buf)) + " ▌")

        def on_tool(name: str, args: dict) -> None:
            arg = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", []))
            status.write(f"{TOOL_LABELS.get(name, name)}" + (f" · {arg}" if arg else ""))

        history = [{"role": m["role"], "content": m["content"]} for m in hist][-12:]
        try:
            turn = copilot.ask(q, history, on_text=on_text, on_step=on_step, on_tool=on_tool)
        except ai.BudgetExceeded as exc:
            status.update(label="Stopped", state="error")
            st.warning(str(exc), icon=":material/savings:")
            st.stop()
        except ai.Refused as exc:
            status.update(label="Declined", state="error")
            box.empty()
            st.warning(f"The model declined to answer this ({exc}). Try rephrasing.",
                       icon=":material/block:")
            st.stop()
        except Exception as exc:  # noqa: BLE001 - surface provider errors plainly
            status.update(label="Failed", state="error")
            st.error(f"The AI provider returned an error: {str(exc)[:300]}",
                     icon=":material/error:")
            st.stop()
        status.update(label=f"Researched with {len(turn.tools_used)} lookup"
                            f"{'' if len(turn.tools_used) == 1 else 's'} · "
                            f"{usd(turn.cost, 3)}", state="complete")
        box.markdown(md_safe(turn.text))
        _sources(turn.sources)
    hist += [{"role": "user", "content": q},
             {"role": "assistant", "content": turn.text, "sources": turn.sources}]
    st.session_state["copilot"] = hist
