import pytest

import database.db as db_module

# NOTE: never import `app` at module level in tests. Importing app.py runs
# init_db()/seed_db() at import time, which must hit the temp DB, not the
# real expense_tracker.db. The `client` fixture imports it lazily instead.


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Point every get_db() call at a fresh, seeded temp database."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(path))
    db_module.init_db()
    db_module.seed_db()
    return path


@pytest.fixture
def client(db_path):
    from app import app

    app.config["TESTING"] = True
    yield app.test_client()
