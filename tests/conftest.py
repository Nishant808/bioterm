import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Point every test at a throwaway SQLite file; don't seed from the real YAML."""
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    # the dashboard's live Yahoo prices -> stored-close fallback (no network in tests)
    monkeypatch.setenv("BIOTERM_LIVE_PRICES", "0")
    import bioterm.db as db_mod
    import bioterm.store as store_mod

    import bioterm.vault as vault_mod

    db_mod._ENGINE = None
    vault_mod.reset_key_cache()
    for k in ("BIOTERM_ADMIN_PASSWORD", "BIOTERM_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(store_mod, "seed_from_yaml", lambda *a, **k: {})
    yield
    db_mod._ENGINE = None
    vault_mod.reset_key_cache()
