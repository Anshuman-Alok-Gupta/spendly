import itertools

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


@pytest.fixture
def make_user(db_path):
    """Create a user in the temp DB and return its id."""
    counter = itertools.count(1)

    def _make(name="Test User", email=None, password="password123"):
        email = email or f"user{next(counter)}@example.com"
        return db_module.create_user(name, email, password)

    return _make


@pytest.fixture
def add_expense(db_path):
    """Insert an expense in the temp DB and return its id."""
    def _add(user_id, amount, category="Food", date="2026-09-01",
             description="Test expense"):
        conn = db_module.get_db()
        try:
            cursor = conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, category, date, description),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    return _add
