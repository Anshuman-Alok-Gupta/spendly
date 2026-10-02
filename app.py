import calendar
import os
from datetime import date, datetime, timedelta

from flask import (
    Flask, flash, redirect, render_template, request, session, url_for
)

from database.db import authenticate_user, create_user, init_db, seed_db
from database.queries import (
    get_category_breakdown, get_recent_transactions, get_summary_stats,
    get_user_by_id,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _is_valid_email(email):
    """Exactly one '@', a non-empty local part, and a '.' in the domain."""
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    return bool(local) and "." in domain


def _validate_registration(name, email, password):
    """Return the first validation error message, or None if the form is valid."""
    if not name:
        return "Please enter your name."
    if not _is_valid_email(email):
        return "Please enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    return None


_DATE_FORMAT = "%Y-%m-%d"
_BAD_DATE_ERROR = (
    "Please use valid dates in YYYY-MM-DD format. Showing all time instead."
)
_RANGE_ORDER_ERROR = (
    "The start date must be on or before the end date. "
    "Showing all time instead."
)


def _parse_iso_date(value):
    """Return a canonical 'YYYY-MM-DD' string, or None if blank.

    Raises ValueError for anything strptime rejects or that isn't already
    canonical (strptime alone accepts '2026-9-1').
    """
    value = (value or "").strip()
    if not value:
        return None
    canonical = datetime.strptime(value, _DATE_FORMAT).date().isoformat()
    if canonical != value:
        raise ValueError(value)
    return canonical


def _parse_date_range(args):
    """Return (start, end, error) from query args.

    Bad input (malformed or reversed) yields (None, None, message).
    """
    try:
        start = _parse_iso_date(args.get("start"))
        end = _parse_iso_date(args.get("end"))
    except ValueError:
        return None, None, _BAD_DATE_ERROR
    # Canonical ISO strings sort in date order, so string comparison is safe.
    if start and end and start > end:
        return None, None, _RANGE_ORDER_ERROR
    return start, end, None


def _date_presets(today):
    """Return [{label, start, end}] quick ranges (ISO strings) for `today`."""
    last_day = calendar.monthrange(today.year, today.month)[1]
    return [
        {
            "label": "This month",
            "start": today.replace(day=1).isoformat(),
            "end": today.replace(day=last_day).isoformat(),
        },
        {
            "label": "Last 30 days",
            "start": (today - timedelta(days=29)).isoformat(),
            "end": today.isoformat(),
        },
        {
            "label": "This year",
            "start": date(today.year, 1, 1).isoformat(),
            "end": date(today.year, 12, 31).isoformat(),
        },
        {"label": "All time", "start": None, "end": None},
    ]


def _format_day(iso_date):
    """'2026-09-01' -> '1 Sep 2026' (no %-d: not portable to Windows)."""
    day = date.fromisoformat(iso_date)
    return f"{day.day} {day.strftime('%b %Y')}"


def _period_label(start, end):
    """Human label for an active range, or None when unfiltered."""
    if start and end:
        return f"Showing {_format_day(start)} – {_format_day(end)}"
    if start:
        return f"Since {_format_day(start)}"
    if end:
        return f"Up to {_format_day(end)}"
    return None


def _date_filter_context(start, end, error, presets):
    """Template state for the filter bar; first exact preset match is active."""
    active = next(
        (
            p["label"] for p in presets
            if p["start"] == start and p["end"] == end
        ),
        None,
    )
    return {
        "start": start,
        "end": end,
        "error": error,
        "active": active,
        "label": _period_label(start, end),
        "is_active": start is not None or end is not None,
    }


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    error = _validate_registration(name, email, password)
    if error is None and create_user(name, email, password) is None:
        error = "An account with that email already exists."

    if error:
        return render_template(
            "register.html", error=error, name=name, email=email
        ), 400

    flash("Account created — please sign in.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("landing"))
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    user = authenticate_user(email, password) if email and password else None
    if user is None:
        return render_template(
            "login.html", error="Invalid email or password.", email=email
        ), 401

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("landing"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/profile")
def profile():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    user = get_user_by_id(user_id)
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    start, end, error = _parse_date_range(request.args)
    presets = _date_presets(date.today())

    return render_template(
        "profile.html",
        user=user,
        stats=get_summary_stats(user_id, start_date=start, end_date=end),
        transactions=get_recent_transactions(
            user_id, start_date=start, end_date=end
        ),
        categories=get_category_breakdown(
            user_id, start_date=start, end_date=end
        ),
        presets=presets,
        date_filter=_date_filter_context(start, end, error, presets),
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
