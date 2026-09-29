import inspect
import re
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

import database.db as db_module

SUCCESS_MSG = "Account created — please sign in."
NAME_ERROR = "Please enter your name."
EMAIL_ERROR = "Please enter a valid email address."
PASSWORD_ERROR = "Password must be at least 8 characters."
DUPLICATE_ERROR = "An account with that email already exists."

VALID = {"name": "Test User", "email": "test@example.com", "password": "password123"}

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _form(**overrides):
    return {**VALID, **overrides}


def _count(email):
    conn = db_module.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?", (email,)
        ).fetchone()[0]
    finally:
        conn.close()


def _user(email):
    conn = db_module.get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()


def _text(response):
    return response.get_data(as_text=True)


# ------------------------------------------------------------------ #
# GET /register                                                       #
# ------------------------------------------------------------------ #

def test_get_register_renders_form(client):
    response = client.get("/register")
    body = _text(response)

    assert response.status_code == 200
    for label in ("Full name", "Email address", "Password"):
        assert label in body
    for field in ('name="name"', 'name="email"', 'name="password"'):
        assert field in body


def test_get_register_has_minlength(client):
    assert 'minlength="8"' in _text(client.get("/register"))


# ------------------------------------------------------------------ #
# Successful registration                                             #
# ------------------------------------------------------------------ #

def test_register_success_redirects_to_login(client):
    response = client.post("/register", data=_form())

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_register_success_flashes_message_on_login(client):
    response = client.post("/register", data=_form(), follow_redirects=True)
    body = _text(response)

    assert response.request.path == "/login"
    assert SUCCESS_MSG in body
    assert 'class="auth-success"' in body


def test_flash_shown_only_once(client):
    client.post("/register", data=_form(), follow_redirects=True)

    assert SUCCESS_MSG not in _text(client.get("/login"))


def test_register_creates_exactly_one_row(client):
    client.post("/register", data=_form())

    assert _count("test@example.com") == 1


def test_password_is_hashed(client):
    client.post("/register", data=_form())
    password_hash = _user("test@example.com")["password_hash"]

    assert password_hash != "password123"
    assert password_hash.startswith(("scrypt:", "pbkdf2:"))
    assert check_password_hash(password_hash, "password123")


def test_email_stored_lowercased_and_trimmed(client):
    client.post("/register", data=_form(email="  Foo@Example.COM "))

    assert _count("foo@example.com") == 1


def test_name_stored_trimmed(client):
    client.post("/register", data=_form(name="  Test User  "))

    assert _user("test@example.com")["name"] == "Test User"


def test_password_not_stripped(client):
    response = client.post("/register", data=_form(password=" pass12 "))

    assert response.status_code == 302
    assert check_password_hash(
        _user("test@example.com")["password_hash"], " pass12 "
    )


# ------------------------------------------------------------------ #
# Duplicate emails                                                    #
# ------------------------------------------------------------------ #

def test_duplicate_email_rejected(client):
    client.post("/register", data=_form())
    response = client.post("/register", data=_form())

    assert response.status_code == 400
    assert DUPLICATE_ERROR in _text(response)
    assert _count("test@example.com") == 1


def test_duplicate_email_case_and_whitespace(client):
    client.post("/register", data=_form())
    response = client.post("/register", data=_form(email="TEST@Example.com "))

    assert response.status_code == 400
    assert DUPLICATE_ERROR in _text(response)
    assert _count("test@example.com") == 1


def test_seeded_demo_user_is_duplicate(client):
    response = client.post("/register", data=_form(email="demo@spendly.com"))

    assert response.status_code == 400
    assert DUPLICATE_ERROR in _text(response)
    assert _count("demo@spendly.com") == 1


# ------------------------------------------------------------------ #
# Validation errors                                                   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("name", ["", "   "])
def test_blank_name_rejected(client, name):
    response = client.post("/register", data=_form(name=name))

    assert response.status_code == 400
    assert NAME_ERROR in _text(response)
    assert _count("test@example.com") == 0


@pytest.mark.parametrize(
    "email", ["not-an-email", "a@b@c.com", "@example.com", "user@localhost", ""]
)
def test_invalid_email_rejected(client, email):
    response = client.post("/register", data=_form(email=email))

    assert response.status_code == 400
    assert EMAIL_ERROR in _text(response)
    assert _count(email.strip().lower()) == 0


def test_short_password_rejected(client):
    response = client.post("/register", data=_form(password="abc1234"))

    assert response.status_code == 400
    assert PASSWORD_ERROR in _text(response)
    assert _count("test@example.com") == 0


def test_validation_order(client):
    all_bad = client.post(
        "/register", data={"name": "", "email": "bad", "password": "short"}
    )
    assert NAME_ERROR in _text(all_bad)

    email_and_password_bad = client.post(
        "/register", data=_form(email="bad", password="short")
    )
    body = _text(email_and_password_bad)
    assert EMAIL_ERROR in body
    assert PASSWORD_ERROR not in body


def test_error_repopulates_name_and_email_not_password(client):
    response = client.post("/register", data=_form(password="abc1234"))
    body = _text(response)

    assert 'value="Test User"' in body
    assert 'value="test@example.com"' in body
    password_input = re.search(r'<input[^>]*name="password"[^>]*>', body).group(0)
    assert "value=" not in password_input
    assert "abc1234" not in body


def test_repopulated_values_are_escaped(client):
    response = client.post("/register", data=_form(name="<b>x</b>", email="bad"))
    body = _text(response)

    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "<b>x</b>" not in body


# ------------------------------------------------------------------ #
# Project rules                                                       #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("template", ["register.html", "login.html"])
def test_templates_have_no_hardcoded_actions(template):
    source = (TEMPLATES_DIR / template).read_text(encoding="utf-8")

    assert re.search(r'action="/', source) is None


def test_routes_contain_no_db_access(client):
    sql = re.compile(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM)\b")

    for endpoint, view in client.application.view_functions.items():
        if endpoint == "static":
            continue
        source = inspect.getsource(view)
        assert "get_db(" not in source, endpoint
        assert sql.search(source) is None, endpoint


def test_uses_temp_database(db_path, tmp_path):
    assert Path(db_module.DB_PATH) == db_path
    assert tmp_path in db_path.parents
    assert db_path.name != "expense_tracker.db"


# ------------------------------------------------------------------ #
# create_user()                                                       #
# ------------------------------------------------------------------ #

def test_create_user_returns_id_then_none(db_path):
    user_id = db_module.create_user("Unit User", "unit@example.com", "password123")

    assert isinstance(user_id, int)
    assert db_module.create_user("Other", "unit@example.com", "password456") is None
    assert _count("unit@example.com") == 1
