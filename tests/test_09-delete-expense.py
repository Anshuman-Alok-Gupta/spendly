"""Tests for Step 09: delete expense (spec-driven)."""
import html as html_lib
import re
import sqlite3
from pathlib import Path

import pytest

import database.db as db_module

ROOT = Path(__file__).resolve().parents[1]
MISSING_ID = 999999
DATE = "2026-09-01"


# ------------------------------------------------------------------ helpers

def _url(expense_id):
    return f"/expenses/{expense_id}/delete"


def _login(client, email, password="password123"):
    resp = client.post("/login", data={"email": email, "password": password})
    assert resp.status_code == 302, "login should redirect on success"


def _body(resp):
    return html_lib.unescape(resp.get_data(as_text=True))


def _location_path(resp):
    return re.sub(r"^https?://[^/]+", "", resp.headers["Location"]).split("?")[0]


def _row(db_path, expense_id):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    finally:
        conn.close()


def _all_expenses(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses ORDER BY id").fetchall()
    finally:
        conn.close()


def _all_users(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, name, email, password_hash FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _set_description_null(db_path, expense_id):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE expenses SET description = NULL WHERE id = ?",
                     (expense_id,))
        conn.commit()
    finally:
        conn.close()


def _delete_user(user_id):
    conn = db_module.get_db()
    try:
        conn.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def _stat(body, label):
    m = re.search(
        rf"{label}</span>.*?<dd class=\"profile-stat-value\">(.*?)</dd>",
        body, re.S)
    assert m, f"stat {label!r} expected on profile"
    return m.group(1).strip()


@pytest.fixture
def user(client, make_user):
    """Fresh user, signed in via POST /login."""
    uid = make_user(name="Deleter", email="deleter@example.com")
    _login(client, "deleter@example.com")
    return uid


@pytest.fixture
def expense(user, add_expense):
    """An expense owned by the signed-in user."""
    return add_expense(user, 12.5, category="Food", date=DATE,
                       description="Lunch special")


@pytest.fixture
def other_expense(make_user, add_expense):
    """An expense owned by a different user."""
    other = make_user(name="Other", email="other@example.com")
    return add_expense(other, 77.0, category="Travel", date=DATE,
                       description="Not yours")


# ------------------------------------------------------- db helper (unit)

class TestDeleteExpenseHelper:
    def test_owner_deletes_returns_true_and_row_removed(
            self, db_path, make_user, add_expense):
        uid = make_user()
        eid = add_expense(uid, 5, date=DATE)
        assert db_module.delete_expense(eid, uid) is True
        assert _row(db_path, eid) is None

    def test_wrong_user_returns_false_and_row_kept(
            self, db_path, make_user, add_expense):
        owner = make_user()
        intruder = make_user()
        eid = add_expense(owner, 5, date=DATE)
        before = _row(db_path, eid)
        assert db_module.delete_expense(eid, intruder) is False
        assert _row(db_path, eid) == before, "row must survive"

    def test_missing_id_returns_false(self, db_path, make_user):
        uid = make_user()
        assert db_module.delete_expense(MISSING_ID, uid) is False

    def test_only_target_row_deleted(self, db_path, make_user, add_expense):
        uid = make_user()
        keep = add_expense(uid, 1, date=DATE)
        gone = add_expense(uid, 2, date=DATE)
        assert db_module.delete_expense(gone, uid) is True
        assert _row(db_path, keep) is not None
        assert _row(db_path, gone) is None


# ------------------------------------------------------------- access control

class TestAccess:
    def test_signed_out_get_redirects_to_login(
            self, client, make_user, add_expense, db_path):
        uid = make_user()
        eid = add_expense(uid, 10, date=DATE)
        resp = client.get(_url(eid))
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        assert _row(db_path, eid) is not None

    def test_signed_out_post_redirects_to_login_and_deletes_nothing(
            self, client, make_user, add_expense, db_path):
        uid = make_user()
        eid = add_expense(uid, 10, date=DATE)
        resp = client.post(_url(eid))
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        assert _row(db_path, eid) is not None, "signed-out POST must not delete"

    def test_stale_user_get_clears_session_and_redirects(
            self, client, user, expense):
        _delete_user(user)
        resp = client.get(_url(expense))
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        with client.session_transaction() as sess:
            assert "user_id" not in sess, "session should be cleared"

    def test_stale_user_post_clears_session_and_redirects(
            self, client, user, expense):
        _delete_user(user)
        resp = client.post(_url(expense))
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        with client.session_transaction() as sess:
            assert "user_id" not in sess, "session should be cleared"

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_missing_id_returns_404(self, client, user, method):
        resp = getattr(client, method)(_url(MISSING_ID))
        assert resp.status_code == 404

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_other_users_expense_returns_404_and_row_survives(
            self, client, user, other_expense, db_path, method):
        before = _row(db_path, other_expense)
        resp = getattr(client, method)(_url(other_expense))
        assert resp.status_code == 404
        assert _row(db_path, other_expense) == before

    def test_body_user_id_and_id_are_ignored(
            self, client, user, other_expense, db_path):
        other_owner = _row(db_path, other_expense)[1]
        resp = client.post(_url(other_expense),
                           data={"user_id": user, "id": other_expense})
        assert resp.status_code == 404
        assert _row(db_path, other_expense) is not None
        assert _row(db_path, other_expense)[1] == other_owner


# ------------------------------------------------------ confirmation page (GET)

class TestConfirmationPage:
    def test_shows_expense_summary(self, client, expense):
        resp = client.get(_url(expense))
        assert resp.status_code == 200
        body = _body(resp)
        assert DATE in body
        assert "Lunch special" in body
        assert "Food" in body
        assert "₹12.50" in body
        assert "Delete expense" in body
        assert re.search(rf'<time[^>]*datetime="{DATE}"', body), \
            "date should be wrapped in <time datetime>"

    def test_has_cancel_link_to_profile(self, client, expense):
        body = _body(client.get(_url(expense)))
        cancel = re.search(r'<a[^>]*href="([^"]*)"[^>]*>\s*Cancel\s*</a>', body)
        assert cancel, "Cancel link expected"
        assert cancel.group(1) == "/profile"

    def test_null_description_shown_as_dash_not_none(
            self, client, expense, db_path):
        _set_description_null(db_path, expense)
        body = _body(client.get(_url(expense)))
        assert "—" in body
        assert "None" not in body

    def test_get_does_not_delete(self, client, expense, db_path):
        resp = client.get(_url(expense))
        assert resp.status_code == 200
        assert _row(db_path, expense) is not None, "GET must never delete"
        assert "Lunch special" in _body(client.get("/profile"))

    def test_form_posts_to_delete_url_and_has_no_inputs(self, client, expense):
        body = _body(client.get(_url(expense)))
        form = re.search(r"<form[^>]*>(.*?)</form>", body, re.S)
        assert form, "confirmation form expected"
        tag = re.search(r"<form[^>]*>", body).group(0)
        assert 'method="post"' in tag.lower()
        assert f'action="{_url(expense)}"' in tag
        assert "<input" not in form.group(1), \
            "form must not carry user_id / id inputs"
        assert "Delete expense" in form.group(1)

    def test_description_html_is_escaped(self, client, expense, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("UPDATE expenses SET description = ? WHERE id = ?",
                         ("<script>alert(1)</script>", expense))
            conn.commit()
        finally:
            conn.close()
        raw = client.get(_url(expense)).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in raw
        assert "&lt;script&gt;" in raw


# ------------------------------------------------------------ deleting (POST)

class TestDelete:
    def test_post_redirects_to_profile_and_flashes(self, client, expense):
        resp = client.post(_url(expense))
        assert resp.status_code == 302
        assert _location_path(resp) == "/profile"
        body = _body(client.get("/profile"))
        assert "Expense deleted." in body
        assert "Expense deleted." not in _body(client.get("/profile")), \
            "flash should be consumed"

    def test_row_gone_from_db_and_recent_transactions(
            self, client, expense, db_path):
        client.post(_url(expense))
        assert _row(db_path, expense) is None
        body = _body(client.get("/profile"))
        assert "Lunch special" not in body
        assert _url(expense) not in body

    def test_second_post_returns_404(self, client, expense):
        assert client.post(_url(expense)).status_code == 302
        assert client.post(_url(expense)).status_code == 404

    def test_get_after_delete_returns_404(self, client, expense):
        client.post(_url(expense))
        assert client.get(_url(expense)).status_code == 404

    def test_profile_stats_reflect_removal(
            self, client, user, add_expense):
        add_expense(user, 12.5, category="Food", date=DATE, description="Snack")
        add_expense(user, 40, category="Travel", date=DATE, description="Taxi")
        big = add_expense(user, 100, category="Bills", date=DATE,
                          description="Rent")
        before = _body(client.get("/profile"))
        assert _stat(before, "Transactions") == "3"
        assert _stat(before, "Top category") == "Bills"
        assert "₹152.50" in _stat(before, "Total spent")
        assert 'profile-cat-name">Bills<' in before

        client.post(_url(big))
        after = _body(client.get("/profile"))
        assert _stat(after, "Transactions") == "2"
        assert _stat(after, "Top category") == "Travel"
        assert "₹52.50" in _stat(after, "Total spent")
        assert 'profile-cat-name">Bills<' not in after
        assert 'profile-cat-name">Travel<' in after

    def test_other_rows_and_users_untouched(
            self, client, user, add_expense, other_expense, db_path):
        keep_same = add_expense(user, 3, category="Bills", date=DATE,
                                description="Keep me")
        target = add_expense(user, 4, category="Food", date=DATE,
                             description="Remove me")
        expenses_before = _all_expenses(db_path)
        users_before = _all_users(db_path)

        assert client.post(_url(target)).status_code == 302

        expected = [r for r in expenses_before if r[0] != target]
        assert _all_expenses(db_path) == expected
        assert _row(db_path, keep_same) is not None
        assert _row(db_path, other_expense) is not None
        assert _all_users(db_path) == users_before

    def test_deleting_last_expense_shows_empty_state(
            self, client, user, add_expense, db_path):
        # Use a fresh user (no seed data) with exactly one expense.
        eid = add_expense(user, 9, date=DATE, description="Only one")
        assert client.post(_url(eid)).status_code == 302
        assert "No expenses yet." in _body(client.get("/profile"))


# --------------------------------------------------------------- profile links

class TestProfileLinks:
    def test_each_row_has_delete_and_edit_links_with_distinct_labels(
            self, client, user, add_expense):
        e1 = add_expense(user, 5, date=DATE, description="Coffee")
        e2 = add_expense(user, 6, date="2026-09-02", description="Tea")
        body = _body(client.get("/profile"))
        for eid, desc in ((e1, "Coffee"), (e2, "Tea")):
            delete = re.search(
                rf'<a[^>]*href="{_url(eid)}"[^>]*>', body)
            assert delete, f"delete link for expense {eid} expected"
            edit = re.search(
                rf'<a[^>]*href="/expenses/{eid}/edit"[^>]*>', body)
            assert edit, f"edit link for expense {eid} expected"
            d_label = re.search(r'aria-label="([^"]*)"', delete.group(0))
            e_label = re.search(r'aria-label="([^"]*)"', edit.group(0))
            assert d_label and e_label, "both links need aria-labels"
            assert d_label.group(1).startswith("Delete")
            assert desc in d_label.group(1)
            assert e_label.group(1).startswith("Edit")
            assert d_label.group(1) != e_label.group(1)

    def test_trash_icon_is_aria_hidden(self, client, expense):
        body = _body(client.get("/profile"))
        icon = re.search(r'<i[^>]*data-lucide="trash-2"[^>]*>', body)
        assert icon, "trash-2 icon expected on profile"
        assert 'aria-hidden="true"' in icon.group(0)

    def test_profile_delete_link_does_not_delete(
            self, client, expense, db_path):
        client.get(_url(expense))
        assert _row(db_path, expense) is not None


# ------------------------------------------------------------ static hygiene

class TestStaticHygiene:
    @pytest.mark.parametrize("name", ["expense.css", "profile.css"])
    def test_css_has_no_hardcoded_hex_colours(self, name):
        css = (ROOT / "static" / "css" / name).read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), \
            f"{name} must use CSS variables, not hex colours"

    def test_template_has_no_style_tags_or_attributes(self):
        src = (ROOT / "templates" / "delete_expense.html").read_text(
            encoding="utf-8")
        assert "<style" not in src.lower()
        assert not re.search(r"\sstyle\s*=", src, re.I)
