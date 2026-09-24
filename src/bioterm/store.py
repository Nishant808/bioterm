"""DB-backed user state: watchlist, manual catalysts, per-ticker notes, app meta.

The YAML files under ``config/`` are *seeds*. On first run each table is populated
from its YAML file; after that the database is authoritative. This is what lets the
Streamlit Cloud dashboard persist edits (its filesystem is ephemeral, and the
GitHub Actions ingest runner is a separate checkout).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from .config import load_settings
from .util import as_text
from .db import (app_meta, bulk_upsert, get_engine, manual_catalysts, molecule_links,
                 molecule_status, molecule_trials, molecules, notes, read_sql, watchlist)

log = logging.getLogger("bioterm.store")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mk_cat_id(ticker: str, ctype: str, d: str, title: str) -> str:
    return hashlib.sha1(f"{ticker}|{ctype}|{d}|{title[:60]}".encode()).hexdigest()[:48]


# ------------------------------------------------------------------ watchlist
def get_watchlist() -> list[dict[str, Any]]:
    """Return the watchlist as a list of dicts (DB first, YAML fallback)."""
    try:
        df = read_sql("SELECT * FROM watchlist ORDER BY conviction DESC, ticker")
    except Exception:  # table missing / DB down
        df = pd.DataFrame()
    if df.empty:
        return [dict(w) for w in load_settings().watchlist]
    out = []
    for _, r in df.iterrows():
        mols = r.get("molecules")
        try:
            mols = json.loads(mols) if mols else []
        except (TypeError, ValueError):
            mols = []
        out.append({
            "ticker": r["ticker"],
            "conviction": int(r["conviction"]) if pd.notna(r["conviction"]) else 3,
            "thesis": r.get("thesis") or "",
            "molecules": mols,
        })
    return out


def save_watchlist(entries: list[dict[str, Any]]) -> int:
    """Replace the whole watchlist. ``entries`` = [{ticker, conviction, thesis, molecules}]."""
    engine = get_engine()
    now = _now()
    rows = []
    for e in entries:
        tk = str(e.get("ticker", "")).strip().upper()
        if not tk:
            continue
        mols = e.get("molecules") or []
        if isinstance(mols, str):
            mols = [m.strip() for m in mols.split(",") if m.strip()]
        rows.append({
            "ticker": tk,
            "conviction": int(e.get("conviction", 3) or 3),
            "thesis": (e.get("thesis") or "").strip() or None,
            "molecules": json.dumps(mols) if mols else None,
            "added_at": now,
            "updated_at": now,
        })
    keep = {r["ticker"] for r in rows}
    with engine.begin() as conn:
        existing = read_sql("SELECT ticker FROM watchlist")
        drop = [t for t in existing["ticker"].tolist() if t not in keep] if not existing.empty else []
        if drop:
            conn.execute(watchlist.delete().where(watchlist.c.ticker.in_(drop)))
    bulk_upsert(watchlist, rows, update_only=["conviction", "thesis", "molecules", "updated_at"])
    return len(rows)


def add_to_watchlist(ticker: str, conviction: int = 3, thesis: str = "") -> None:
    wl = {w["ticker"].upper(): w for w in get_watchlist()}
    ticker = ticker.upper()
    if ticker in wl:
        wl[ticker]["conviction"] = conviction
        if thesis:
            wl[ticker]["thesis"] = thesis
    else:
        wl[ticker] = {"ticker": ticker, "conviction": conviction,
                      "thesis": thesis, "molecules": []}
    save_watchlist(list(wl.values()))


def remove_from_watchlist(ticker: str) -> None:
    wl = [w for w in get_watchlist() if w["ticker"].upper() != ticker.upper()]
    save_watchlist(wl)


def watchlist_conviction(ticker: str) -> int | None:
    for w in get_watchlist():
        if w["ticker"].upper() == ticker.upper():
            return int(w.get("conviction", 3))
    return None


# ------------------------------------------------------------------ manual catalysts
def get_manual_catalysts() -> list[dict[str, Any]]:
    try:
        df = read_sql("SELECT * FROM manual_catalysts ORDER BY date")
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        return [dict(c) for c in load_settings().manual_catalysts]
    return df.to_dict("records")


def add_manual_catalyst(ticker: str, ctype: str, d: date | str, title: str,
                        confidence: str = "medium", url: str = "") -> str:
    d = str(d)
    cid = _mk_cat_id(ticker.upper(), ctype, d, title)
    bulk_upsert(manual_catalysts, [{
        "id": cid, "ticker": ticker.upper(), "type": ctype,
        "date": pd.to_datetime(d, errors="coerce").date(),
        "title": title.strip(), "confidence": confidence,
        "url": url.strip(), "created_at": _now(),
    }])
    return cid


def delete_manual_catalyst(cid: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(manual_catalysts.delete().where(manual_catalysts.c.id == cid))


# ------------------------------------------------------------------ notes
def get_note(ticker: str) -> str:
    try:
        df = read_sql("SELECT body FROM notes WHERE ticker = :t", {"t": ticker.upper()})
    except Exception:
        return ""
    return "" if df.empty else (df.iloc[0]["body"] or "")


def set_note(ticker: str, body: str) -> None:
    bulk_upsert(notes, [{"ticker": ticker.upper(), "body": body,
                         "updated_at": _now()}])


def all_notes() -> dict[str, str]:
    try:
        df = read_sql("SELECT ticker, body FROM notes")
    except Exception:
        return {}
    return dict(zip(df["ticker"], df["body"])) if not df.empty else {}


# ------------------------------------------------------------------ app meta
def get_meta(key: str, default: Any = None) -> Any:
    try:
        df = read_sql("SELECT value FROM app_meta WHERE key = :k", {"k": key})
    except Exception:
        return default
    if df.empty:
        return default
    try:
        return json.loads(df.iloc[0]["value"])
    except (TypeError, ValueError):
        return default


def set_meta(key: str, value: Any) -> None:
    bulk_upsert(app_meta, [{"key": key, "value": json.dumps(value, default=str),
                            "updated_at": _now()}])


# ------------------------------------------------------------------ molecules
# A drug-code-looking token ("VX-548", "V940", "SRP-9003", "mRNA-4157") or an
# INN stem ("delandistrogene", "suzetrigine", "...mab") inside parentheses is
# another name for the asset; anything else in parentheses is the indication.
_CODE_RE = re.compile(r"^[A-Za-z]{1,6}-?\d{2,}[A-Za-z0-9-]*$")
_INN_RE = re.compile(r"(mab|nib|gene|cel|ran|tide|stat|gine|parin|vir|sen|rsen|siran|"
                     r"cept|lukast|zumab|ximab|tinib|ciclib|dustat|platin|trogene)$", re.I)


def _looks_like_name(token: str) -> bool:
    t = token.strip()
    return bool(_CODE_RE.match(t) or (" " not in t and _INN_RE.search(t)))


def molecule_id(ticker: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{ticker}-{name}".lower()).strip("-")
    return slug[:48]


def parse_molecule_label(label: str, ticker: str) -> dict[str, Any]:
    """Watchlist free text -> structured molecule.

    "mRNA-4157/V940 (melanoma)"  -> name mRNA-4157, aliases [V940], indication melanoma
    "suzetrigine (VX-548)"       -> name suzetrigine, aliases [VX-548]
    """
    label = " ".join(str(label or "").split())
    paren = re.findall(r"\(([^)]*)\)", label)
    head = re.sub(r"\([^)]*\)", " ", label).strip()
    names = [n.strip() for n in re.split(r"\s*/\s*", head) if n.strip()]
    aliases, indication = names[1:], []
    for p in paren:
        parts = [x.strip() for x in p.split(",") if x.strip()]
        if parts and all(_looks_like_name(x) for x in parts):
            aliases.extend(parts)
        else:
            indication.append(p.strip())
    name = names[0] if names else label
    return {"id": molecule_id(ticker, name), "ticker": ticker.upper(), "name": name,
            "aliases": list(dict.fromkeys(a for a in aliases if a.lower() != name.lower())),
            "indication": "; ".join(indication), "nct_ids": [], "notes": ""}


def _jlist(v) -> list:
    if isinstance(v, list):
        return v
    try:
        out = json.loads(v) if v else []
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


def get_molecules(ticker: str | None = None) -> list[dict[str, Any]]:
    try:
        if ticker:
            df = read_sql("SELECT * FROM molecules WHERE ticker = :t ORDER BY name",
                          {"t": ticker.upper()})
        else:
            df = read_sql("SELECT * FROM molecules ORDER BY ticker, name")
    except Exception:  # noqa: BLE001
        return []
    out = []
    for _, r in df.iterrows():
        d = r.to_dict()
        d["aliases"] = _jlist(d.get("aliases"))
        d["nct_ids"] = _jlist(d.get("nct_ids"))
        out.append(d)
    return out


def save_molecule(m: dict[str, Any]) -> str:
    ticker = as_text(m.get("ticker")).upper()
    name = as_text(m.get("name"))
    if not ticker or not name:
        raise ValueError("a molecule needs a ticker and a name")
    mid = m.get("id") or molecule_id(ticker, name)

    def _as_list(v) -> list[str]:
        if isinstance(v, str):
            v = re.split(r"[,;\n]", v)
        return [str(x).strip() for x in (v or []) if str(x).strip()]
    ncts = [x.upper() for x in _as_list(m.get("nct_ids"))
            if re.fullmatch(r"NCT\d{8}", x.strip().upper())]
    now = _now()
    bulk_upsert(molecules, [{
        "id": mid, "ticker": ticker[:16], "name": name[:120],
        "aliases": json.dumps(_as_list(m.get("aliases"))),
        "indication": as_text(m.get("indication"))[:160] or None,
        "nct_ids": json.dumps(ncts), "notes": as_text(m.get("notes")) or None,
        "created_at": now, "updated_at": now}],
        update_only=["ticker", "name", "aliases", "indication", "nct_ids", "notes",
                     "updated_at"])
    return mid


def delete_molecule(mid: str) -> None:
    with get_engine().begin() as conn:
        for t, col in ((molecules, molecules.c.id), (molecule_trials, molecule_trials.c.molecule_id),
                       (molecule_links, molecule_links.c.molecule_id),
                       (molecule_status, molecule_status.c.molecule_id)):
            conn.execute(t.delete().where(col == mid))


def sync_molecules_from_watchlist() -> int:
    """Add a tracked molecule for every watchlist entry's free-text molecule that
    isn't tracked yet. Never overwrites a molecule the user has edited."""
    have = {m["id"] for m in get_molecules()}
    added = 0
    for w in get_watchlist():
        for label in w.get("molecules") or []:
            m = parse_molecule_label(label, w["ticker"])
            if m["id"] not in have:
                save_molecule(m)
                have.add(m["id"])
                added += 1
    return added


# ------------------------------------------------------------------ seeding
def seed_from_yaml(force: bool = False) -> dict:
    """Populate the user-state tables from config/*.yml if they are empty."""
    cfg = load_settings()
    out = {}

    wl_existing = read_sql("SELECT COUNT(*) c FROM watchlist").iloc[0]["c"]
    if force or wl_existing == 0:
        entries = [{"ticker": w["ticker"], "conviction": w.get("conviction", 3),
                    "thesis": w.get("thesis", ""), "molecules": w.get("molecules", [])}
                   for w in cfg.watchlist]
        out["watchlist_seeded"] = save_watchlist(entries) if entries else 0

    mc_existing = read_sql("SELECT COUNT(*) c FROM manual_catalysts").iloc[0]["c"]
    if (force or mc_existing == 0) and cfg.manual_catalysts:
        n = 0
        for c in cfg.manual_catalysts:
            if c.get("ticker") and c.get("date"):
                add_manual_catalyst(c["ticker"], c.get("type", "other"), c["date"],
                                    c.get("title", ""), c.get("confidence", "medium"),
                                    c.get("url", ""))
                n += 1
        out["manual_catalysts_seeded"] = n

    return out
