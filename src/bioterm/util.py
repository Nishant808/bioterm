"""Tiny shared helpers."""
from __future__ import annotations

from typing import Any


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
