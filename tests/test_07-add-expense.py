"""Tests for Step 07: add expense (spec-driven)."""
import html as html_lib
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import database.db as db_module
from database.db import CATEGORIES

ROOT = Path(__file__).resolve().parents[1]
URL = "/expenses/add"


# ------------------------------------------------------------------ helpers

def _login(client, email, password="password123"):
    resp = client.post("/login", data={"email": email, "password": password})
    assert resp.status_code == 302, "login should redirect on success"


def _body(resp):
    return html_lib.unescape(resp.get_data(as_text=True))


def _expense_count():
    conn = db_module.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    finally:
        conn.close()


def _rows(where="1=1", params=()):
    conn = db_module.get_db()
    try:
        return conn.execute(
            "SELECT user_id, amount, category, date, description FROM expenses "
            "WHERE " + where + " ORDER BY id",
            params,
        ).fetchall()
    finally:
        conn.close()


def _form(**overrides):
    data = {
        "amount": "250.50",
        "category": "Food",
        "date": "2026-09-15",
        "description": "Dinner",
    }
    data.update(overrides)
    return data


@pytest.fixture
def user(client, make_user):
    """Fresh user, signed in via POST /login."""
    uid = make_user(name="Adder", email="adder@example.com")
    _login(client, "adder@example.com")
    return uid


def _location_path(resp):
    return re.sub(r"^https?://[^/]+", "", resp.headers["Location"]).split("?")[0]


# ------------------------------------------------------------- access control

class TestAccess:
    def test_signed_out_get_redirects_to_login(self, client):
        resp = client.get(URL)
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"

    def test_signed_out_post_redirects_to_login_and_inserts_nothing(self, client):
        before = _expense_count()
        resp = client.post(URL, data=_form())
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        assert _expense_count() == before, "signed-out POST must not insert"

    def test_stale_user_get_clears_session_and_redirects(self, client):
        with client.session_transaction() as sess:
            sess["user_id"] = 999999
        resp = client.get(URL)
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        with client.session_transaction() as sess:
            assert "user_id" not in sess, "session should be cleared"

    def test_stale_user_post_clears_session_and_inserts_nothing(self, client):
        with client.session_transaction() as sess:
            sess["user_id"] = 999999
        before = _expense_count()
        resp = client.post(URL, data=_form())
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        assert _expense_count() == before
        with client.session_transaction() as sess:
            assert "user_id" not in sess


# ------------------------------------------------------------------ GET form

class TestForm:
    def test_get_returns_200_with_fields_button_and_cancel(self, client, user):
        resp = client.get(URL)
        body = _body(resp)
        assert resp.status_code == 200
        for name in ("amount", "category", "date", "description"):
            assert f'name="{name}"' in body, f"missing field {name}"
        assert "Add expense" in body
        assert "Cancel" in body
        cancel = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*Cancel', body)
        assert cancel, "Cancel link expected"
        assert cancel.group(1) == "/profile"

    def test_category_dropdown_lists_exactly_the_categories(self, client, user):
        body = _body(client.get(URL))
        select = re.search(
            r'<select[^>]*name="category"[^>]*>(.*?)</select>', body, re.S)
        assert select, "category select expected"
        values = re.findall(r'<option[^>]*value="([^"]*)"', select.group(1))
        values = [v for v in values if v]  # drop placeholder with empty value
        assert len(CATEGORIES) == 7
        assert sorted(values) == sorted(CATEGORIES)

    def test_no_category_preselected(self, client, user):
        body = _body(client.get(URL))
        select = re.search(
            r'<select[^>]*name="category"[^>]*>(.*?)</select>', body, re.S).group(1)
        for opt in re.findall(r"<option[^>]*>", select):
            if 'value=""' in opt or "disabled" in opt:
                continue
            assert "selected" not in opt, "no real category should be preselected"

    def test_date_field_defaults_to_today(self, client, user):
        body = _body(client.get(URL))
        tag = re.search(r'<input[^>]*name="date"[^>]*>', body)
        assert tag, "date input expected"
        assert f'value="{date.today().isoformat()}"' in tag.group(0)

    def test_no_error_shown_on_fresh_get(self, client, user):
        assert 'role="alert"' not in _body(client.get(URL))

    def test_profile_add_expense_link_opens_form_not_stub(self, client, user):
        body = _body(client.get("/profile"))
        link = re.search(r'href="([^"]*expenses/add[^"]*)"', body)
        assert link, "profile should link to add expense"
        resp = client.get(link.group(1))
        assert resp.status_code == 200
        text = _body(resp)
        assert 'name="amount"' in text, "should be the real form"
        assert "coming in Step" not in text


# ------------------------------------------------------------------- success

class TestSuccess:
    def test_valid_post_redirects_to_profile_and_flashes(self, client, user):
        resp = client.post(URL, data=_form())
        assert resp.status_code == 302
        assert _location_path(resp) == "/profile"
        page = client.get("/profile")
        body = _body(page)
        status = re.search(r'role="status"[^>]*>(.*?)</p>', body, re.S)
        assert status and "Expense added." in status.group(1)
        # Flash is consumed on the following request
        assert "Expense added." not in _body(client.get("/profile"))

    def test_valid_post_inserts_row_for_user(self, client, user):
        client.post(URL, data=_form())
        rows = _rows("user_id = ?", (user,))
        assert len(rows) == 1
        r = rows[0]
        assert r["amount"] == pytest.approx(250.50)
        assert r["category"] == "Food"
        assert r["date"] == "2026-09-15"
        assert r["description"] == "Dinner"

    def test_new_row_appears_in_recent_transactions_with_amount(self, client, user):
        client.post(URL, data=_form())
        body = _body(client.get("/profile"))
        assert "Dinner" in body
        assert "₹250.50" in body

    def test_totals_and_breakdown_include_new_expense(
            self, client, make_user, add_expense):
        uid = make_user(name="Totals", email="totals@example.com")
        add_expense(uid, 100, category="Bills", date="2026-09-01",
                    description="Existing")
        _login(client, "totals@example.com")
        before = _body(client.get("/profile"))
        assert "₹100.00" in before
        client.post(URL, data=_form(category="Shopping"))
        after = _body(client.get("/profile"))
        assert "₹350.50" in after, "total spent should be 100 + 250.50"
        assert "Shopping" in after, "category breakdown should list new category"
        assert "₹250.50" in after
        assert len(_rows("user_id = ?", (uid,))) == 2

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_description_saved_as_null_and_dash_shown(
            self, client, user, blank):
        client.post(URL, data=_form(description=blank))
        rows = _rows("user_id = ?", (user,))
        assert len(rows) == 1
        assert rows[0]["description"] is None
        assert "—" in _body(client.get("/profile"))

    def test_today_is_accepted(self, client, user):
        resp = client.post(URL, data=_form(date=date.today().isoformat()))
        assert resp.status_code == 302
        assert len(_rows("user_id = ?", (user,))) == 1

    def test_description_of_exactly_200_chars_is_accepted(self, client, user):
        resp = client.post(URL, data=_form(description="x" * 200))
        assert resp.status_code == 302
        assert len(_rows("user_id = ?", (user,))) == 1

    def test_user_id_in_form_is_ignored(self, client, user, make_user):
        other = make_user(name="Other", email="other@example.com")
        resp = client.post(URL, data=_form(user_id=str(other)))
        assert resp.status_code == 302
        assert len(_rows("user_id = ?", (user,))) == 1
        assert _rows("user_id = ?", (other,)) == [], "must not write for other user"

    def test_demo_user_can_add(self, client):
        _login(client, "demo@spendly.com", "demo123")
        before = _expense_count()
        resp = client.post(URL, data=_form(description="DemoAdded"))
        assert resp.status_code == 302
        assert _expense_count() == before + 1

    def test_sql_injection_in_description_stored_literally(self, client, user):
        payload = "'); DROP TABLE expenses;--"
        resp = client.post(URL, data=_form(description=payload))
        assert resp.status_code == 302
        rows = _rows("user_id = ?", (user,))
        assert rows[0]["description"] == payload


# ---------------------------------------------------------------- validation

class TestValidation:
    def _assert_rejected(self, client, **overrides):
        before = _expense_count()
        resp = client.post(URL, data=_form(**overrides))
        assert resp.status_code == 400, f"expected 400 for {overrides}"
        assert 'role="alert"' in resp.get_data(as_text=True), "inline error expected"
        assert _expense_count() == before, "nothing should be inserted"
        return resp

    @pytest.mark.parametrize("amount", [
        "", "   ", "0", "0.00", "-5", "abc", "nan", "NaN", "inf", "-inf",
        "Infinity", "12.345", "10000000.01", "10000001", "99999999999",
    ])
    def test_invalid_amount_returns_400(self, client, user, amount):
        self._assert_rejected(client, amount=amount)

    def test_missing_amount_field_returns_400(self, client, user):
        data = _form()
        del data["amount"]
        before = _expense_count()
        resp = client.post(URL, data=data)
        assert resp.status_code == 400
        assert _expense_count() == before

    @pytest.mark.parametrize("amount", ["0.01", "10000000", "10000000.00", "5"])
    def test_boundary_amounts_accepted(self, client, user, amount):
        resp = client.post(URL, data=_form(amount=amount))
        assert resp.status_code == 302, f"{amount} should be valid"
        assert len(_rows("user_id = ?", (user,))) == 1

    @pytest.mark.parametrize("category", [
        "Rent", "", "food", "FOOD", " Food", "Food ", "<script>"])
    def test_invalid_category_returns_400(self, client, user, category):
        self._assert_rejected(client, category=category)

    def test_missing_category_field_returns_400(self, client, user):
        data = _form()
        del data["category"]
        before = _expense_count()
        assert client.post(URL, data=data).status_code == 400
        assert _expense_count() == before

    @pytest.mark.parametrize("category", list(CATEGORIES))
    def test_every_listed_category_is_accepted(self, client, user, category):
        resp = client.post(URL, data=_form(category=category))
        assert resp.status_code == 302
        assert _rows("user_id = ?", (user,))[0]["category"] == category

    @pytest.mark.parametrize("bad_date", [
        "", "   ", "2026-13-01", "2026-9-1", "2026-02-30", "20260915",
        "15-09-2026", "2026/09/15", "not-a-date", "2026-09-15x",
    ])
    def test_invalid_date_returns_400(self, client, user, bad_date):
        self._assert_rejected(client, date=bad_date)

    def test_future_date_returns_400(self, client, user):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self._assert_rejected(client, date=tomorrow)

    def test_far_future_date_returns_400(self, client, user):
        far = (date.today() + timedelta(days=3650)).isoformat()
        self._assert_rejected(client, date=far)

    def test_missing_date_field_returns_400(self, client, user):
        data = _form()
        del data["date"]
        before = _expense_count()
        assert client.post(URL, data=data).status_code == 400
        assert _expense_count() == before

    def test_description_over_200_chars_returns_400(self, client, user):
        self._assert_rejected(client, description="x" * 201)

    def test_validation_error_does_not_flash_or_redirect(self, client, user):
        resp = client.post(URL, data=_form(amount="abc"))
        assert resp.status_code == 400
        assert "Location" not in resp.headers
        body = _body(client.get("/profile"))
        assert "Expense added." not in body

    def test_submitted_values_preserved_after_error(self, client, user):
        resp = client.post(URL, data=_form(
            amount="12.345", category="Health",
            date="2026-08-20", description="Keep me"))
        body = _body(resp)
        assert resp.status_code == 400
        assert 'value="12.345"' in body
        assert 'value="2026-08-20"' in body
        assert "Keep me" in body
        select = re.search(
            r'<select[^>]*name="category"[^>]*>(.*?)</select>', body, re.S).group(1)
        selected = [o for o in re.findall(r"<option[^>]*>", select)
                    if "selected" in o and "disabled" not in o]
        assert len(selected) == 1 and 'value="Health"' in selected[0], \
            "previously chosen category should stay selected"

    def test_html_in_preserved_values_is_escaped_on_error_page(self, client, user):
        resp = client.post(URL, data=_form(
            amount="abc", description='"><script>alert(1)</script>'))
        raw = resp.get_data(as_text=True)
        assert resp.status_code == 400
        assert "<script>alert(1)</script>" not in raw


# ------------------------------------------------------------------ escaping

class TestEscaping:
    def test_script_in_description_escaped_on_profile(self, client, user):
        client.post(URL, data=_form(description="<script>alert(1)</script>"))
        raw = client.get("/profile").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in raw, "must be escaped"
        assert "&lt;script&gt;" in raw


# --------------------------------------------------------------- other stubs

class TestStubsUntouched:
    def test_delete_stub_still_returns_stub_string(self, client, user):
        resp = client.get("/expenses/1/delete")
        assert resp.status_code == 200
        assert "Delete expense — coming in Step 9" in resp.get_data(as_text=True)


# ------------------------------------------------------------ static hygiene

class TestStaticHygiene:
    def test_expense_css_has_no_hardcoded_hex_colours(self):
        css = (ROOT / "static" / "css" / "expense.css").read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), \
            "expense.css must use CSS variables, not hex colours"

    def test_template_has_no_style_tag_or_attribute(self):
        tpl = (ROOT / "templates" / "add_expense.html").read_text(encoding="utf-8")
        assert not re.search(r"<style\b", tpl, re.I), "no <style> tags allowed"
        assert not re.search(r"\sstyle\s*=", tpl, re.I), "no style= attributes allowed"

    def test_template_extends_base(self):
        tpl = (ROOT / "templates" / "add_expense.html").read_text(encoding="utf-8")
        assert re.search(r"{%\s*extends\s+[\"']base.html[\"']\s*%}", tpl)
