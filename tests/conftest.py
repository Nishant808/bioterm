import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Point every test at a throwaway SQLite file."""
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    # reset the memoised engine + settings
    import bioterm.db as db_mod

    db_mod._ENGINE = None
    yield
    db_mod._ENGINE = None
