"""Tests for Step 06: date filter on the profile page."""
import html
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

AMOUNT_100 = "100.00"
EN_DASH = "–"


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _as(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _get(client, user_id, query=""):
    _as(client, user_id)
    response = client.get("/profile" + query)
    return response, html.unescape(response.get_data(as_text=True))


def _stat_value(body, label):
    match = re.search(
        rf"{label}.*?class=\"profile-stat-value\">([^<]+)<", body, re.DOTALL
    )
    assert match, f"stat '{label}' not found on page"
    return match.group(1).strip()


def _anchors(body):
    """Return list of (opening-tag attrs, inner text, href) for every <a>."""
    result = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", body, re.DOTALL):
        attrs, inner = m.group(1), m.group(2)
        href = re.search(r'href="([^"]*)"', attrs)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        result.append((attrs, text, href.group(1) if href else None))
    return result


def _preset_anchor(body, label):
    matches = [a for a in _anchors(body) if a[1] == label]
    assert matches, f"preset link '{label}' not found"
    return matches[0]


def _input_tag(body, name):
    m = re.search(rf'<input\b[^>]*name="{name}"[^>]*>', body)
    assert m, f"input {name} not found"
    return m.group(0)


def _has_alert(body):
    return 'role="alert"' in body


def _two_period_user(make_user, add_expense):
    uid = make_user("Filter User")
    add_expense(uid, 100, category="Food", date="2026-08-15",
                description="AugMarker")
    add_expense(uid, 50, category="Travel", date="2026-09-10",
                description="SepMarker")
    return uid


# ------------------------------------------------------------------ #
# Access                                                              #
# ------------------------------------------------------------------ #

def test_signed_out_filtered_profile_redirects_to_login(client):
    response = client.get("/profile?start=2026-09-01")

    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/login"


# ------------------------------------------------------------------ #
# Filtering behaviour                                                 #
# ------------------------------------------------------------------ #

class TestFiltering:
    def test_dod_example_range_counts_only_september_expense(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        response, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert response.status_code == 200
        assert _stat_value(body, "Total spent") == "₹50.00"
        assert _stat_value(body, "Transactions") == "1"
        assert "SepMarker" in body
        assert "AugMarker" not in body

    def test_no_params_shows_all_time_figures(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        _, body = _get(client, uid)

        assert _stat_value(body, "Total spent") == "₹150.00"
        assert _stat_value(body, "Transactions") == "2"
        assert "AugMarker" in body and "SepMarker" in body

    def test_expense_on_start_date_is_included(
            self, client, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 10, date="2026-09-01", description="OnStart")
        add_expense(uid, 20, date="2026-08-31", description="DayBefore")

        _, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert "OnStart" in body
        assert "DayBefore" not in body
        assert _stat_value(body, "Transactions") == "1"

    def test_expense_on_end_date_is_included(
            self, client, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 10, date="2026-09-30", description="OnEnd")
        add_expense(uid, 20, date="2026-10-01", description="DayAfter")

        _, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert "OnEnd" in body
        assert "DayAfter" not in body
        assert _stat_value(body, "Transactions") == "1"

    def test_start_only_includes_everything_from_start_onward(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        _, body = _get(client, uid, "?start=2026-09-01")

        assert _stat_value(body, "Total spent") == "₹50.00"
        assert "SepMarker" in body
        assert "AugMarker" not in body

    def test_end_only_includes_everything_up_to_end(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        _, body = _get(client, uid, "?end=2026-08-31")

        assert _stat_value(body, "Total spent") == "₹100.00"
        assert "AugMarker" in body
        assert "SepMarker" not in body

    def test_start_equals_end_returns_single_day(
            self, client, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 7, date="2026-09-10", description="TheDay")
        add_expense(uid, 8, date="2026-09-11", description="NextDay")
        add_expense(uid, 9, date="2026-09-09", description="PrevDay")

        response, body = _get(client, uid, "?start=2026-09-10&end=2026-09-10")

        assert response.status_code == 200
        assert not _has_alert(body)
        assert _stat_value(body, "Total spent") == "₹7.00"
        assert "TheDay" in body
        assert "NextDay" not in body and "PrevDay" not in body

    @pytest.mark.parametrize("query", [
        "?start=&end=",
        "?start=",
        "?end=",
        "?start=%20%20&end=%20",
    ])
    def test_blank_params_behave_as_all_time_without_error(
            self, client, make_user, add_expense, query):
        uid = _two_period_user(make_user, add_expense)

        response, body = _get(client, uid, query)

        assert response.status_code == 200
        assert not _has_alert(body), "blank params must not raise an error"
        assert _stat_value(body, "Total spent") == "₹150.00"

    def test_whitespace_padded_value_is_accepted(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        response, body = _get(
            client, uid, "?start=%202026-09-01%20&end=%202026-09-30%20")

        assert response.status_code == 200
        assert not _has_alert(body)
        assert _stat_value(body, "Total spent") == "₹50.00"

    def test_empty_period_shows_zero_figures_and_empty_state(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        response, body = _get(client, uid, "?start=2025-01-01&end=2025-01-31")

        assert response.status_code == 200
        assert _stat_value(body, "Total spent") == "₹0.00"
        assert _stat_value(body, "Transactions") == "0"
        assert "No expenses in this period." in body
        assert "No spending in this period." in body
        assert "No expenses yet." not in body
        idx = body.index("No expenses in this period.")
        assert 'href="/profile"' in body[idx:], \
            "expected a clear-filter link to /profile after the empty state"

    def test_unfiltered_empty_user_keeps_original_empty_state(
            self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid)

        assert "No expenses yet." in body
        assert "No expenses in this period." not in body

    def test_other_users_expenses_are_not_counted(
            self, client, make_user, add_expense):
        me = make_user("Me")
        other = make_user("Other")
        add_expense(me, 10, date="2026-09-05", description="MineOnly")
        add_expense(other, 999, date="2026-09-05", description="TheirsOnly")

        _, body = _get(client, me, "?start=2026-09-01&end=2026-09-30")

        assert _stat_value(body, "Total spent") == "₹10.00"
        assert _stat_value(body, "Transactions") == "1"
        assert "MineOnly" in body
        assert "TheirsOnly" not in body

    def test_category_breakdown_and_top_category_reflect_range_only(
            self, client, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 500, category="Rent", date="2026-08-01")
        add_expense(uid, 30, category="Food", date="2026-09-02")
        add_expense(uid, 10, category="Travel", date="2026-09-03")

        _, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert _stat_value(body, "Top category") == "Food"
        assert "Rent" not in body.split("Top category", 1)[1]

    def test_recent_transactions_limited_to_ten_within_range(
            self, client, make_user, add_expense):
        uid = make_user()
        for day in range(1, 16):
            add_expense(uid, 1, date=f"2026-09-{day:02d}",
                        description=f"Row{day:02d}X")
        add_expense(uid, 1, date="2026-08-20", description="OutsideRow")

        _, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert _stat_value(body, "Transactions") == "15"
        shown = re.findall(r"Row\d\dX", body)
        assert len(set(shown)) == 10
        assert "OutsideRow" not in body
        # the most recent ten are shown
        assert "Row15X" in body and "Row06X" in body
        assert "Row05X" not in body


# ------------------------------------------------------------------ #
# Invalid input                                                       #
# ------------------------------------------------------------------ #

class TestInvalidInput:
    @pytest.mark.parametrize("bad", [
        "not-a-date", "20260901", "2026-02-30", "2026-9-1",
    ])
    @pytest.mark.parametrize("param", ["start", "end"])
    def test_malformed_date_returns_200_with_error_and_all_time(
            self, client, make_user, add_expense, param, bad):
        uid = _two_period_user(make_user, add_expense)

        response, body = _get(client, uid, f"?{param}={bad}")

        assert response.status_code == 200
        assert _has_alert(body), "expected an error element with role=alert"
        assert _stat_value(body, "Total spent") == "₹150.00"
        assert _stat_value(body, "Transactions") == "2"
        assert f'value="{bad}"' not in body, "bad value must not be re-filled"

    def test_malformed_start_ignores_valid_end_too(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        response, body = _get(client, uid, "?start=nope&end=2026-08-31")

        assert response.status_code == 200
        assert _has_alert(body)
        assert _stat_value(body, "Total spent") == "₹150.00"

    def test_reversed_range_returns_200_with_error_and_all_time(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        response, body = _get(client, uid, "?start=2026-09-30&end=2026-09-01")

        assert response.status_code == 200
        assert _has_alert(body)
        assert _stat_value(body, "Total spent") == "₹150.00"
        assert _stat_value(body, "Transactions") == "2"
        assert 'value="2026-09-30"' not in body
        assert 'value="2026-09-01"' not in body

    def test_valid_filter_shows_no_error(
            self, client, make_user, add_expense):
        uid = _two_period_user(make_user, add_expense)

        _, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert not _has_alert(body)

    def test_xss_payload_in_start_is_not_echoed_raw(
            self, client, make_user):
        uid = make_user()
        payload = "<script>alert(1)</script>"

        _as(client, uid)
        response = client.get("/profile?start=" + payload)
        raw = response.get_data(as_text=True)

        assert response.status_code == 200
        assert payload not in raw
        assert "<script>alert(1)" not in raw


# ------------------------------------------------------------------ #
# Template: filter bar, presets, labels                               #
# ------------------------------------------------------------------ #

class TestFilterBar:
    def test_all_time_preset_is_active_when_no_filter(
            self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid)

        attrs, _, _ = _preset_anchor(body, "All time")
        assert 'aria-current="true"' in attrs
        assert body.count('aria-current="true"') >= 1

    def test_preset_links_match_date_presets_for_today(
            self, client, make_user):
        from app import _date_presets

        uid = make_user()
        _, body = _get(client, uid)

        for preset in _date_presets(date.today()):
            _, _, href = _preset_anchor(body, preset["label"])
            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            assert parsed.path == "/profile", preset["label"]
            assert query.get("start", [None])[0] == preset["start"], \
                preset["label"]
            assert query.get("end", [None])[0] == preset["end"], \
                preset["label"]

    def test_this_month_preset_url_activates_this_month_only(
            self, client, make_user):
        from app import _date_presets

        uid = make_user()
        this_month = _date_presets(date.today())[0]
        query = f"?start={this_month['start']}&end={this_month['end']}"

        response, body = _get(client, uid, query)

        assert response.status_code == 200
        attrs, _, _ = _preset_anchor(body, "This month")
        assert 'aria-current="true"' in attrs
        attrs_all, _, _ = _preset_anchor(body, "All time")
        assert 'aria-current' not in attrs_all

    def test_custom_range_has_no_active_preset(self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid, "?start=2001-03-04&end=2001-03-05")

        for label in ("This month", "Last 30 days", "This year", "All time"):
            attrs, _, _ = _preset_anchor(body, label)
            assert "aria-current" not in attrs, label

    def test_inputs_prefilled_after_valid_filter(self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert 'value="2026-09-01"' in _input_tag(body, "start")
        assert 'value="2026-09-30"' in _input_tag(body, "end")

    def test_inputs_are_date_type_with_labels_and_get_form(
            self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid)

        assert 'type="date"' in _input_tag(body, "start")
        assert 'type="date"' in _input_tag(body, "end")
        assert re.search(r'<form\b[^>]*method="get"', body, re.I)
        assert len(re.findall(r"<label\b", body)) >= 2
        assert "Apply" in body and "Clear" in body

    def test_inputs_empty_without_filter(self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid)

        for name in ("start", "end"):
            tag = _input_tag(body, name)
            assert not re.search(r'value="[^"]+"', tag), tag

    def test_period_label_for_both_bounds_uses_en_dash(
            self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid, "?start=2026-09-01&end=2026-09-30")

        assert f"Showing 1 Sep 2026 {EN_DASH} 30 Sep 2026" in body

    def test_period_label_for_start_only(self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid, "?start=2026-09-01")

        assert "Since 1 Sep 2026" in body

    def test_period_label_for_end_only(self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid, "?end=2026-08-31")

        assert "Up to 31 Aug 2026" in body

    def test_no_period_label_without_filter(self, client, make_user):
        uid = make_user()

        _, body = _get(client, uid)

        assert "Showing " not in body
        assert "Since " not in body
        assert "Up to " not in body

    def test_user_info_unaffected_by_filter(self, client, make_user):
        uid = make_user("Zelda Hyrule", email="zelda@example.com")

        _, body = _get(client, uid, "?start=2001-01-01&end=2001-01-02")

        assert "Zelda Hyrule" in body
        assert "zelda@example.com" in body


# ------------------------------------------------------------------ #
# _parse_date_range                                                   #
# ------------------------------------------------------------------ #

class TestParseDateRange:
    def test_empty_args_returns_none_none_none(self):
        from app import _parse_date_range

        assert _parse_date_range({}) == (None, None, None)

    def test_valid_both_returns_canonical_strings(self):
        from app import _parse_date_range

        result = _parse_date_range({"start": "2026-09-01", "end": "2026-09-30"})

        assert result == ("2026-09-01", "2026-09-30", None)

    def test_start_only(self):
        from app import _parse_date_range

        assert _parse_date_range({"start": "2026-09-01"}) == \
            ("2026-09-01", None, None)

    def test_end_only(self):
        from app import _parse_date_range

        assert _parse_date_range({"end": "2026-09-30"}) == \
            (None, "2026-09-30", None)

    def test_equal_start_and_end_is_valid(self):
        from app import _parse_date_range

        assert _parse_date_range({"start": "2026-09-10", "end": "2026-09-10"}) \
            == ("2026-09-10", "2026-09-10", None)

    def test_whitespace_is_stripped(self):
        from app import _parse_date_range

        start, end, error = _parse_date_range(
            {"start": "  2026-09-01 ", "end": "\t2026-09-30\n"})

        assert (start, end, error) == ("2026-09-01", "2026-09-30", None)

    def test_blank_values_count_as_not_provided(self):
        from app import _parse_date_range

        assert _parse_date_range({"start": "   ", "end": ""}) == \
            (None, None, None)

    @pytest.mark.parametrize("bad", [
        "not-a-date", "20260901", "2026-02-30", "2026-9-1",
    ])
    def test_malformed_returns_error_and_no_dates(self, bad):
        from app import _parse_date_range

        start, end, error = _parse_date_range(
            {"start": bad, "end": "2026-09-30"})

        assert start is None and end is None
        assert isinstance(error, str) and error

    def test_malformed_end_returns_error(self):
        from app import _parse_date_range

        start, end, error = _parse_date_range({"end": "2026-13-01"})

        assert start is None and end is None
        assert isinstance(error, str) and error

    def test_reversed_range_returns_error(self):
        from app import _parse_date_range

        start, end, error = _parse_date_range(
            {"start": "2026-09-30", "end": "2026-09-01"})

        assert start is None and end is None
        assert isinstance(error, str) and error

    def test_leap_day_is_valid_only_in_leap_year(self):
        from app import _parse_date_range

        assert _parse_date_range({"start": "2024-02-29"})[2] is None
        assert _parse_date_range({"start": "2026-02-29"})[2] is not None


# ------------------------------------------------------------------ #
# _date_presets                                                       #
# ------------------------------------------------------------------ #

class TestDatePresets:
    def test_labels_and_order(self):
        from app import _date_presets

        presets = _date_presets(date(2026, 2, 15))

        assert [p["label"] for p in presets] == [
            "This month", "Last 30 days", "This year", "All time"]
        for p in presets:
            assert set(p) >= {"label", "start", "end"}

    def test_mid_february_non_leap(self):
        from app import _date_presets

        p = {x["label"]: x for x in _date_presets(date(2026, 2, 15))}

        assert (p["This month"]["start"], p["This month"]["end"]) == \
            ("2026-02-01", "2026-02-28")
        assert (p["Last 30 days"]["start"], p["Last 30 days"]["end"]) == \
            ("2026-01-17", "2026-02-15")
        assert (p["This year"]["start"], p["This year"]["end"]) == \
            ("2026-01-01", "2026-12-31")
        assert (p["All time"]["start"], p["All time"]["end"]) == (None, None)

    def test_mid_february_leap_year(self):
        from app import _date_presets

        p = {x["label"]: x for x in _date_presets(date(2024, 2, 15))}

        assert p["This month"]["end"] == "2024-02-29"
        assert p["Last 30 days"]["start"] == "2024-01-17"
        assert p["Last 30 days"]["end"] == "2024-02-15"

    def test_last_day_of_year(self):
        from app import _date_presets

        p = {x["label"]: x for x in _date_presets(date(2026, 12, 31))}

        assert (p["This month"]["start"], p["This month"]["end"]) == \
            ("2026-12-01", "2026-12-31")
        assert p["Last 30 days"]["start"] == "2026-12-02"
        assert p["Last 30 days"]["end"] == "2026-12-31"
        assert p["This year"]["end"] == "2026-12-31"

    def test_last_30_days_crosses_year_boundary(self):
        from app import _date_presets

        p = {x["label"]: x for x in _date_presets(date(2026, 1, 10))}

        assert p["Last 30 days"]["start"] == "2025-12-12"
        assert p["Last 30 days"]["end"] == "2026-01-10"

    def test_last_30_days_spans_exactly_30_days_inclusive(self):
        from app import _date_presets

        today = date(2026, 6, 20)
        p = {x["label"]: x for x in _date_presets(today)}

        start = date.fromisoformat(p["Last 30 days"]["start"])
        assert start == today - timedelta(days=29)

    def test_values_are_iso_strings(self):
        from app import _date_presets

        for p in _date_presets(date(2026, 9, 30)):
            for key in ("start", "end"):
                assert p[key] is None or (
                    isinstance(p[key], str)
                    and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p[key]))

    def test_this_month_and_last_30_days_coincide_on_30th_of_30_day_month(self):
        from app import _date_presets

        presets = _date_presets(date(2026, 9, 30))

        this_month, last_30 = presets[0], presets[1]
        assert this_month["label"] == "This month"
        assert last_30["label"] == "Last 30 days"
        assert (this_month["start"], this_month["end"]) == \
            (last_30["start"], last_30["end"]) == ("2026-09-01", "2026-09-30")


# ------------------------------------------------------------------ #
# Query helpers                                                       #
# ------------------------------------------------------------------ #

class TestQueryHelpers:
    def _seed(self, make_user, add_expense):
        uid = make_user()
        add_expense(uid, 100, category="Rent", date="2026-08-15",
                    description="Aug")
        add_expense(uid, 30, category="Food", date="2026-09-01",
                    description="SepFirst")
        add_expense(uid, 20, category="Travel", date="2026-09-30",
                    description="SepLast")
        add_expense(uid, 5, category="Food", date="2026-10-01",
                    description="Oct")
        return uid

    def test_summary_stats_with_range_is_inclusive(
            self, db_path, make_user, add_expense):
        from database.queries import get_summary_stats

        uid = self._seed(make_user, add_expense)

        stats = get_summary_stats(
            uid, start_date="2026-09-01", end_date="2026-09-30")

        assert stats["total_spent"] == 50.0
        assert stats["transaction_count"] == 2
        assert stats["top_category"] == "Food"

    def test_summary_stats_without_range_is_all_time(
            self, db_path, make_user, add_expense):
        from database.queries import get_summary_stats

        uid = self._seed(make_user, add_expense)

        stats = get_summary_stats(uid)

        assert stats["total_spent"] == 155.0
        assert stats["transaction_count"] == 4
        assert stats["top_category"] == "Rent"

    def test_summary_stats_start_only_and_end_only(
            self, db_path, make_user, add_expense):
        from database.queries import get_summary_stats

        uid = self._seed(make_user, add_expense)

        assert get_summary_stats(uid, start_date="2026-09-30")[
            "transaction_count"] == 2
        assert get_summary_stats(uid, end_date="2026-09-01")[
            "transaction_count"] == 2

    def test_summary_stats_empty_range(
            self, db_path, make_user, add_expense):
        from database.queries import get_summary_stats

        uid = self._seed(make_user, add_expense)

        stats = get_summary_stats(
            uid, start_date="2025-01-01", end_date="2025-01-31")

        assert stats["total_spent"] == 0
        assert stats["transaction_count"] == 0

    def test_recent_transactions_range_and_order(
            self, db_path, make_user, add_expense):
        from database.queries import get_recent_transactions

        uid = self._seed(make_user, add_expense)

        rows = get_recent_transactions(
            uid, start_date="2026-09-01", end_date="2026-09-30")

        assert [r["description"] for r in rows] == ["SepLast", "SepFirst"]

    def test_recent_transactions_positional_limit_still_works(
            self, db_path, make_user, add_expense):
        from database.queries import get_recent_transactions

        uid = self._seed(make_user, add_expense)

        rows = get_recent_transactions(uid, 2, start_date="2026-09-01")

        assert len(rows) == 2

    def test_recent_transactions_default_limit_is_ten_within_range(
            self, db_path, make_user, add_expense):
        from database.queries import get_recent_transactions

        uid = make_user()
        for day in range(1, 13):
            add_expense(uid, 1, date=f"2026-09-{day:02d}")
        add_expense(uid, 1, date="2026-08-01")

        rows = get_recent_transactions(
            uid, start_date="2026-09-01", end_date="2026-09-30")

        assert len(rows) == 10
        assert all(r["date"].startswith("2026-09") for r in rows)

    def test_category_breakdown_range_sums_to_100(
            self, db_path, make_user, add_expense):
        from database.queries import get_category_breakdown

        uid = self._seed(make_user, add_expense)

        rows = get_category_breakdown(
            uid, start_date="2026-09-01", end_date="2026-09-30")

        assert [r["name"] for r in rows] == ["Food", "Travel"]
        assert sum(r["pct"] for r in rows) == 100
        assert sum(r["amount"] for r in rows) == 50.0

    def test_category_breakdown_empty_range_is_empty_list(
            self, db_path, make_user, add_expense):
        from database.queries import get_category_breakdown

        uid = self._seed(make_user, add_expense)

        assert get_category_breakdown(
            uid, start_date="2025-01-01", end_date="2025-01-02") == []

    def test_helpers_are_user_scoped_with_range(
            self, db_path, make_user, add_expense):
        from database.queries import (
            get_category_breakdown, get_recent_transactions,
            get_summary_stats,
        )

        me = make_user("Me")
        other = make_user("Other")
        add_expense(me, 10, date="2026-09-05")
        add_expense(other, 500, date="2026-09-05")
        kw = {"start_date": "2026-09-01", "end_date": "2026-09-30"}

        assert get_summary_stats(me, **kw)["total_spent"] == 10.0
        assert len(get_recent_transactions(me, **kw)) == 1
        assert get_category_breakdown(me, **kw)[0]["amount"] == 10.0

    def test_sql_injection_in_date_bound_is_treated_as_data(
            self, db_path, make_user, add_expense):
        from database.queries import get_summary_stats

        uid = make_user()
        add_expense(uid, 10, date="2026-09-05")

        stats = get_summary_stats(uid, start_date="2026-01-01'; DROP TABLE expenses;--")

        assert stats["transaction_count"] in (0, 1)
        assert get_summary_stats(uid)["transaction_count"] == 1
