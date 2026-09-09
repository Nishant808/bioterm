import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Point every test at a throwaway SQLite file; don't seed from the real YAML."""
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    import bioterm.db as db_mod
    import bioterm.store as store_mod

    db_mod._ENGINE = None
    monkeypatch.setattr(store_mod, "seed_from_yaml", lambda *a, **k: {})
    yield
    db_mod._ENGINE = None
