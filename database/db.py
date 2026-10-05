import os
import sqlite3
from datetime import date

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "expense_tracker.db")

CATEGORIES = (
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount      REAL NOT NULL,
    category    TEXT NOT NULL,
    date        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

# (amount, category, day of current month, description)
SEED_EXPENSES = (
    (12.50, "Food", 1, "Lunch at cafe"),
    (45.00, "Transport", 3, "Metro card top-up"),
    (120.00, "Bills", 5, "Electricity bill"),
    (30.00, "Health", 8, "Pharmacy"),
    (15.99, "Entertainment", 12, "Movie tickets"),
    (60.25, "Shopping", 15, "New shoes"),
    (8.75, "Other", 18, "Gift wrapping"),
    (38.40, "Food", 22, "Weekly groceries"),
)


def get_db():
    """Return a SQLite connection with dict-like rows and FK enforcement on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to call repeatedly."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _seed_date(day, today=None):
    """Return a YYYY-MM-DD date in the current month, never after today."""
    today = today or date.today()
    return date(today.year, today.month, min(day, today.day)).isoformat()


def seed_db():
    """Insert a demo user and sample expenses, only if no users exist yet."""
    conn = get_db()
    try:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count > 0:
            return

        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
        )
        user_id = cursor.lastrowid

        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (user_id, amount, category, _seed_date(day), description)
                for amount, category, day, description in SEED_EXPENSES
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_user(name, email, password):
    """Insert a new user with a hashed password.

    Returns the new user's id, or None if the email is already registered.
    """
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()


def create_expense(user_id, amount, category, date, description):
    """Insert an expense for a user and return its id.

    Values are expected to be validated by the caller; `description` may be None.
    """
    conn = get_db()
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


def update_expense(expense_id, user_id, amount, category, date, description):
    """Update an expense owned by `user_id`; return True if a row matched.

    Values are expected to be validated by the caller; `description` may be None.
    """
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, "
            "description = ? WHERE id = ? AND user_id = ?",
            (amount, category, date, description, expense_id, user_id),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def delete_expense(expense_id, user_id):
    """Delete an expense owned by `user_id`; return True if a row was removed."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def authenticate_user(email, password):
    """Return the user row if the email and password match, otherwise None.

    `email` is expected to be already trimmed and lowercased by the caller.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None or not check_password_hash(row["password_hash"], password):
            return None
        return row
    finally:
        conn.close()
