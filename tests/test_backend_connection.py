import html
import re
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

import pytest

import database.db as db_module
from database.queries import (
    NO_VALUE, _allocate_pct, get_category_breakdown, get_recent_transactions,
    get_summary_stats, get_user_by_id,
)

SEED_USER_ID = 1
DEMO = {"email": "demo@spendly.com", "password": "demo123"}


# ------------------------------------------------------------------ #
# get_user_by_id                                                     #
# ------------------------------------------------------------------ #

def _set_created_at(user_id, value):
    conn = db_module.get_db()
    try:
        conn.execute("UPDATE users SET created_at = ? WHERE id = ?", (value, user_id))
        conn.commit()
    finally:
        conn.close()


def test_get_user_by_id_returns_profile_fields(db_path):
    _set_created_at(1, "2026-01-15 09:30:00")

    assert get_user_by_id(1) == {
        "name": "Demo User",
        "email": "demo@spendly.com",
        "member_since": "January 2026",
    }


def test_get_user_by_id_unknown_returns_none(db_path):
    assert get_user_by_id(9999) is None


def test_get_user_by_id_bad_created_at(db_path):
    _set_created_at(1, "not a date")
    assert get_user_by_id(1)["member_since"] == ""

    _set_created_at(1, None)
    assert get_user_by_id(1)["member_since"] == ""


def test_get_user_by_id_never_exposes_password(db_path):
    assert "password_hash" not in get_user_by_id(1)


# ------------------------------------------------------------------ #
# get_recent_transactions                                            #
# ------------------------------------------------------------------ #

def test_rows_come_back_newest_first(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 1.00, date="2026-09-03", description="third")
    add_expense(user_id, 2.00, date="2026-09-20", description="twentieth")
    add_expense(user_id, 3.00, date="2026-09-10", description="tenth")

    result = get_recent_transactions(user_id)

    assert [r["date"] for r in result] == [
        "2026-09-20", "2026-09-10", "2026-09-03",
    ]


def test_same_date_later_inserted_row_comes_first(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 1.00, date="2026-09-05", description="first")
    add_expense(user_id, 2.00, date="2026-09-05", description="second")

    result = get_recent_transactions(user_id)

    assert [r["description"] for r in result] == ["second", "first"]


def test_row_shape_and_types(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 12, category="Bills", date="2026-09-07",
                description="Water")

    (row,) = get_recent_transactions(user_id)

    assert set(row) == {"id", "date", "description", "category", "amount"}
    assert isinstance(row["amount"], float)
    assert row["amount"] == 12.0
    assert date.fromisoformat(row["date"]) == date(2026, 9, 7)
    assert row["category"] == "Bills"
    assert row["description"] == "Water"


def test_default_limit_returns_ten_newest(make_user, add_expense):
    user_id = make_user()
    for day in range(1, 13):
        add_expense(user_id, day, date=f"2026-09-{day:02d}",
                    description=f"day {day}")

    result = get_recent_transactions(user_id)

    assert len(result) == 10
    assert result[0]["date"] == "2026-09-12"
    assert result[-1]["date"] == "2026-09-03"


def test_explicit_limit(make_user, add_expense):
    user_id = make_user()
    for day in range(1, 13):
        add_expense(user_id, day, date=f"2026-09-{day:02d}")

    result = get_recent_transactions(user_id, limit=3)

    assert [r["date"] for r in result] == [
        "2026-09-12", "2026-09-11", "2026-09-10",
    ]


def test_zero_limit_returns_empty(make_user, add_expense):
    user_id = make_user()
    for day in range(1, 13):
        add_expense(user_id, day, date=f"2026-09-{day:02d}")

    assert get_recent_transactions(user_id, limit=0) == []


def test_negative_limit_returns_empty(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 5)

    assert get_recent_transactions(user_id, limit=-1) == []


def test_missing_description_uses_placeholder(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 1.00, date="2026-09-01", description=None)
    add_expense(user_id, 2.00, date="2026-09-02", description="")

    result = get_recent_transactions(user_id)

    assert [r["description"] for r in result] == [NO_VALUE, NO_VALUE]
    assert NO_VALUE == "—"


def test_user_with_no_expenses_returns_empty(make_user):
    user_id = make_user()

    assert get_recent_transactions(user_id) == []


def test_unknown_user_returns_empty(db_path):
    assert get_recent_transactions(9999) == []


def test_seed_user_transactions(db_path):
    result = get_recent_transactions(1)

    assert len(result) == 8
    assert result[0]["description"] == "Weekly groceries"
    assert result[-1]["description"] == "Lunch at cafe"


def test_other_users_rows_never_appear(make_user, add_expense):
    alice = make_user(name="Alice")
    bob = make_user(name="Bob")
    add_expense(alice, 10.00, description="alice row")
    add_expense(bob, 20.00, description="bob row")

    alice_rows = get_recent_transactions(alice)
    bob_rows = get_recent_transactions(bob)

    assert [r["description"] for r in alice_rows] == ["alice row"]
    assert [r["description"] for r in bob_rows] == ["bob row"]
    assert all(r["description"] != "Weekly groceries" for r in alice_rows)


# ------------------------------------------------------------------ #
# get_summary_stats                                                  #
# ------------------------------------------------------------------ #

def test_seed_user_summary(db_path):
    assert get_summary_stats(1) == {
        "total_spent": 330.89,
        "transaction_count": 8,
        "top_category": "Bills",
    }


def test_user_with_no_expenses(make_user):
    user_id = make_user(name="Empty")
    stats = get_summary_stats(user_id)
    assert stats == {
        "total_spent": 0.0,
        "transaction_count": 0,
        "top_category": NO_VALUE,
    }
    assert stats["top_category"] == "—"
    assert isinstance(stats["total_spent"], float)


def test_float_total_is_rounded(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 0.1)
    add_expense(user_id, 0.2)
    assert get_summary_stats(user_id)["total_spent"] == 0.3


def test_top_category_uses_summed_total(make_user, add_expense):
    user_id = make_user()
    for _ in range(3):
        add_expense(user_id, 20, category="Food")
    add_expense(user_id, 50, category="Bills")
    stats = get_summary_stats(user_id)
    assert stats["top_category"] == "Food"
    assert stats["total_spent"] == 110.0
    assert stats["transaction_count"] == 4


def test_top_category_tie_breaks_alphabetically(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 10, category="Food")
    add_expense(user_id, 10, category="Bills")
    assert get_summary_stats(user_id)["top_category"] == "Bills"


def test_user_isolation(make_user, add_expense):
    first = make_user()
    second = make_user()
    add_expense(first, 5, category="Transport")
    add_expense(second, 500, category="Shopping")
    add_expense(second, 7, category="Shopping")
    assert get_summary_stats(first) == {
        "total_spent": 5.0,
        "transaction_count": 1,
        "top_category": "Transport",
    }


# ------------------------------------------------------------------ #
# get_category_breakdown                                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "amounts, expected",
    [
        ([], []),
        ([5], [100]),
        ([1, 1, 1], [34, 33, 33]),
        ([47.5, 17.5, 17.5, 17.5], [46, 18, 18, 18]),
        ([2, 1], [67, 33]),
    ],
)
def test_allocate_pct(amounts, expected):
    result = _allocate_pct(amounts)
    assert result == expected
    if amounts:
        assert sum(result) == 100


def test_seed_user_breakdown(db_path):
    breakdown = get_category_breakdown(SEED_USER_ID)
    assert [c["name"] for c in breakdown] == [
        "Bills", "Shopping", "Food", "Transport",
        "Health", "Entertainment", "Other",
    ]
    assert [c["amount"] for c in breakdown] == [
        120.0, 60.25, 50.9, 45.0, 30.0, 15.99, 8.75,
    ]
    assert [c["pct"] for c in breakdown] == [36, 18, 15, 14, 9, 5, 3]
    assert sum(c["pct"] for c in breakdown) == 100


def test_equal_categories_tie_break_alphabetical(make_user, add_expense):
    user_id = make_user()
    for category in ("Food", "Bills", "Other"):
        add_expense(user_id, 10, category=category)

    breakdown = get_category_breakdown(user_id)
    assert [(c["name"], c["pct"]) for c in breakdown] == [
        ("Bills", 34), ("Food", 33), ("Other", 33),
    ]


def test_breakdown_item_shape(db_path):
    breakdown = get_category_breakdown(SEED_USER_ID)
    assert breakdown
    for item in breakdown:
        assert set(item) == {"name", "amount", "pct"}
        assert isinstance(item["pct"], int)
        assert isinstance(item["amount"], float)


def test_empty_user_returns_empty_list(make_user):
    user_id = make_user()
    assert get_category_breakdown(user_id) == []


def test_breakdown_is_isolated_per_user(make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 99.99, category="Health")

    breakdown = get_category_breakdown(user_id)
    assert breakdown == [{"name": "Health", "amount": 99.99, "pct": 100}]

    seed_names = {c["name"] for c in get_category_breakdown(SEED_USER_ID)}
    assert len(seed_names) == 7
    seed_health = next(
        c for c in get_category_breakdown(SEED_USER_ID) if c["name"] == "Health"
    )
    assert seed_health["amount"] == 30.0


# ------------------------------------------------------------------ #
# GET /profile                                                       #
# ------------------------------------------------------------------ #

def _login(client, email=DEMO["email"], password=DEMO["password"]):
    return client.post("/login", data={"email": email, "password": password})


def _as(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _page(client):
    return html.unescape(client.get("/profile").get_data(as_text=True))


def _stat_value(body, label):
    match = re.search(
        rf"{label}.*?class=\"profile-stat-value\">([^<]+)<", body, re.DOTALL
    )
    return match.group(1).strip()


def test_profile_signed_out_redirects(client):
    response = client.get("/profile")

    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/login"


def test_profile_seed_user_live_data(client):
    _login(client)
    response = client.get("/profile")
    body = html.unescape(response.get_data(as_text=True))
    tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.DOTALL).group(1)
    names = re.findall(r'class="profile-cat-name">([^<]+)<', body)
    pcts = re.findall(r'class="profile-cat-percent">(\d+)%<', body)

    assert response.status_code == 200
    assert "Demo User" in body
    assert "demo@spendly.com" in body
    assert "you@example.com" not in body
    assert "₹" in body and "£" not in body
    assert _stat_value(body, "Total spent") == "₹330.89"
    assert _stat_value(body, "Transactions") == "8"
    assert _stat_value(body, "Top category") == "Bills"
    assert len(re.findall(r"<tr>", tbody)) == 8
    assert sorted(names) == sorted(db_module.CATEGORIES)
    assert sum(int(p) for p in pcts) == 100


def test_profile_lists_newest_first(client, make_user, add_expense):
    user_id = make_user()
    add_expense(user_id, 1, date="2026-09-03", description="Oldest")
    add_expense(user_id, 2, date="2026-09-20", description="Newest")
    add_expense(user_id, 3, date="2026-09-10", description="Middle")
    _as(client, user_id)
    body = _page(client)

    assert re.findall(r'<time datetime="([^"]+)"', body) == [
        "2026-09-20", "2026-09-10", "2026-09-03",
    ]
    assert body.index("Newest") < body.index("Middle") < body.index("Oldest")


def test_profile_new_user_empty_state(client):
    client.post("/register", data={
        "name": "Fresh User", "email": "fresh@example.com",
        "password": "password123",
    })
    _login(client, "fresh@example.com", "password123")
    body = _page(client)

    assert "Fresh User" in body and "fresh@example.com" in body
    assert _stat_value(body, "Total spent") == "₹0.00"
    assert _stat_value(body, "Transactions") == "0"
    assert _stat_value(body, "Top category") == "—"
    assert "No expenses yet." in body
    assert "No spending to break down yet." in body
    assert "<table" not in body


def test_profile_users_are_isolated(client, make_user, add_expense):
    other = make_user(name="Other Person")
    add_expense(other, 999.99, category="Other", description="Private thing")

    _as(client, SEED_USER_ID)
    demo_body = _page(client)
    _as(client, other)
    other_body = _page(client)

    assert "999.99" not in demo_body and "Private thing" not in demo_body
    assert _stat_value(other_body, "Total spent") == "₹999.99"
    assert _stat_value(other_body, "Transactions") == "1"
    assert "Electricity bill" not in other_body


def test_profile_stale_session_clears_and_redirects(client):
    _as(client, 9999)
    response = client.get("/profile")

    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    assert client.get("/login").status_code == 200


def test_stats_and_breakdown_agree(db_path):
    stats = get_summary_stats(SEED_USER_ID)
    breakdown = get_category_breakdown(SEED_USER_ID)

    assert Decimal(str(stats["total_spent"])) == sum(
        Decimal(str(c["amount"])) for c in breakdown
    )
    assert stats["top_category"] == breakdown[0]["name"]
