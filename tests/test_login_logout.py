import html
import inspect
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

import database.db as db_module

INVALID_MSG = "Invalid email or password."
LOGOUT_MSG = "You've been signed out."
PASSWORD_ERROR = "Password must be at least 8 characters."

DEMO = {"email": "demo@spendly.com", "password": "demo123"}


def _login(client, **overrides):
    return client.post("/login", data={**DEMO, **overrides})


def _raw(response):
    return response.get_data(as_text=True)


def _text(response):
    return html.unescape(_raw(response))


def _path(response):
    return urlparse(response.headers["Location"]).path


def _user(email):
    conn = db_module.get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# GET /login                                                          #
# ------------------------------------------------------------------ #

def test_get_login_renders_form(client):
    response = client.get("/login")
    body = _raw(response)

    assert response.status_code == 200
    assert "Email address" in body
    assert "Password" in body
    assert 'name="email"' in body
    assert 'name="password"' in body


def test_get_login_when_signed_in_redirects(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_name"] = "Demo User"

    response = client.get("/login")

    assert response.status_code == 302
    assert _path(response) == "/"


# ------------------------------------------------------------------ #
# Successful sign-in                                                  #
# ------------------------------------------------------------------ #

def test_demo_login_redirects_to_landing(client):
    response = _login(client)

    assert response.status_code == 302
    assert _path(response) == "/"


def test_navbar_after_login(client):
    _login(client)
    body = _text(client.get("/"))

    assert "Demo User" in body
    assert "Sign out" in body
    assert 'class="nav-user"' in body
    assert "Sign in" not in body
    assert "Get started" not in body


def test_login_email_case_and_whitespace(client):
    response = _login(client, email="DEMO@Spendly.com ")

    assert response.status_code == 302
    assert _path(response) == "/"


def test_registered_user_can_login(client):
    client.post(
        "/register",
        data={"name": "Test User", "email": "test@example.com", "password": "password123"},
    )
    response = _login(client, email="test@example.com", password="password123")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_name"] == "Test User"


def test_session_contents_after_login(client):
    _login(client)
    demo = _user("demo@spendly.com")

    with client.session_transaction() as sess:
        assert set(sess.keys()) == {"user_id", "user_name"}
        assert sess["user_id"] == demo["id"]
        assert sess["user_name"] == "Demo User"
        for value in sess.values():
            assert value not in ("demo123", "demo@spendly.com", demo["password_hash"])


def test_login_clears_stale_session(client):
    with client.session_transaction() as sess:
        sess["stale"] = "x"

    _login(client)

    with client.session_transaction() as sess:
        assert "stale" not in sess


# ------------------------------------------------------------------ #
# Failed sign-in                                                      #
# ------------------------------------------------------------------ #

def test_wrong_password(client):
    response = _login(client, password="wrongpass")

    assert response.status_code == 401
    assert INVALID_MSG in _text(response)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_unknown_email_same_message(client):
    wrong_password = _login(client, password="wrongpass")
    unknown_email = _login(client, email="nobody@example.com", password="wrongpass")

    assert unknown_email.status_code == 401
    assert INVALID_MSG in _text(unknown_email)
    assert (
        _raw(unknown_email).replace("nobody@example.com", "demo@spendly.com")
        == _raw(wrong_password)
    )


@pytest.mark.parametrize(
    "email,password",
    [("", "demo123"), ("demo@spendly.com", ""), ("   ", "demo123"), ("", "")],
)
def test_empty_fields_rejected(client, email, password):
    response = _login(client, email=email, password=password)

    assert response.status_code == 401
    assert INVALID_MSG in _text(response)


def test_failed_login_repopulates_email_not_password(client):
    response = _login(client, password="wrongpass")
    body = _raw(response)

    assert 'value="demo@spendly.com"' in body
    password_input = re.search(r'<input[^>]*name="password"[^>]*>', body).group(0)
    assert "value=" not in password_input
    assert "wrongpass" not in body


def test_repopulated_email_is_escaped(client):
    response = _login(client, email="<b>x</b>@a.com")
    body = _raw(response)

    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "<b>x</b>" not in body


def test_short_password_not_rejected_by_length_rule(client):
    assert _login(client).status_code == 302

    client.get("/logout")
    response = _login(client, password="abc")

    assert response.status_code == 401
    assert INVALID_MSG in _text(response)
    assert PASSWORD_ERROR not in _text(response)


# ------------------------------------------------------------------ #
# GET /logout                                                         #
# ------------------------------------------------------------------ #

def test_logout_redirects_to_login(client):
    _login(client)
    response = client.get("/logout")

    assert response.status_code == 302
    assert _path(response) == "/login"


def test_logout_flashes_success(client):
    _login(client)
    response = client.get("/logout", follow_redirects=True)

    assert response.request.path == "/login"
    assert LOGOUT_MSG in _text(response)
    assert 'class="auth-success"' in _raw(response)


def test_logout_clears_session_and_navbar(client):
    _login(client)
    client.get("/logout")

    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "user_name" not in sess

    body = _text(client.get("/"))
    assert "Sign in" in body
    assert "Get started" in body
    assert "Sign out" not in body
    assert "Demo User" not in body


def test_logout_when_signed_out(client):
    response = client.get("/logout")

    assert response.status_code == 302
    assert _path(response) == "/login"

    followed = client.get("/login")
    assert followed.status_code == 200
    assert LOGOUT_MSG in _text(followed)


def test_logout_not_placeholder(client):
    response = client.get("/logout", follow_redirects=True)

    assert "coming in Step 3" not in _text(response)


def test_logout_flash_shown_once(client):
    _login(client)
    client.get("/logout", follow_redirects=True)
    response = client.get("/login")

    assert LOGOUT_MSG not in _text(response)


# ------------------------------------------------------------------ #
# Project rules                                                       #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("endpoint", ["login", "logout"])
def test_login_logout_views_have_no_db_logic(client, endpoint):
    sql = re.compile(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM)\b")
    source = inspect.getsource(client.application.view_functions[endpoint])

    assert "get_db(" not in source
    assert "check_password_hash" not in source
    assert sql.search(source) is None


def test_uses_temp_database(db_path, tmp_path):
    assert Path(db_module.DB_PATH) == db_path
    assert tmp_path in db_path.parents
    assert db_path.name != "expense_tracker.db"


# ------------------------------------------------------------------ #
# authenticate_user()                                                 #
# ------------------------------------------------------------------ #

def test_authenticate_user_success(db_path):
    user = db_module.authenticate_user("demo@spendly.com", "demo123")

    assert user is not None
    assert user["name"] == "Demo User"
    assert user["email"] == "demo@spendly.com"


def test_authenticate_user_wrong_password_and_unknown_email(db_path):
    assert db_module.authenticate_user("demo@spendly.com", "wrongpass") is None
    assert db_module.authenticate_user("nobody@example.com", "demo123") is None
