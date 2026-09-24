"""Tiny shared helpers."""
from __future__ import annotations

import html
import re
from typing import Any

# A tag (<a href=...>, </a>, <br/>, <!-- -->) or one cut off at the end of the
# string by truncation (<a href="https://...). Tag-shaped only: feedparser hands
# back decoded text, so "p<0.001" or "viral load <LLOQ" in a headline is prose.
_TAG_RE = re.compile(r"<[A-Za-z/!?][^<>]*>|<[A-Za-z][\w-]*\s+[\w:-]+=[^<>]*$")


def strip_markup(value: Any) -> str:
    """Plain text from a feed field that may carry HTML.

    Some publishers put markup inside RSS <title>s (FierceBiotech wraps the
    headline in its own <a href=...>). Left in, it leaks into the dashboard and
    breaks Telegram's HTML parse mode - so tags go, entities are decoded, and
    whitespace is collapsed."""
    text = _TAG_RE.sub(" ", as_text(value))
    return " ".join(html.unescape(text).split())


def as_text(value: Any) -> str:
    """Coerce anything (incl. float NaN / None / pandas NA) to a plain string."""
    if value is None:
        return ""
    try:
        # NaN != NaN
        if value != value:  # noqa: PLR0124
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


# Trailing corporate-form / security-class words that differ between how a company
# is named in an ETF sheet, a 13F filing and SEC's own index ("Cytokinetics,
# Incorporated" / "CYTOKINETICS INC" / "Cytokinetics Inc - Sponsored ADR").
_CORP_TAIL = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED",
    "PLC", "SA", "NV", "SE", "AG", "AB", "ASA", "OYJ", "LLC", "LP", "HOLDINGS",
    "HOLDING", "GROUP", "SPONSORED", "ADR", "ADS", "ORD", "SHS", "COM", "CL", "CLASS",
    "A", "B", "NEW", "DEL", "THE",
}
# Industry words: dropped only for the looser "core" key
_INDUSTRY = {
    "THERAPEUTICS", "PHARMACEUTICALS", "PHARMACEUTICAL", "PHARMA", "BIOSCIENCES",
    "BIOSCIENCE", "BIOTHERAPEUTICS", "MEDICINES", "BIOLOGICS", "BIOPHARMA",
    "BIOPHARMACEUTICALS", "SCIENCES", "GENETICS", "BIOTECHNOLOGY", "BIOTECH", "BIO",
    "LABORATORIES", "LABS", "ONCOLOGY", "THERAPEUTIC",
}


def company_key(name: Any) -> str:
    """Canonical company name for cross-source matching: upper case, punctuation
    and trailing corporate-form words removed ("Alkermes plc" -> "ALKERMES")."""
    s = as_text(name).upper().replace("&", " AND ")
    s = re.sub(r"\(.*?\)", " ", s)
    toks = [t for t in re.sub(r"[^A-Z0-9 ]", " ", s).split() if t]
    while toks and toks[0] == "THE":
        toks.pop(0)
    while toks and toks[-1] in _CORP_TAIL:
        toks.pop()
    return " ".join(toks)


def company_core(name: Any) -> str:
    """``company_key`` minus trailing industry words ("INSMED", "VERTEX") - looser,
    so only trusted when it is unique across the universe."""
    toks = company_key(name).split()
    while len(toks) > 1 and toks[-1] in _INDUSTRY:
        toks.pop()
    return " ".join(toks)
