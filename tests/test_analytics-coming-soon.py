import html
import re
from urllib.parse import urlparse

import pytest


def _as(client, user_id=1):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _text(response):
    return html.unescape(response.get_data(as_text=True))


def _path(response):
    return urlparse(response.headers["Location"]).path


def _analytics_anchors(body):
    """Return (opening_tag, inner_text) for every <a> whose href is /analytics."""
    anchors = re.findall(r"(<a\b[^>]*>)(.*?)</a>", body, re.DOTALL)
    return [
        (tag, inner)
        for tag, inner in anchors
        if re.search(r"""href=["']/analytics["']""", tag)
    ]


# ------------------------------------------------------------------ #
# Access                                                              #
# ------------------------------------------------------------------ #

def test_analytics_signed_out_redirects_to_login(client):
    response = client.get("/analytics")

    assert response.status_code == 302
    assert _path(response) == "/login"


def test_analytics_missing_user_redirects_and_clears_session(client):
    _as(client, 9999)
    response = client.get("/analytics")

    assert response.status_code == 302
    assert _path(response) == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess, "Stale user_id should be cleared"


def test_analytics_post_not_allowed(client):
    _as(client, 1)
    response = client.post("/analytics")

    assert response.status_code == 405


# ------------------------------------------------------------------ #
# Page content                                                        #
# ------------------------------------------------------------------ #

def test_analytics_signed_in_returns_200(client):
    _as(client, 1)
    response = client.get("/analytics")

    assert response.status_code == 200


@pytest.mark.parametrize(
    "expected",
    [
        "Advanced Analytics",
        "Coming soon",
        "We're working on powerful insights and visualizations",
        "We're crafting something special",
    ],
)
def test_analytics_page_contains_copy(client, expected):
    _as(client, 1)
    body = _text(client.get("/analytics"))

    assert expected in body, f"Expected {expected!r} on analytics page"


def test_analytics_page_links_analytics_stylesheet(client):
    _as(client, 1)
    body = _text(client.get("/analytics"))

    assert "css/analytics.css" in body
    assert re.search(r"<link\b[^>]*analytics\.css", body)


def test_analytics_page_title(client):
    _as(client, 1)
    body = _text(client.get("/analytics"))
    match = re.search(r"<title>(.*?)</title>", body, re.DOTALL)

    assert match, "Expected a <title> element"
    assert match.group(1).strip() == "Analytics — Spendly"


# ------------------------------------------------------------------ #
# Navbar                                                              #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("page", ["/analytics", "/profile", "/"])
def test_navbar_signed_in_has_analytics_link(client, page):
    _as(client, 1)
    response = client.get(page)
    assert response.status_code == 200
    anchors = _analytics_anchors(_text(response))

    assert anchors, f"Expected a link to /analytics on {page}"
    assert any(inner.strip() == "Analytics" or "Analytics" in inner
               for _, inner in anchors)


@pytest.mark.parametrize("page", ["/", "/login"])
def test_navbar_signed_out_has_no_analytics_link(client, page):
    response = client.get(page)
    assert response.status_code == 200

    assert _analytics_anchors(_text(response)) == [], (
        f"Signed-out visitors must not see an Analytics link on {page}"
    )


# ------------------------------------------------------------------ #
# Active state                                                        #
# ------------------------------------------------------------------ #

def test_analytics_link_is_active_on_analytics_page(client):
    _as(client, 1)
    anchors = _analytics_anchors(_text(client.get("/analytics")))

    assert anchors
    assert any(re.search(r"""aria-current=["']page["']""", tag)
               for tag, _ in anchors), "Analytics link should be aria-current"


def test_analytics_link_not_active_on_profile_page(client):
    _as(client, 1)
    anchors = _analytics_anchors(_text(client.get("/profile")))

    assert anchors
    for tag, _ in anchors:
        assert not re.search(r"""aria-current=["']page["']""", tag), (
            "Analytics link must not be active on /profile"
        )
