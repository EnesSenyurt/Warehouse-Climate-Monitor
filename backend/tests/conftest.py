"""
Shared fixtures.

Every test gets its own throwaway SQLite file. `db.DB_PATH` is a module
global read at call time, so monkeypatching the attribute is enough to
redirect all queries - no dependency injection needed.
"""

import pytest

from app import db as db_module


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh, initialised database, isolated per test."""
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    return db_module
