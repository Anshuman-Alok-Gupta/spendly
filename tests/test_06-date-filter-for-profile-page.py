"""Tests for Step 06: date filter on the profile page (spec-driven)."""
import html as html_lib
import re
from datetime import date

import pytest

import database.db as db_module


# ------------------------------------------------------------------ helpers

def _login(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def _get(client, query=""):
    resp = client.get("/profile" + query)
    return resp, html_lib.unescape(resp.get_data(as_text=True))


def _counts():
    conn = db_module.get_db()
    try:
        return (
            conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        )
    finally:
        conn.close()


@pytest.fixture
def user(client, make_user, add_expense):
    """Fresh user with Aug 100 Food, Sep 10 50 Bills; signed in."""
    uid = make_user(name="Filter User")
    add_expense(uid, 100, category="Food", date="2026-08-15", description="AugFood")
    add_expense(uid, 50, category="Bills", date="2026-09-10", description="SepBills")
    _login(client, uid)
    return uid


# --------------------------------------------------- _parse_date_range unit

class TestParseDateRange:
    def test_no_params_returns_none_none_no_error(self):
        from app import _parse_date_range
        assert _parse_date_range({}) == (None, None, None)

    def test_both_valid_returns_canonical_iso(self):
        from app import _parse_date_range
        s, e, err = _parse_date_range({"start": "2026-09-01", "end": "2026-09-30"})
        assert (s, e, err) == ("2026-09-01", "2026-09-30", None)

    def test_only_start(self):
        from app import _parse_date_range
        assert _parse_date_range({"start": "2026-09-01"}) == ("2026-09-01", None, None)

    def test_only_end(self):
        from app import _parse_date_range
        assert _parse_date_range({"end": "2026-09-01"}) == (None, "2026-09-01", None)

    def test_same_day_start_and_end_is_valid(self):
        from app import _parse_date_range
        assert _parse_date_range({"start": "2026-09-01", "end": "2026-09-01"}) == (
            "2026-09-01", "2026-09-01", None)

    def test_blank_and_whitespace_values_count_as_not_provided(self):
        from app import _parse_date_range
        assert _parse_date_range({"start": "", "end": "   "}) == (None, None, None)

    def test_values_are_stripped(self):
        from app import _parse_date_range
        s, e, err = _parse_date_range({"start": "  2026-09-01 ", "end": " 2026-09-30"})
        assert (s, e, err) == ("2026-09-01", "2026-09-30", None)

    @pytest.mark.parametrize("bad", [
        "not-a-date", "2026-9-1", "20260901", "2026-02-30", "2026-13-01",
        "01-09-2026", "2026/09/01", "2026-09-01x", "'; DROP TABLE expenses;--",
    ])
    def test_malformed_start_returns_error_and_drops_both(self, bad):
        from app import _parse_date_range
        s, e, err = _parse_date_range({"start": bad, "end": "2026-09-30"})
        assert s is None and e is None, f"both should be ignored for {bad!r}"
        assert err, "an error message is expected"

    @pytest.mark.parametrize("bad", ["2026-9-1", "20260901", "nope"])
    def test_malformed_end_returns_error(self, bad):
        from app import _parse_date_range
        s, e, err = _parse_date_range({"start": "2026-09-01", "end": bad})
        assert (s, e) == (None, None)
        assert err

    def test_start_after_end_returns_error_and_drops_both(self):
        from app import _parse_date_range
        s, e, err = _parse_date_range({"start": "2026-09-30", "end": "2026-09-01"})
        assert (s, e) == (None, None)
        assert err


# ----------------------------------------------------- _date_presets unit

class TestDatePresets:
    def _by_label(self, today):
        from app import _date_presets
        return {p["label"]: p for p in _date_presets(today)}

    def test_presets_labels_and_order(self):
        from app import _date_presets
        labels = [p["label"] for p in _date_presets(date(2026, 9, 15))]
        assert labels == ["This month", "Last 30 days", "This year", "All time"]

    def test_this_month_spans_first_to_last_day(self):
        p = self._by_label(date(2026, 9, 15))["This month"]
        assert (p["start"], p["end"]) == ("2026-09-01", "2026-09-30")

    def test_this_month_february_non_leap(self):
        p = self._by_label(date(2026, 2, 10))["This month"]
        assert (p["start"], p["end"]) == ("2026-02-01", "2026-02-28")

    def test_this_month_february_leap_year(self):
        p = self._by_label(date(2028, 2, 10))["This month"]
        assert p["end"] == "2028-02-29"

    def test_last_30_days_is_today_minus_29_to_today(self):
        p = self._by_label(date(2026, 9, 30))["Last 30 days"]
        assert (p["start"], p["end"]) == ("2026-09-01", "2026-09-30")

    def test_last_30_days_crosses_month_boundary(self):
        p = self._by_label(date(2026, 3, 5))["Last 30 days"]
        assert (p["start"], p["end"]) == ("2026-02-04", "2026-03-05")

    def test_this_year_jan1_to_dec31(self):
        p = self._by_label(date(2026, 9, 15))["This year"]
        assert (p["start"], p["end"]) == ("2026-01-01", "2026-12-31")

    def test_all_time_is_none_none(self):
        p = self._by_label(date(2026, 9, 15))["All time"]
        assert (p["start"], p["end"]) == (None, None)

    def test_preset_values_are_iso_strings(self):
        from app import _date_presets
        for p in _date_presets(date(2026, 1, 31)):
            for key in ("start", "end"):
                assert p[key] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", p[key])


# ------------------------------------------------------- query layer

class TestQueryLayer:
    def test_summary_inclusive_bounds(self, make_user, add_expense):
        from database.queries import get_summary_stats
        uid = make_user()
        add_expense(uid, 10, date="2026-09-01")
        add_expense(uid, 20, date="2026-09-30")
        add_expense(uid, 99, date="2026-08-31")
        add_expense(uid, 99, date="2026-10-01")
        s = get_summary_stats(uid, start_date="2026-09-01", end_date="2026-09-30")
        assert s["total_spent"] == 30.0
        assert s["transaction_count"] == 2

    def test_summary_positional_call_is_all_time(self, make_user, add_expense):
        from database.queries import get_summary_stats
        uid = make_user()
        add_expense(uid, 10, date="2026-01-01")
        add_expense(uid, 20, date="2026-12-31")
        s = get_summary_stats(uid)
        assert s["total_spent"] == 30.0 and s["transaction_count"] == 2

    def test_summary_start_only_and_end_only(self, make_user, add_expense):
        from database.queries import get_summary_stats
        uid = make_user()
        add_expense(uid, 100, date="2026-08-15")
        add_expense(uid, 50, date="2026-09-10")
        assert get_summary_stats(uid, start_date="2026-09-01")["total_spent"] == 50.0
        assert get_summary_stats(uid, end_date="2026-08-31")["total_spent"] == 100.0

    def test_top_category_reflects_filtered_range_only(self, make_user, add_expense):
        from database.queries import get_summary_stats
        uid = make_user()
        add_expense(uid, 500, category="Rent", date="2026-08-01")
        add_expense(uid, 5, category="Food", date="2026-09-05")
        s = get_summary_stats(uid, start_date="2026-09-01", end_date="2026-09-30")
        assert s["top_category"] == "Food"

    def test_recent_transactions_filtered_and_limit_kept(self, make_user, add_expense):
        from database.queries import get_recent_transactions
        uid = make_user()
        for day in range(1, 16):
            add_expense(uid, 1, date=f"2026-09-{day:02d}")
        add_expense(uid, 1, date="2026-08-01")
        rows = get_recent_transactions(uid, start_date="2026-09-01",
                                       end_date="2026-09-30")
        assert len(rows) == 10, "limit=10 must still apply within the range"
        assert all(r["date"].startswith("2026-09") for r in rows)

    def test_category_breakdown_pct_sums_to_100_and_matches_total(
            self, make_user, add_expense):
        from database.queries import get_category_breakdown, get_summary_stats
        uid = make_user()
        add_expense(uid, 10, category="Food", date="2026-09-02")
        add_expense(uid, 10, category="Bills", date="2026-09-03")
        add_expense(uid, 10, category="Fun", date="2026-09-04")
        add_expense(uid, 777, category="Rent", date="2026-01-04")
        kw = dict(start_date="2026-09-01", end_date="2026-09-30")
        cats = get_category_breakdown(uid, **kw)
        assert sum(c["pct"] for c in cats) == 100
        assert "Rent" not in [c["name"] for c in cats]
        assert round(sum(c["amount"] for c in cats), 2) == \
            get_summary_stats(uid, **kw)["total_spent"]

    def test_empty_range_yields_zero_and_empty(self, make_user, add_expense):
        from database.queries import (get_category_breakdown,
                                      get_recent_transactions, get_summary_stats)
        uid = make_user()
        add_expense(uid, 10, date="2026-09-02")
        kw = dict(start_date="2030-01-01", end_date="2030-01-31")
        assert get_summary_stats(uid, **kw)["total_spent"] == 0
        assert get_summary_stats(uid, **kw)["transaction_count"] == 0
        assert get_recent_transactions(uid, **kw) == []
        assert get_category_breakdown(uid, **kw) == []


# ----------------------------------------------------------- route tests

class TestProfileFilterRoute:
    def test_no_params_shows_all_time(self, client, user):
        resp, body = _get(client)
        assert resp.status_code == 200
        assert "150.00" in body
        assert "AugFood" in body and "SepBills" in body

    def test_both_params_filter_total_count_and_rows(self, client, user):
        resp, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert resp.status_code == 200
        assert "₹50.00" in body
        assert "SepBills" in body
        assert "AugFood" not in body
        assert "150.00" not in body

    def test_inclusive_start_boundary(self, client, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 11, date="2026-09-01", description="OnStart")
        add_expense(uid, 22, date="2026-08-31", description="DayBefore")
        _login(client, uid)
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert "OnStart" in body and "DayBefore" not in body

    def test_inclusive_end_boundary(self, client, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 11, date="2026-09-30", description="OnEnd")
        add_expense(uid, 22, date="2026-10-01", description="DayAfter")
        _login(client, uid)
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert "OnEnd" in body and "DayAfter" not in body

    def test_start_only(self, client, user):
        resp, body = _get(client, "?start=2026-09-01")
        assert resp.status_code == 200
        assert "SepBills" in body and "AugFood" not in body

    def test_end_only(self, client, user):
        resp, body = _get(client, "?end=2026-08-31")
        assert resp.status_code == 200
        assert "AugFood" in body and "SepBills" not in body

    def test_top_category_reflects_filter(self, client, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 900, category="Rent", date="2026-08-01")
        add_expense(uid, 5, category="Groceries", date="2026-09-05")
        _login(client, uid)
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert "Groceries" in body
        assert "Rent" not in body

    def test_other_users_expenses_never_included(
            self, client, make_user, add_expense):
        a = make_user(name="Alice")
        b = make_user(name="Bob")
        add_expense(a, 10, date="2026-09-10", description="AliceItem")
        add_expense(b, 9999, date="2026-09-10", description="BobSecret")
        _login(client, a)
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert "AliceItem" in body
        assert "BobSecret" not in body
        assert "9,999" not in body and "9999" not in body

    def test_user_info_unaffected_by_filter(self, client, user):
        _, body = _get(client, "?start=2030-01-01&end=2030-01-31")
        assert "Filter User" in body

    def test_period_label_both(self, client, user):
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert "Showing 1 Sep 2026" in body and "30 Sep 2026" in body

    def test_period_label_start_only(self, client, user):
        _, body = _get(client, "?start=2026-09-01")
        assert "Since 1 Sep 2026" in body

    def test_period_label_end_only(self, client, user):
        _, body = _get(client, "?end=2026-09-30")
        assert "Up to 30 Sep 2026" in body

    def test_no_period_label_when_unfiltered(self, client, user):
        _, body = _get(client)
        assert "Showing " not in body and "Since " not in body \
            and "Up to " not in body

    def test_caption_does_not_claim_alltime_count(self, client, make_user, add_expense):
        uid = make_user()
        for d in ("2026-08-01", "2026-08-02", "2026-09-05"):
            add_expense(uid, 1, date=d)
        _login(client, uid)
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert "of 3 expenses" not in body


class TestFilterBarMarkup:
    def test_presets_inputs_apply_and_clear_present(self, client, user):
        _, body = _get(client)
        for label in ("This month", "Last 30 days", "This year", "All time"):
            assert label in body, f"preset {label} missing"
        assert 'type="date"' in body
        assert 'name="start"' in body and 'name="end"' in body
        assert "Apply" in body and "Clear" in body
        assert re.search(r'<form[^>]*method="get"', body, re.I)
        assert re.search(r'<form[^>]*action="/profile"', body)
        assert "<label" in body

    def test_inputs_have_visible_labels(self, client, user):
        _, body = _get(client)
        assert len(re.findall(r"<label\b", body)) >= 2

    def test_inputs_prefilled_with_valid_range(self, client, user):
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert re.search(r'name="start"[^>]*value="2026-09-01"|'
                         r'value="2026-09-01"[^>]*name="start"', body)
        assert re.search(r'name="end"[^>]*value="2026-09-30"|'
                         r'value="2026-09-30"[^>]*name="end"', body)

    def test_matching_preset_gets_aria_current(self, client, user):
        today = date.today()
        from app import _date_presets
        p = next(x for x in _date_presets(today) if x["label"] == "This month")
        _, body = _get(client, f"?start={p['start']}&end={p['end']}")
        assert 'aria-current="true"' in body
        assert body.count('aria-current="true"') == 1

    def test_all_time_preset_active_without_params(self, client, user):
        _, body = _get(client)
        assert body.count('aria-current="true"') == 1

    def test_custom_range_has_no_active_preset(self, client, user):
        _, body = _get(client, "?start=2026-09-02&end=2026-09-03")
        assert 'aria-current="true"' not in body

    def test_preset_links_use_start_end_params(self, client, user):
        from app import _date_presets
        p = next(x for x in _date_presets(date.today()) if x["label"] == "This year")
        _, body = _get(client)
        assert f"start={p['start']}" in body and f"end={p['end']}" in body

    def test_no_style_tags_in_profile(self, client, user):
        _, body = _get(client, "?start=2026-09-01")
        assert "<style" not in body.lower()

    def test_profile_css_has_no_hex_colours_outside_variables(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parent.parent / "static" / "css"
               / "profile.css").read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), \
            "profile.css must use CSS variables, not hex colours"


class TestInvalidFilters:
    @pytest.mark.parametrize("query", [
        "?start=not-a-date",
        "?end=garbage",
        "?start=2026-9-1",
        "?start=20260901",
        "?start=2026-02-30",
        "?start=2026-09-30&end=2026-09-01",
        "?start=%27%3B+DROP+TABLE+expenses%3B--",
    ])
    def test_invalid_returns_200_error_and_alltime(self, client, user, query):
        resp, body = _get(client, query)
        assert resp.status_code == 200
        assert 'role="alert"' in body, "inline error expected"
        assert "150.00" in body, "should fall back to all-time totals"
        assert "AugFood" in body and "SepBills" in body

    def test_invalid_does_not_redirect(self, client, user):
        resp = client.get("/profile?start=bad")
        assert resp.status_code == 200 and "Location" not in resp.headers

    def test_valid_filter_shows_no_error_alert(self, client, user):
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert 'role="alert"' not in body

    def test_no_params_shows_no_error_alert(self, client, user):
        _, body = _get(client)
        assert 'role="alert"' not in body

    def test_malicious_input_not_echoed_unescaped(self, client, user):
        payload = "<script>alert(1)</script>"
        resp = client.get("/profile", query_string={"start": payload})
        raw = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert payload not in raw

    def test_invalid_input_not_prefilled_in_inputs(self, client, user):
        _, body = _get(client, "?start=not-a-date")
        assert 'value="not-a-date"' not in body

    def test_sql_injection_does_not_alter_data(self, client, user):
        before = _counts()
        resp = client.get("/profile", query_string={
            "start": "2026-09-01' OR '1'='1", "end": "x'; DROP TABLE expenses;--"})
        assert resp.status_code == 200
        assert _counts() == before


class TestEmptyStates:
    def test_filter_with_no_matches(self, client, user):
        resp, body = _get(client, "?start=2030-01-01&end=2030-01-31")
        assert resp.status_code == 200
        assert "No expenses in this period." in body
        assert "No spending in this period." in body
        assert "₹0.00" in body
        assert "No expenses yet." not in body

    def test_empty_period_has_clear_link(self, client, user):
        _, body = _get(client, "?start=2030-01-01&end=2030-01-31")
        assert re.search(r'href="/profile"', body)

    def test_user_with_no_expenses_unfiltered_keeps_original_messages(
            self, client, make_user):
        uid = make_user()
        _login(client, uid)
        _, body = _get(client)
        assert "No expenses yet." in body
        assert "No spending to break down yet." in body
        assert "in this period" not in body

    def test_user_with_no_expenses_filtered_shows_period_messages(
            self, client, make_user):
        uid = make_user()
        _login(client, uid)
        _, body = _get(client, "?start=2026-09-01&end=2026-09-30")
        assert "No expenses in this period." in body
        assert "No spending in this period." in body


class TestAuthAndSideEffects:
    @pytest.mark.parametrize("query", [
        "", "?start=2026-09-01", "?start=2026-09-01&end=2026-09-30",
        "?start=bad",
    ])
    def test_signed_out_redirects_to_login(self, client, query):
        resp = client.get("/profile" + query)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_signed_out_does_not_leak_data(self, client, user):
        with client.session_transaction() as sess:
            sess.clear()
        resp = client.get("/profile?start=2026-09-01")
        assert resp.status_code == 302
        assert b"SepBills" not in resp.data

    @pytest.mark.parametrize("query", [
        "?start=2026-09-01&end=2026-09-30", "?start=bad",
        "?start=2030-01-01", "?end=2026-08-31",
    ])
    def test_get_with_filters_never_writes_to_db(self, client, user, query):
        before = _counts()
        resp = client.get("/profile" + query)
        assert resp.status_code == 200
        assert _counts() == before, "filtering must not change row counts"

    def test_filter_does_not_modify_expense_rows(self, client, user):
        def snapshot():
            conn = db_module.get_db()
            try:
                return [tuple(r) for r in conn.execute(
                    "SELECT * FROM expenses ORDER BY id").fetchall()]
            finally:
                conn.close()
        before = snapshot()
        client.get("/profile?start=2026-09-01&end=2026-09-30")
        assert snapshot() == before
