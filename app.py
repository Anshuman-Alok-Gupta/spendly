import calendar
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import (
    Flask, abort, flash, redirect, render_template, request, session, url_for
)

from database.db import (
    CATEGORIES, authenticate_user, create_expense, create_user,
    delete_expense as db_delete_expense, init_db, seed_db, update_expense,
)
from database.queries import (
    get_category_breakdown, get_expense, get_recent_transactions,
    get_summary_stats, get_user_by_id,
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


_CENT = Decimal("0.01")
_MAX_AMOUNT = Decimal("10000000")
_MAX_DESCRIPTION = 200


def _parse_amount(raw):
    """Return (amount, error); amount is a 2dp float when valid."""
    raw = (raw or "").strip()
    if not raw:
        return None, "Please enter an amount."
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None, "Please enter a valid amount."
    # Must run before any comparison: comparing sNaN raises InvalidOperation.
    if not amount.is_finite():
        return None, "Please enter a valid amount."
    if amount <= 0:
        return None, "Amount must be greater than 0."
    if amount > _MAX_AMOUNT:
        return None, "Amount must be ₹10,000,000 or less."
    # Compare by value so '12.500' passes but '12.345' doesn't.
    if amount != amount.quantize(_CENT):
        return None, "Amount can have at most 2 decimal places."
    return float(amount.quantize(_CENT)), None


def _validate_expense(form, today):
    """Return (values, error) for the add- and edit-expense forms.

    `values` holds amount/category/date/description ready for
    create_expense() / update_expense(); only those keys are read, so a
    submitted user_id is ignored. `today` is a date, passed in so tests are deterministic.
    """
    amount, error = _parse_amount(form.get("amount"))
    if error:
        return None, error

    category = form.get("category", "")
    if category not in CATEGORIES:
        return None, "Please choose a valid category."

    try:
        day = _parse_iso_date(form.get("date"))
    except ValueError:
        day = None
    if day is None:
        return None, "Please enter a valid date (YYYY-MM-DD)."
    if day > today.isoformat():
        return None, "The date can't be in the future."

    description = form.get("description", "").strip()
    if len(description) > _MAX_DESCRIPTION:
        return None, "Description must be 200 characters or fewer."

    return {
        "amount": amount,
        "category": category,
        "date": day,
        "description": description or None,
    }, None


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


@app.route("/analytics")
def analytics():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if get_user_by_id(user_id) is None:
        session.clear()
        return redirect(url_for("login"))

    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if get_user_by_id(user_id) is None:
        session.clear()
        return redirect(url_for("login"))

    today = date.today()
    context = {"categories": CATEGORIES, "today": today.isoformat()}

    if request.method == "GET":
        return render_template(
            "add_expense.html", form={"date": context["today"]}, **context
        )

    values, error = _validate_expense(request.form, today)
    if error:
        return render_template(
            "add_expense.html", form=request.form, error=error, **context
        ), 400

    create_expense(user_id, **values)
    flash("Expense added.", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if get_user_by_id(user_id) is None:
        session.clear()
        return redirect(url_for("login"))

    # Missing and not-yours look identical, and both are checked before
    # validation so a bad POST can't reveal that someone else's id exists.
    expense = get_expense(id, user_id)
    if expense is None:
        abort(404)

    today = date.today()
    context = {
        "categories": CATEGORIES,
        "today": today.isoformat(),
        "expense_id": id,
    }

    if request.method == "GET":
        form = {
            "amount": "%.2f" % expense["amount"],
            "category": expense["category"],
            "date": expense["date"],
            "description": expense["description"] or "",
        }
        return render_template("edit_expense.html", form=form, **context)

    values, error = _validate_expense(request.form, today)
    if error:
        return render_template(
            "edit_expense.html", form=request.form, error=error, **context
        ), 400

    if not update_expense(id, user_id, **values):
        abort(404)
    flash("Expense updated.", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete", methods=["GET", "POST"])
def delete_expense(id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if get_user_by_id(user_id) is None:
        session.clear()
        return redirect(url_for("login"))

    # Missing and not-yours look identical, and both are checked before
    # anything is deleted. GET only confirms; only POST deletes.
    expense = get_expense(id, user_id)
    if expense is None:
        abort(404)

    if request.method == "GET":
        return render_template("delete_expense.html", expense=expense)

    if not db_delete_expense(id, user_id):
        abort(404)  # removed elsewhere between the lookup and the delete
    flash("Expense deleted.", "success")
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
