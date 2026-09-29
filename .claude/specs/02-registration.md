# Spec: Registration

## Overview
This step makes the existing sign-up page work. `GET /register` already renders `register.html`, but submitting the form goes nowhere because no route accepts `POST /register`. This step adds form handling to that route. It validates the name, email and password, hashes the password with werkzeug, and inserts a new row into the `users` table created in Step 1. On success the user is redirected to the sign-in page with a confirmation message. On failure the form is shown again with an error, and the values the user typed (except the password) are kept. Registration comes before login and logout (Step 3) because an account has to exist before anyone can sign in. This step does **not** start a session or log the user in.

## Depends on
- **Step 1: Database setup.** It provides `get_db()`, `init_db()` and the `users` table with its `UNIQUE` constraint on `email`.

## Routes
- `GET /register`: renders the empty registration form. Public. (Already exists; the route gains `POST` handling.)
- `POST /register`: validates the submitted form and creates the user. It redirects to `GET /login` on success and re-renders `register.html` with an error on failure. Public.

No other new routes.

## Database changes
No database changes. The `users` table in `database/db.py` already has `id`, `name`, `email` (`NOT NULL UNIQUE`), `password_hash` and `created_at`.

One new helper function is added to `database/db.py` (it is not a schema change):

- `create_user(name, email, password)`
  - Hashes `password` with `werkzeug.security.generate_password_hash`.
  - Runs `INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)`.
  - Commits and returns the new user's `id` (`cursor.lastrowid`).
  - Catches `sqlite3.IntegrityError` (duplicate email), rolls back and returns `None`.
  - Always closes the connection in a `finally` block, following the pattern used by `seed_db()`.

## Templates
- **Create:** none.
- **Modify:**
  - `templates/register.html`
    - Change the hardcoded `action="/register"` to `action="{{ url_for('register') }}"`.
    - Re-populate the `name` and `email` inputs from the submitted values on error (`value="{{ name or '' }}"`, `value="{{ email or '' }}"`). Never re-populate `password`.
    - Add `minlength="8"` to the password input so browsers match the server rule.
  - `templates/login.html`
    - Change the hardcoded `action="/login"` to `action="{{ url_for('login') }}"`.
    - Above the form inside `.auth-card`, render flashed messages with `get_flashed_messages(with_categories=true)`, using class `auth-success` for the `success` category.

## Files to change
- `app.py`
  - Import `request`, `redirect`, `url_for`, `flash` and `abort` from `flask`.
  - Import `create_user` from `database.db`.
  - Set `app.secret_key` from `os.environ.get("SECRET_KEY", "dev-secret-change-me")`. Flashing needs it, and Step 3 sessions will too.
  - Change `@app.route("/register")` to `methods=["GET", "POST"]` and implement POST handling as described in the rules below.
- `database/db.py`: add `create_user()`.
- `templates/register.html`: see Templates.
- `templates/login.html`: see Templates.
- `static/css/style.css`: add an `.auth-success` rule next to the existing `.auth-error`. It mirrors `.auth-error` but uses `var(--accent-light)` for the background and `var(--accent)` for the text and border.
- `CLAUDE.md`
  - In the routes table, mark `POST /register` as implemented.
  - Remove the stale warning "`database/db.py` is currently empty".

## Files to create
- `tests/__init__.py`: empty.
- `tests/conftest.py`
  - Provides a `client` fixture that monkeypatches `database.db.DB_PATH` to a file under `tmp_path`.
  - The fixture calls `init_db()`, sets `app.config["TESTING"] = True` and yields `app.test_client()`.
  - Tests never touch the real `expense_tracker.db`.
- `tests/test_registration.py`: pytest tests covering every item in the Definition of Done that can be automated.

## New dependencies
No new dependencies. `flask`, `werkzeug`, `pytest` and `pytest-flask` are already in `requirements.txt`, and `sqlite3` is in the standard library.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` through `get_db()` only.
- Parameterised queries only (`?` placeholders). Never build SQL with f-strings or string formatting.
- Passwords are hashed with werkzeug (`generate_password_hash`). The plain-text password is never stored, logged or re-rendered.
- Use CSS variables and never hardcode hex values in new CSS.
- All templates extend `base.html`.
- **No DB logic in routes.** The route calls `create_user()` and never calls `get_db()` or runs SQL directly. The route doesn't catch `sqlite3.IntegrityError` either, because `create_user()` handles that and returns `None`.
- **Validation (server-side, in the route, in this order).** Stop at the first failure.
  1. `name = request.form.get("name", "").strip()`: must be non-empty, otherwise the error is "Please enter your name."
  2. `email = request.form.get("email", "").strip().lower()`: must contain exactly one `@`, with a non-empty local part and a domain part that contains a `.`, otherwise the error is "Please enter a valid email address."
  3. `password = request.form.get("password", "")`: do **not** strip it. It must be at least 8 characters, otherwise the error is "Password must be at least 8 characters."
  4. If `create_user()` returns `None`, the error is "An account with that email already exists."
- On any validation error, re-render `register.html` with `error`, `name` and `email`, and return HTTP status **400**.
- On success, call `flash("Account created — please sign in.", "success")` and `redirect(url_for("login"))` (HTTP 302).
- Emails are stored lowercased and trimmed, so `Foo@Example.com` and `foo@example.com` count as the same account.
- Use `url_for()` for every internal link and form action, with no hardcoded paths.
- Do not implement `POST /login`, sessions, `/logout` or any other stub route. Those belong to Step 3 and later.
- The app stays on port 5001.

## Definition of done
- [ ] `GET /register` returns 200 and shows the form with Full name, Email address and Password fields.
- [ ] Submitting valid details (e.g. `Test User`, `test@example.com`, `password123`) redirects to `/login`, and the green message "Account created — please sign in." appears there.
- [ ] After a successful registration, `SELECT * FROM users WHERE email = 'test@example.com'` returns exactly one row. Its `password_hash` is not `password123` and starts with a werkzeug hash prefix (e.g. `scrypt:` or `pbkdf2:`).
- [ ] `check_password_hash(row["password_hash"], "password123")` returns `True`.
- [ ] Registering again with `test@example.com` shows "An account with that email already exists." with status 400, and no second row is created.
- [ ] Registering with `TEST@Example.com ` (different case plus a trailing space) is also rejected as a duplicate.
- [ ] Registering with `demo@spendly.com` (the seeded user) is rejected as a duplicate.
- [ ] Submitting a blank or whitespace-only name shows "Please enter your name." with status 400.
- [ ] Submitting `not-an-email` shows "Please enter a valid email address." with status 400.
- [ ] Submitting a 7-character password shows "Password must be at least 8 characters." with status 400.
- [ ] After any error, the Full name and Email inputs keep what the user typed, and the Password input is empty.
- [ ] The rendered `register.html` and `login.html` contain no hardcoded `action="/..."` paths.
- [ ] `app.py` contains no `get_db()` calls or SQL strings inside route functions.
- [ ] `pytest` passes, and the tests use a temporary database rather than `expense_tracker.db`.
- [ ] `python app.py` starts without errors on port 5001.
