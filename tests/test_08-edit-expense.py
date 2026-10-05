"""Tests for Step 08: edit expense (spec-driven)."""
import html as html_lib
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import database.db as db_module
from database.db import CATEGORIES

ROOT = Path(__file__).resolve().parents[1]
MISSING_ID = 999999
NEW_DATE = (date.today() - timedelta(days=20)).isoformat()
OLD_DATE = (date.today() - timedelta(days=40)).isoformat()


# ------------------------------------------------------------------ helpers

def _url(expense_id):
    return f"/expenses/{expense_id}/edit"


def _login(client, email, password="password123"):
    resp = client.post("/login", data={"email": email, "password": password})
    assert resp.status_code == 302, "login should redirect on success"


def _body(resp):
    return html_lib.unescape(resp.get_data(as_text=True))


def _location_path(resp):
    return re.sub(r"^https?://[^/]+", "", resp.headers["Location"]).split("?")[0]


def _row(expense_id):
    conn = db_module.get_db()
    try:
        r = conn.execute(
            "SELECT id, user_id, amount, category, date, description, created_at "
            "FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        return tuple(r) if r else None
    finally:
        conn.close()


def _all_rows():
    conn = db_module.get_db()
    try:
        return [tuple(r) for r in conn.execute(
            "SELECT id, user_id, amount, category, date, description, created_at "
            "FROM expenses ORDER BY id").fetchall()]
    finally:
        conn.close()


def _form(**overrides):
    data = {
        "amount": "99.99",
        "category": "Bills",
        "date": NEW_DATE,
        "description": "Updated",
    }
    data.update(overrides)
    return data


def _input_tag(body, name):
    tag = re.search(rf'<input[^>]*name="{name}"[^>]*>', body)
    assert tag, f"input {name} expected"
    return tag.group(0)


def _select_options(body):
    select = re.search(
        r'<select[^>]*name="category"[^>]*>(.*?)</select>', body, re.S)
    assert select, "category select expected"
    return re.findall(r"<option[^>]*>", select.group(1))


def _delete_user(user_id):
    conn = db_module.get_db()
    try:
        conn.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def user(client, make_user):
    """Fresh user, signed in via POST /login."""
    uid = make_user(name="Editor", email="editor@example.com")
    _login(client, "editor@example.com")
    return uid


@pytest.fixture
def expense(user, add_expense):
    """An expense owned by the signed-in user."""
    return add_expense(user, 12.5, category="Food", date=OLD_DATE,
                       description="Original")


@pytest.fixture
def other_expense(make_user, add_expense):
    """An expense owned by a different user."""
    other = make_user(name="Other", email="other@example.com")
    return add_expense(other, 77.0, category="Travel", date=OLD_DATE,
                       description="Not yours")


# ------------------------------------------------------------- access control

class TestAccess:
    def test_signed_out_get_redirects_to_login(self, client, make_user, add_expense):
        uid = make_user(name="Owner", email="owner@example.com")
        eid = add_expense(uid, 10, date=OLD_DATE)
        resp = client.get(_url(eid))
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"

    def test_signed_out_post_redirects_to_login_and_changes_nothing(
            self, client, make_user, add_expense):
        uid = make_user(name="Owner", email="owner@example.com")
        eid = add_expense(uid, 10, date=OLD_DATE)
        before = _row(eid)
        resp = client.post(_url(eid), data=_form())
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        assert _row(eid) == before, "signed-out POST must not change the row"

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
        resp = client.post(_url(expense), data=_form())
        assert resp.status_code == 302
        assert _location_path(resp) == "/login"
        with client.session_transaction() as sess:
            assert "user_id" not in sess, "session should be cleared"

    def test_stale_session_for_nonexistent_user_redirects_even_for_missing_id(
            self, client):
        with client.session_transaction() as sess:
            sess["user_id"] = MISSING_ID
        resp = client.get(_url(MISSING_ID))
        assert resp.status_code == 302, "login redirect takes precedence over 404"
        assert _location_path(resp) == "/login"


class TestNotFoundAndOwnership:
    def test_get_missing_id_returns_404(self, client, user):
        assert client.get(_url(MISSING_ID)).status_code == 404

    def test_post_missing_id_returns_404(self, client, user):
        before = _all_rows()
        assert client.post(_url(MISSING_ID), data=_form()).status_code == 404
        assert _all_rows() == before

    def test_get_other_users_expense_returns_404(
            self, client, user, other_expense):
        resp = client.get(_url(other_expense))
        assert resp.status_code == 404
        assert "Not yours" not in resp.get_data(as_text=True), \
            "404 must not leak the other user's data"

    def test_post_other_users_expense_returns_404_and_row_unchanged(
            self, client, user, other_expense):
        before = _row(other_expense)
        resp = client.post(_url(other_expense), data=_form())
        assert resp.status_code == 404
        assert _row(other_expense) == before

    def test_other_and_missing_return_same_status(
            self, client, user, other_expense):
        assert (client.get(_url(other_expense)).status_code
                == client.get(_url(MISSING_ID)).status_code == 404)

    def test_invalid_post_to_other_users_expense_still_404(
            self, client, user, other_expense):
        resp = client.post(_url(other_expense), data=_form(amount="abc"))
        assert resp.status_code == 404, "ownership is checked before validation"


# ------------------------------------------------------------------ GET form

class TestForm:
    def test_get_returns_200_with_prefilled_values_button_and_cancel(
            self, client, expense):
        resp = client.get(_url(expense))
        body = _body(resp)
        assert resp.status_code == 200
        for name in ("amount", "category", "date", "description"):
            assert f'name="{name}"' in body, f"missing field {name}"
        assert 'value="12.50"' in _input_tag(body, "amount")
        assert f'value="{OLD_DATE}"' in _input_tag(body, "date")
        assert 'value="Original"' in _input_tag(body, "description")
        assert "Save changes" in body
        assert "Edit expense" in body
        cancel = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*Cancel', body)
        assert cancel, "Cancel link expected"
        assert cancel.group(1) == "/profile"

    def test_form_posts_to_the_edit_url(self, client, expense):
        body = _body(client.get(_url(expense)))
        form = re.search(r"<form[^>]*>", body)
        assert form, "form expected"
        assert 'method="post"' in form.group(0).lower()
        assert f'action="{_url(expense)}"' in form.group(0)

    def test_title_is_edit_expense(self, client, expense):
        body = _body(client.get(_url(expense)))
        title = re.search(r"<title>(.*?)</title>", body, re.S)
        assert title and "Edit expense" in title.group(1)

    @pytest.mark.parametrize("stored,expected", [
        (12.5, "12.50"), (100, "100.00"), (0.1, "0.10"), (1234.56, "1234.56"),
    ])
    def test_amount_prefilled_with_two_decimals(
            self, client, user, add_expense, stored, expected):
        eid = add_expense(user, stored, date=OLD_DATE)
        body = _body(client.get(_url(eid)))
        assert f'value="{expected}"' in _input_tag(body, "amount")

    def test_null_description_prefilled_as_empty(
            self, client, user, add_expense):
        eid = add_expense(user, 5, date=OLD_DATE, description=None)
        body = _body(client.get(_url(eid)))
        tag = _input_tag(body, "description")
        assert 'value=""' in tag
        assert "None" not in tag
        assert "—" not in tag

    def test_category_dropdown_lists_exactly_the_categories(self, client, expense):
        body = _body(client.get(_url(expense)))
        select = re.search(
            r'<select[^>]*name="category"[^>]*>(.*?)</select>', body, re.S).group(1)
        values = [v for v in re.findall(r'<option[^>]*value="([^"]*)"', select) if v]
        assert len(CATEGORIES) == 7
        assert sorted(values) == sorted(CATEGORIES)

    @pytest.mark.parametrize("category", list(CATEGORIES))
    def test_stored_category_is_selected(
            self, client, user, add_expense, category):
        eid = add_expense(user, 5, category=category, date=OLD_DATE)
        body = _body(client.get(_url(eid)))
        selected = [o for o in _select_options(body)
                    if "selected" in o and "disabled" not in o]
        assert len(selected) == 1, "exactly one category should be selected"
        assert f'value="{category}"' in selected[0]

    def test_no_error_shown_on_fresh_get(self, client, expense):
        assert 'role="alert"' not in _body(client.get(_url(expense)))

    def test_amount_input_attributes(self, client, expense):
        tag = _input_tag(_body(client.get(_url(expense))), "amount")
        assert 'step="0.01"' in tag
        assert 'min="0.01"' in tag
        assert 'max="10000000"' in tag

    def test_date_input_max_is_today(self, client, expense):
        tag = _input_tag(_body(client.get(_url(expense))), "date")
        assert f'max="{date.today().isoformat()}"' in tag

    def test_description_input_maxlength(self, client, expense):
        tag = _input_tag(_body(client.get(_url(expense))), "description")
        assert 'maxlength="200"' in tag

    def test_html_in_description_is_escaped_on_edit_form(
            self, client, user, add_expense):
        eid = add_expense(user, 5, date=OLD_DATE,
                          description='"><script>alert(1)</script>')
        raw = client.get(_url(eid)).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in raw, "must be escaped"


# ------------------------------------------------------------ profile link

class TestProfileEditLinks:
    def test_each_recent_transaction_row_has_edit_link(
            self, client, user, add_expense):
        ids = {
            add_expense(user, 10, date=OLD_DATE, description="RowAlpha"): "RowAlpha",
            add_expense(user, 20, date=NEW_DATE, description="RowBeta"): "RowBeta",
            add_expense(user, 30, date=NEW_DATE, description="RowGamma"): "RowGamma",
        }
        body = _body(client.get("/profile"))
        rows = re.findall(r"<tr\b.*?</tr>", body, re.S)
        for eid, desc in ids.items():
            matching = [r for r in rows if desc in r]
            assert matching, f"row for {desc} expected"
            assert f'href="{_url(eid)}"' in matching[0], \
                f"row for {desc} should link to its edit page"

    def test_edit_link_opens_the_edit_form(self, client, expense):
        body = _body(client.get("/profile"))
        link = re.search(r'href="([^"]*/expenses/\d+/edit)"', body)
        assert link, "profile should link to an edit page"
        resp = client.get(link.group(1))
        assert resp.status_code == 200
        assert "Save changes" in _body(resp)

    def test_profile_has_no_delete_link(self, client, expense):
        assert "/delete" not in _body(client.get("/profile"))


# ------------------------------------------------------------------- success

class TestSuccess:
    def test_valid_post_redirects_to_profile_and_flashes(self, client, expense):
        resp = client.post(_url(expense), data=_form())
        assert resp.status_code == 302
        assert _location_path(resp) == "/profile"
        body = _body(client.get("/profile"))
        status = re.search(r'role="status"[^>]*>(.*?)</p>', body, re.S)
        assert status and "Expense updated." in status.group(1)
        assert "Expense updated." not in _body(client.get("/profile")), \
            "flash should be consumed"

    def test_valid_post_updates_row(self, client, user, expense):
        created_before = _row(expense)[-1]
        client.post(_url(expense), data=_form())
        row = _row(expense)
        assert row[1] == user, "owner must not change"
        assert row[2] == pytest.approx(99.99)
        assert row[3] == "Bills"
        assert row[4] == NEW_DATE
        assert row[5] == "Updated"
        assert row[6] == created_before, "created_at must not change"

    def test_updated_row_shows_new_values_on_profile(self, client, expense):
        client.post(_url(expense), data=_form())
        body = _body(client.get("/profile"))
        assert "₹99.99" in body
        assert "Updated" in body
        assert "Bills" in body
        assert "Original" not in body
        assert "₹12.50" not in body

    def test_totals_and_breakdown_reflect_new_values(
            self, client, make_user, add_expense):
        uid = make_user(name="Totals", email="totals@example.com")
        eid = add_expense(uid, 100, category="Food", date=OLD_DATE,
                          description="Big")
        add_expense(uid, 30, category="Bills", date=OLD_DATE,
                    description="Small")
        _login(client, "totals@example.com")
        before = _body(client.get("/profile"))
        assert "₹130.00" in before
        assert "₹100.00" in before
        client.post(_url(eid), data=_form())  # 99.99 Bills
        after = _body(client.get("/profile"))
        assert "₹129.99" in after, "total spent (and Bills breakdown) = 99.99 + 30"
        assert "₹130.00" not in after
        assert "₹100.00" not in after
        assert "Food" not in after, "Food no longer has any spend"
        conn = db_module.get_db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (uid,)
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 2, "transaction count must be unchanged"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_description_saved_as_null_and_dash_shown(
            self, client, expense, blank):
        client.post(_url(expense), data=_form(description=blank))
        assert _row(expense)[5] is None
        assert "—" in _body(client.get("/profile"))

    def test_editing_one_expense_leaves_all_other_rows_unchanged(
            self, client, user, expense, other_expense, add_expense):
        sibling = add_expense(user, 44, category="Health", date=OLD_DATE,
                              description="Sibling")
        before = {r[0]: r for r in _all_rows()}
        resp = client.post(_url(expense), data=_form())
        assert resp.status_code == 302
        after = {r[0]: r for r in _all_rows()}
        assert after[expense] != before[expense]
        for eid in before:
            if eid != expense:
                assert after[eid] == before[eid], f"row {eid} must not change"
        assert after[sibling] == before[sibling]
        assert after[other_expense] == before[other_expense]
        assert len(after) == len(before)

    def test_user_id_in_form_is_ignored(
            self, client, user, expense, make_user):
        other = make_user(name="Intruder", email="intruder@example.com")
        resp = client.post(_url(expense), data=_form(user_id=str(other)))
        assert resp.status_code == 302
        assert _row(expense)[1] == user, "user_id must not change"
        assert _row(expense)[2] == pytest.approx(99.99)

    def test_id_in_form_is_ignored(self, client, user, expense, add_expense):
        sibling = add_expense(user, 44, date=OLD_DATE, description="Sibling")
        before = _row(sibling)
        client.post(_url(expense), data=_form(id=str(sibling)))
        assert _row(sibling) == before, "id comes only from the URL"
        assert _row(expense)[2] == pytest.approx(99.99)

    def test_today_is_accepted(self, client, expense):
        resp = client.post(
            _url(expense), data=_form(date=date.today().isoformat()))
        assert resp.status_code == 302
        assert _row(expense)[4] == date.today().isoformat()

    def test_description_of_exactly_200_chars_is_accepted(self, client, expense):
        resp = client.post(_url(expense), data=_form(description="x" * 200))
        assert resp.status_code == 302
        assert _row(expense)[5] == "x" * 200

    @pytest.mark.parametrize("amount", ["0.01", "10000000", "10000000.00", "5"])
    def test_boundary_amounts_accepted(self, client, expense, amount):
        resp = client.post(_url(expense), data=_form(amount=amount))
        assert resp.status_code == 302, f"{amount} should be valid"
        assert _row(expense)[2] == pytest.approx(float(amount))

    @pytest.mark.parametrize("category", list(CATEGORIES))
    def test_every_category_is_accepted(self, client, expense, category):
        resp = client.post(_url(expense), data=_form(category=category))
        assert resp.status_code == 302
        assert _row(expense)[3] == category

    def test_sql_injection_in_description_stored_literally(self, client, expense):
        payload = "'); DROP TABLE expenses;--"
        resp = client.post(_url(expense), data=_form(description=payload))
        assert resp.status_code == 302
        assert _row(expense)[5] == payload

    def test_script_in_description_escaped_on_profile(self, client, expense):
        client.post(_url(expense),
                    data=_form(description="<script>alert(1)</script>"))
        raw = client.get("/profile").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in raw, "must be escaped"
        assert "&lt;script&gt;" in raw


# ---------------------------------------------------------------- validation

class TestValidation:
    def _assert_rejected(self, client, expense, **overrides):
        before = _row(expense)
        resp = client.post(_url(expense), data=_form(**overrides))
        assert resp.status_code == 400, f"expected 400 for {overrides}"
        assert 'role="alert"' in resp.get_data(as_text=True), "inline error expected"
        assert _row(expense) == before, "row must be unchanged"
        return resp

    @pytest.mark.parametrize("amount", [
        "", "   ", "0", "0.00", "-5", "abc", "nan", "NaN", "inf", "-inf",
        "Infinity", "12.345", "10000000.01", "10000001", "99999999999",
    ])
    def test_invalid_amount_returns_400(self, client, expense, amount):
        self._assert_rejected(client, expense, amount=amount)

    def test_missing_amount_field_returns_400(self, client, expense):
        before = _row(expense)
        data = _form()
        del data["amount"]
        assert client.post(_url(expense), data=data).status_code == 400
        assert _row(expense) == before

    @pytest.mark.parametrize("category", [
        "Rent", "", "food", "FOOD", " Food", "Food ", "<script>"])
    def test_invalid_category_returns_400(self, client, expense, category):
        self._assert_rejected(client, expense, category=category)

    def test_missing_category_field_returns_400(self, client, expense):
        before = _row(expense)
        data = _form()
        del data["category"]
        assert client.post(_url(expense), data=data).status_code == 400
        assert _row(expense) == before

    @pytest.mark.parametrize("bad_date", [
        "", "   ", "2026-13-01", "2026-9-1", "2026-02-30", "20260915",
        "15-09-2026", "2026/09/15", "not-a-date", "2026-09-15x",
    ])
    def test_invalid_date_returns_400(self, client, expense, bad_date):
        self._assert_rejected(client, expense, date=bad_date)

    def test_future_date_returns_400(self, client, expense):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self._assert_rejected(client, expense, date=tomorrow)

    def test_far_future_date_returns_400(self, client, expense):
        far = (date.today() + timedelta(days=3650)).isoformat()
        self._assert_rejected(client, expense, date=far)

    def test_missing_date_field_returns_400(self, client, expense):
        before = _row(expense)
        data = _form()
        del data["date"]
        assert client.post(_url(expense), data=data).status_code == 400
        assert _row(expense) == before

    def test_description_over_200_chars_returns_400(self, client, expense):
        self._assert_rejected(client, expense, description="x" * 201)

    def test_validation_error_does_not_flash_or_redirect(self, client, expense):
        resp = client.post(_url(expense), data=_form(amount="abc"))
        assert resp.status_code == 400
        assert "Location" not in resp.headers
        assert "Expense updated." not in _body(client.get("/profile"))

    def test_submitted_values_shown_not_stored_ones_after_error(
            self, client, expense):
        resp = client.post(_url(expense), data=_form(
            amount="12.345", category="Health",
            date=NEW_DATE, description="Keep me"))
        body = _body(resp)
        assert resp.status_code == 400
        assert 'value="12.345"' in _input_tag(body, "amount")
        assert f'value="{NEW_DATE}"' in _input_tag(body, "date")
        assert 'value="Keep me"' in _input_tag(body, "description")
        assert "Original" not in body, "stored description must not be shown"
        assert 'value="12.50"' not in body, "stored amount must not be shown"
        selected = [o for o in _select_options(body)
                    if "selected" in o and "disabled" not in o]
        assert len(selected) == 1 and 'value="Health"' in selected[0], \
            "submitted category should be selected"

    def test_form_still_posts_to_edit_url_after_error(self, client, expense):
        body = _body(client.post(_url(expense), data=_form(amount="abc")))
        form = re.search(r"<form[^>]*>", body).group(0)
        assert f'action="{_url(expense)}"' in form

    def test_html_in_submitted_values_is_escaped_on_error_page(
            self, client, expense):
        resp = client.post(_url(expense), data=_form(
            amount="abc", description='"><script>alert(1)</script>'))
        assert resp.status_code == 400
        assert "<script>alert(1)</script>" not in resp.get_data(as_text=True)


# --------------------------------------------------------------- other stubs

class TestStubsUntouched:
    def test_delete_stub_still_returns_stub_string(self, client, user):
        resp = client.get("/expenses/1/delete")
        assert resp.status_code == 200
        assert "Delete expense — coming in Step 9" in resp.get_data(as_text=True)


# ------------------------------------------------------- get_expense (queries)

class TestGetExpenseQuery:
    def test_returns_dict_for_owner(self, make_user, add_expense):
        from database.queries import get_expense
        uid = make_user()
        eid = add_expense(uid, 12.5, category="Health", date="2026-08-01",
                          description="Pills")
        result = get_expense(eid, uid)
        assert isinstance(result, dict)
        assert result["id"] == eid
        assert result["amount"] == pytest.approx(12.5)
        assert result["category"] == "Health"
        assert result["date"] == "2026-08-01"
        assert result["description"] == "Pills"

    def test_returns_none_for_other_user(self, make_user, add_expense):
        from database.queries import get_expense
        owner = make_user()
        intruder = make_user()
        eid = add_expense(owner, 5)
        assert get_expense(eid, intruder) is None

    def test_returns_none_for_missing_id(self, make_user):
        from database.queries import get_expense
        uid = make_user()
        assert get_expense(MISSING_ID, uid) is None

    def test_null_description_returned_as_none(self, make_user, add_expense):
        from database.queries import get_expense
        uid = make_user()
        eid = add_expense(uid, 5, description=None)
        result = get_expense(eid, uid)
        assert result is not None
        assert result["description"] is None, "raw NULL, not a placeholder"


# ------------------------------------------------------ update_expense (db)

class TestUpdateExpenseHelper:
    def test_updates_row_and_returns_true(self, make_user, add_expense):
        uid = make_user()
        eid = add_expense(uid, 10, category="Food", date=OLD_DATE,
                          description="Old")
        created = _row(eid)[-1]
        result = db_module.update_expense(
            eid, uid, 55.55, "Bills", NEW_DATE, "New")
        assert result is True
        row = _row(eid)
        assert row[1] == uid
        assert row[2] == pytest.approx(55.55)
        assert row[3] == "Bills"
        assert row[4] == NEW_DATE
        assert row[5] == "New"
        assert row[6] == created

    def test_none_description_stored_as_null(self, make_user, add_expense):
        uid = make_user()
        eid = add_expense(uid, 10, date=OLD_DATE, description="Old")
        assert db_module.update_expense(
            eid, uid, 10, "Food", OLD_DATE, None) is True
        assert _row(eid)[5] is None

    def test_wrong_owner_returns_false_and_changes_nothing(
            self, make_user, add_expense):
        owner = make_user()
        intruder = make_user()
        eid = add_expense(owner, 10, date=OLD_DATE)
        before = _row(eid)
        result = db_module.update_expense(
            eid, intruder, 99, "Bills", NEW_DATE, "Hacked")
        assert result is False
        assert _row(eid) == before

    def test_missing_id_returns_false(self, make_user):
        uid = make_user()
        before = _all_rows()
        assert db_module.update_expense(
            MISSING_ID, uid, 1, "Food", NEW_DATE, "x") is False
        assert _all_rows() == before

    def test_does_not_touch_other_rows(self, make_user, add_expense):
        uid = make_user()
        other = make_user()
        target = add_expense(uid, 10, date=OLD_DATE, description="Target")
        same_user = add_expense(uid, 20, date=OLD_DATE, description="Sibling")
        other_user = add_expense(other, 30, date=OLD_DATE, description="Other")
        before = {r[0]: r for r in _all_rows()}
        assert db_module.update_expense(
            target, uid, 1, "Bills", NEW_DATE, "Changed") is True
        after = {r[0]: r for r in _all_rows()}
        for eid in before:
            if eid != target:
                assert after[eid] == before[eid], f"row {eid} must not change"
        assert after[same_user] == before[same_user]
        assert after[other_user] == before[other_user]

    def test_sql_injection_values_stored_literally(self, make_user, add_expense):
        uid = make_user()
        eid = add_expense(uid, 10, date=OLD_DATE)
        payload = "x'; DROP TABLE expenses;--"
        assert db_module.update_expense(
            eid, uid, 10, "Food", OLD_DATE, payload) is True
        assert _row(eid)[5] == payload


# ------------------------------------------------------------ static hygiene

class TestStaticHygiene:
    def test_profile_css_has_no_hardcoded_hex_colours(self):
        css = (ROOT / "static" / "css" / "profile.css").read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), \
            "profile.css must use CSS variables, not hex colours"

    def test_template_has_no_style_tag_or_attribute(self):
        tpl = (ROOT / "templates" / "edit_expense.html").read_text(encoding="utf-8")
        assert not re.search(r"<style\b", tpl, re.I), "no <style> tags allowed"
        assert not re.search(r"\sstyle\s*=", tpl, re.I), "no style= attributes allowed"

    def test_template_extends_base(self):
        tpl = (ROOT / "templates" / "edit_expense.html").read_text(encoding="utf-8")
        assert re.search(r"{%\s*extends\s+[\"']base.html[\"']\s*%}", tpl)

    def test_template_does_not_use_safe_filter(self):
        tpl = (ROOT / "templates" / "edit_expense.html").read_text(encoding="utf-8")
        assert "|safe" not in tpl.replace(" ", ""), "never use |safe"
