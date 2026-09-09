"""Configuration loading: YAML files under config/ + environment overrides.

Everything is re-read on each call to ``load_settings()`` so a running scheduler or
Streamlit session picks up edits without a restart.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Repo root = two levels up from this file (src/bioterm/config.py -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"


def _read_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


def _load_dotenv() -> None:
    """Minimal .env loader (avoids a python-dotenv dependency)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


@dataclass
class Settings:
    raw: dict[str, Any]
    watchlist: list[dict[str, Any]] = field(default_factory=list)
    seed: list[dict[str, Any]] = field(default_factory=list)
    feeds: list[dict[str, Any]] = field(default_factory=list)
    manual_catalysts: list[dict[str, Any]] = field(default_factory=list)

    # --- env-derived ---
    @property
    def database_url(self) -> str:
        url = os.environ.get("DATABASE_URL", "sqlite:///data/bioterm.db")
        # make relative sqlite paths repo-root relative, not cwd relative
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            if not os.path.isabs(rel):
                url = f"sqlite:///{(REPO_ROOT / rel).as_posix()}"
        return url

    @property
    def sec_user_agent(self) -> str:
        return os.environ.get(
            "BIOTERM_SEC_USER_AGENT", "BioTerm/0.1 (contact-me@example.com)"
        )

    @property
    def http_timeout(self) -> int:
        return int(os.environ.get("BIOTERM_HTTP_TIMEOUT", "20"))

    @property
    def universe_limit(self) -> int:
        return int(os.environ.get("BIOTERM_UNIVERSE_LIMIT", "0"))

    # --- convenience accessors into raw settings.yml ---
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def horizon_months(self) -> int:
        return int(self.get("horizon_months", default=6))

    @property
    def watchlist_tickers(self) -> list[str]:
        return [str(w["ticker"]).upper() for w in self.watchlist if w.get("ticker")]

    def conviction_for(self, ticker: str) -> int | None:
        for w in self.watchlist:
            if str(w.get("ticker", "")).upper() == ticker.upper():
                return int(w.get("conviction", 3))
        return None


def load_settings() -> Settings:
    _load_dotenv()
    raw = _read_yaml("settings.yml")
    watchlist = _read_yaml("watchlist.yml").get("watchlist", []) or []
    seed = _read_yaml("universe_seed.yml").get("seed", []) or []
    feeds = _read_yaml("sources.yml").get("feeds", []) or []
    manual = _read_yaml("catalysts_manual.yml").get("catalysts", []) or []
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)
    return Settings(
        raw=raw,
        watchlist=watchlist,
        seed=seed,
        feeds=feeds,
        manual_catalysts=manual,
    )


@lru_cache(maxsize=1)
def settings_cached() -> Settings:
    """Process-lifetime cached settings (use load_settings() when you need freshness)."""
    return load_settings()
