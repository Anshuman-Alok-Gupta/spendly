import html
import inspect
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import pytest

import database.db as db_module

ROOT = Path(__file__).resolve().parents[1]
PROFILE_CSS = ROOT / "static" / "css" / "profile.css"
PROFILE_TEMPLATE = ROOT / "templates" / "profile.html"
MAIN_JS = ROOT / "static" / "js" / "main.js"

DEMO = {"email": "demo@spendly.com", "password": "demo123"}
AMOUNT = r"₹\d+\.\d{2}"


def _login(client, **overrides):
    return client.post("/login", data={**DEMO, **overrides})


def _as(client, name="Demo User"):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_name"] = name


def _raw(response):
    return response.get_data(as_text=True)


def _text(response):
    return html.unescape(_raw(response))


def _path(response):
    return urlparse(response.headers["Location"]).path


def _profile(client, name="Demo User"):
    _as(client, name)
    return _raw(client.get("/profile"))


def _stat_value(body, label):
    match = re.search(
        rf"{label}.*?class=\"profile-stat-value\">([^<]+)<", body, re.DOTALL
    )
    return match.group(1).strip()


# ------------------------------------------------------------------ #
# Access                                                              #
# ------------------------------------------------------------------ #

def test_profile_signed_out_redirects_to_login(client):
    response = client.get("/profile")

    assert response.status_code == 302
    assert _path(response) == "/login"


def test_profile_signed_in_returns_200(client):
    _login(client)
    response = client.get("/profile")

    assert response.status_code == 200


def test_profile_not_placeholder(client):
    _as(client)

    assert "coming in Step 4" not in _text(client.get("/profile"))


def test_profile_title(client):
    _as(client)

    assert "<title>Profile — Spendly</title>" in _text(client.get("/profile"))


# ------------------------------------------------------------------ #
# User card                                                           #
# ------------------------------------------------------------------ #

def test_profile_shows_name_and_initials(client):
    body = _profile(client)

    assert "Demo User" in body
    assert re.search(r'class="profile-avatar"[^>]*>\s*DU\s*<', body)


@pytest.mark.parametrize(
    "name,initials",
    [("Mary Jane Watson", "MW"), ("anshuman", "A"), ("", "?")],
)
def test_initials_derivation(client, name, initials):
    body = _profile(client, name)

    assert re.search(
        rf'class="profile-avatar"[^>]*>\s*{re.escape(initials)}\s*<', body
    )


def test_profile_shows_email_and_member_since(client):
    body = _profile(client)

    assert re.search(r"profile-meta.*?[\w.+-]+@[\w-]+\.[\w.]+", body, re.DOTALL)
    assert "Member since" in body


def test_user_name_is_escaped(client):
    body = _profile(client, "<script>x</script>")

    assert "&lt;script&gt;x&lt;/script&gt;" in body
    assert "<script>x</script>" not in body


def test_no_password_hash_on_page(client):
    _login(client)
    body = _raw(client.get("/profile"))
    conn = db_module.get_db()
    try:
        password_hash = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", (DEMO["email"],)
        ).fetchone()["password_hash"]
    finally:
        conn.close()

    assert password_hash not in body
    assert "demo123" not in body


# ------------------------------------------------------------------ #
# Stats, table and categories                                         #
# ------------------------------------------------------------------ #

def test_stat_cards(client):
    body = _profile(client)

    for label in ("Total spent", "Transactions", "Top category"):
        assert label in body
    assert re.fullmatch(AMOUNT, _stat_value(body, "Total spent"))
    assert re.fullmatch(r"\d+", _stat_value(body, "Transactions"))


def test_transactions_table(client):
    body = _profile(client)
    tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.DOTALL).group(1)
    amounts = re.findall(r'<td class="profile-num">([^<]+)</td>', tbody)

    for heading in ("Date", "Description", "Category", "Amount"):
        assert re.search(rf'<th scope="col"[^>]*>\s*{heading}\s*</th>', body)
    assert len(re.findall(r"<tr>", tbody)) == 5
    assert len(amounts) == 5
    assert all(re.fullmatch(AMOUNT, amount) for amount in amounts)
    assert len(re.findall(r'class="profile-pill"', tbody)) == 5


def test_transactions_newest_first(client):
    dates = re.findall(r'<time datetime="([^"]+)"', _profile(client))

    assert dates
    assert dates == sorted(dates, reverse=True)


def test_category_bars(client):
    body = _profile(client)
    widths = [int(w) for w in re.findall(r'class="profile-bar" style="width: (\d+)%"', body)]
    names = re.findall(r'class="profile-cat-name">([^<]+)<', body)

    assert widths
    assert len(widths) == len(names)
    assert widths[0] == max(widths)
    assert names[0] == _stat_value(body, "Top category")


def test_total_equals_sum_of_categories(client):
    body = _profile(client)
    total = Decimal(_stat_value(body, "Total spent").lstrip("₹"))
    amounts = re.findall(r'class="profile-cat-amount">₹([\d.]+)<', body)

    assert amounts
    assert total == sum(Decimal(a) for a in amounts)


def test_add_expense_link(client):
    assert 'href="/expenses/add"' in _profile(client)


def test_empty_transactions_state(client, monkeypatch):
    import app as app_module

    original = app_module._placeholder_profile_context

    def empty_context(user_name):
        context = original(user_name)
        context["transactions"] = []
        return context

    monkeypatch.setattr(app_module, "_placeholder_profile_context", empty_context)
    body = _profile(client)

    assert "No expenses yet." in body
    assert "<table" not in body


# ------------------------------------------------------------------ #
# Navbar                                                              #
# ------------------------------------------------------------------ #

def test_navbar_name_links_to_profile(client):
    _login(client)
    body = _raw(client.get("/"))

    assert 'class="nav-user"' in body
    assert re.search(r'<a[^>]*href="/profile"[^>]*class="nav-user"[^>]*>\s*Demo User', body)


def test_navbar_marks_profile_as_current(client):
    body = _profile(client)

    assert re.search(r'class="nav-user"[^>]*aria-current="page"', body)


def test_navbar_signed_out_no_profile_link(client):
    assert 'href="/profile"' not in _raw(client.get("/"))


# ------------------------------------------------------------------ #
# Styles and icons                                                    #
# ------------------------------------------------------------------ #

def test_profile_uses_profile_css_no_style_tags(client):
    body = _profile(client)

    assert "css/profile.css" in body
    assert "<style" not in body
    assert "<style" not in PROFILE_TEMPLATE.read_text(encoding="utf-8")


def test_profile_css_has_no_hardcoded_colours():
    css = PROFILE_CSS.read_text(encoding="utf-8")

    assert re.search(r"#[0-9a-fA-F]{3,8}\b", css) is None
    assert "rgb(" not in css and "rgba(" not in css


def test_lucide_pinned_and_icons_decorative(client):
    body = _profile(client)
    icons = re.findall(r"<i data-lucide[^>]*>", body)

    assert "lucide@1.49.0" in body
    assert icons
    assert all('aria-hidden="true"' in icon for icon in icons)
    assert "window.lucide" in MAIN_JS.read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
# Project rules                                                       #
# ------------------------------------------------------------------ #

def test_profile_view_has_no_db_logic(client):
    sql = re.compile(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM)\b")
    source = inspect.getsource(client.application.view_functions["profile"])

    assert "get_db(" not in source
    assert sql.search(source) is None


def test_placeholder_context_contract(client):
    from app import _placeholder_profile_context

    context = _placeholder_profile_context("Demo User")
    user, stats = context["user"], context["stats"]
    transactions, categories = context["transactions"], context["categories"]

    assert set(context) == {"user", "stats", "transactions", "categories"}
    assert user["name"] == "Demo User"
    assert isinstance(user["email"], str) and isinstance(user["member_since"], str)
    assert isinstance(stats["total_spent"], float)
    assert isinstance(stats["transaction_count"], int)
    assert stats["transaction_count"] >= len(transactions)

    amounts = [c["amount"] for c in categories]
    assert amounts == sorted(amounts, reverse=True)
    assert all(c["name"] in db_module.CATEGORIES for c in categories)
    assert all(isinstance(c["percent"], int) and 0 <= c["percent"] <= 100 for c in categories)
    assert Decimal(str(stats["total_spent"])) == sum(Decimal(str(a)) for a in amounts)
    assert stats["top_category"] == categories[0]["name"]

    dates = [t["date"] for t in transactions]
    assert dates == sorted(dates, reverse=True)
    for tx in transactions:
        date.fromisoformat(tx["date"])
        assert tx["category"] in db_module.CATEGORIES
        assert isinstance(tx["amount"], float)
