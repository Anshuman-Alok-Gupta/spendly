import os

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

    return render_template(
        "profile.html",
        user=user,
        stats=get_summary_stats(user_id),
        transactions=get_recent_transactions(user_id),
        categories=get_category_breakdown(user_id),
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
