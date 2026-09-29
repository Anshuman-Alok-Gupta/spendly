# Spec: Login and Logout

## Overview
This step lets registered users sign in and out. `GET /login` already renders `login.html`, and the form already posts to `url_for('login')`, but the route only accepts `GET`, so submitting it returns 405. This step adds `POST /login` handling. It looks up the user by email, checks the password against the stored werkzeug hash, and on success stores the user's id and name in Flask's signed `session` cookie. It also replaces the `/logout` stub with a real route that clears the session. The navbar in `base.html` becomes session-aware: signed-out visitors see "Sign in" / "Get started", and signed-in users see their name and a "Sign out" link. Login comes after registration (Step 2) because an account must exist first. It comes before the profile page (Step 4) because every later page needs to know who the current user is.

## Depends on
- **Step 1: Database setup.** It provides `get_db()`, the `users` table and the seeded demo user (`demo@spendly.com` / `demo123`).
- **Step 2: Registration.** It provides `create_user()`, `app.secret_key`, the flash-message block in `login.html`, the `.auth-success` style and the `tests/conftest.py` fixtures.

## Routes
- `GET /login`: renders the sign-in form. Public. (Already exists; the route gains `POST` handling.) If the user is already signed in, it redirects to `url_for('landing')` instead.
- `POST /login`: validates credentials and starts a session. It redirects to `url_for('landing')` on success and re-renders `login.html` with an error on failure. Public.
- `GET /logout`: clears the session, flashes "You've been signed out." with category `success`, and redirects to `url_for('login')`. Public (it is safe to call when not signed in). This replaces the existing Step 3 stub.

No other new routes. `/profile` stays a stub until Step 4.

## Database changes
No database changes. The `users` table in `database/db.py` already has `id`, `name`, `email` (`NOT NULL UNIQUE`) and `password_hash`.

One new helper function is added to `database/db.py` (it is not a schema change):

- `authenticate_user(email, password)`
  - Runs `SELECT id, name, email, password_hash FROM users WHERE email = ?`.
  - If no row is found, returns `None`.
  - If a row is found, checks the password with `werkzeug.security.check_password_hash(row["password_hash"], password)`. Returns the row (`sqlite3.Row`) on a match and `None` otherwise.
  - Always closes the connection in a `finally` block, following the pattern used by `create_user()`.
  - Import `check_password_hash` alongside the existing `generate_password_hash` import.

## Templates
- **Create:** none.
- **Modify:**
  - `templates/login.html`
    - Re-populate the email input from the submitted value on error (`value="{{ email or '' }}"`). Never re-populate `password`.
    - The existing flash block and `{% if error %}` block stay as they are.
  - `templates/base.html`
    - Make `.nav-links` session-aware:
      - `{% if session.get('user_id') %}`: show `<span class="nav-user">{{ session.get('user_name') }}</span>` and `<a href="{{ url_for('logout') }}">Sign out</a>`.
      - `{% else %}`: keep the existing "Sign in" and "Get started" links unchanged.

## Files to change
- `app.py`
  - Import `session` from `flask`.
  - Import `authenticate_user` from `database.db`.
  - Change `@app.route("/login")` to `methods=["GET", "POST"]` and implement POST handling as described in the rules below.
  - Replace the `/logout` stub body with the real implementation. Move the route out of the "Placeholder routes" section into the main "Routes" section.
- `database/db.py`: add `authenticate_user()` and import `check_password_hash`.
- `templates/login.html`: see Templates.
- `templates/base.html`: see Templates.
- `static/css/style.css`: add a `.nav-user` rule in the navbar section. It uses `var(--ink-soft)` for the text colour and `font-weight: 500`, with no hardcoded hex values.
- `CLAUDE.md`
  - In the routes table, add `POST /login` as implemented and mark `GET /logout` as implemented.

## Files to create
- `tests/test_login_logout.py`: pytest tests covering every item in the Definition of Done that can be automated. Reuse the `client` and `db_path` fixtures from `tests/conftest.py`. Do not import `app` at module level.

## New dependencies
No new dependencies. Flask's built-in `session` and werkzeug's `check_password_hash` are already available.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` through `get_db()` only.
- Parameterised queries only (`?` placeholders). Never build SQL with f-strings or string formatting.
- Passwords are hashed with werkzeug. Verification uses `check_password_hash`. The plain-text password is never stored, logged, put in the session or re-rendered.
- Use CSS variables and never hardcode hex values in new CSS.
- All templates extend `base.html`.
- **No DB logic in routes.** The route calls `authenticate_user()` and never calls `get_db()`, runs SQL or calls `check_password_hash` directly.
- **POST /login handling, in this order:**
  1. `email = request.form.get("email", "").strip().lower()`, matching how Step 2 stores emails.
  2. `password = request.form.get("password", "")`: do **not** strip it.
  3. If either field is empty, or `authenticate_user(email, password)` returns `None`, re-render `login.html` with `error="Invalid email or password."` and `email=email`, and return HTTP status **401**.
  4. Use the same generic error message for "unknown email" and "wrong password", so the page never reveals which emails are registered.
  5. Do **not** apply the registration password-length rule at login. The seeded demo password `demo123` is only 7 characters and must still work.
  6. On success, call `session.clear()` first, then set `session["user_id"] = user["id"]` and `session["user_name"] = user["name"]`, then `redirect(url_for("landing"))` (HTTP 302).
- **GET /login** when `session.get("user_id")` is set redirects to `url_for("landing")` without rendering the form.
- **GET /logout** calls `session.clear()`, then `flash("You've been signed out.", "success")`, then `redirect(url_for("login"))`. Clear the session before flashing, because flashed messages are stored in the session.
- Store only `user_id` and `user_name` in the session. Never store the email, password or password hash.
- Use `url_for()` for every internal link and redirect, with no hardcoded paths.
- Do not add a `login_required` decorator, protect other routes, or implement `/profile` or any expense routes. Those belong to Step 4 and later.
- Do not change the existing registration behaviour or its tests.
- The app stays on port 5001.

## Definition of done
- [ ] `GET /login` returns 200 and shows the Email address and Password fields.
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects (302) to `/`, and the navbar then shows "Demo User" and a "Sign out" link instead of "Sign in" / "Get started".
- [ ] Signing in as `DEMO@Spendly.com ` (different case plus a trailing space) with `demo123` also succeeds.
- [ ] A user registered through `/register` (e.g. `test@example.com` / `password123`) can then sign in with those credentials.
- [ ] Signing in with a correct email and wrong password shows "Invalid email or password." with status 401.
- [ ] Signing in with an unregistered email shows the exact same "Invalid email or password." message with status 401.
- [ ] Submitting an empty email or empty password shows "Invalid email or password." with status 401.
- [ ] After a failed sign-in, the Email input keeps what the user typed and the Password input is empty.
- [ ] After a successful sign-in, the session contains `user_id` and `user_name` and nothing derived from the password.
- [ ] Visiting `GET /login` while signed in redirects to `/`.
- [ ] Clicking "Sign out" (`GET /logout`) redirects to `/login` and shows the green message "You've been signed out.".
- [ ] After signing out, the session no longer contains `user_id`, and the navbar shows "Sign in" / "Get started" again.
- [ ] `GET /logout` while not signed in still redirects to `/login` without an error.
- [ ] `/logout` no longer returns the placeholder text "Logout — coming in Step 3".
- [ ] `app.py` contains no `get_db()` calls, SQL strings or `check_password_hash` calls inside route functions.
- [ ] `pytest` passes, including the existing registration tests, and the tests use a temporary database rather than `expense_tracker.db`.
- [ ] `python app.py` starts without errors on port 5001.
