# Spec: Add Expense

## Overview
Step 7 lets a signed-in user record a new expense. Until now, every expense in
the database has come from seed data or test fixtures. The "Add expense" button
on the profile page already links to `url_for('add_expense')`, but that route
is a stub that returns a plain string. This step replaces the stub with a real
form page (amount, category, date, description) and a POST handler. The handler
validates the input, inserts the row for the session user, flashes a
confirmation and redirects to `/profile`. The new expense then appears in the
summary stats, recent transactions and category breakdown built in Steps 5–6.
This is the first write-side expense feature. It sets the form, validation and
DB-helper pattern that Step 8 (edit) and Step 9 (delete) will reuse.

## Depends on
- Step 1: Database setup (`expenses` table, `CATEGORIES` tuple, `get_db()`)
- Step 3: Login / Logout (`session["user_id"]`)
- Step 4: Profile page design (the "Add expense" button that links here)
- Step 5: Backend routes for profile page (live query helpers that will show the new row)
- Step 6: Date filter for profile page (`_parse_iso_date()` helper in `app.py`)

## Routes
The existing stub `/expenses/add` is replaced with a real implementation:
- `GET /expenses/add` — render the add-expense form, with the date pre-filled
  to today and no category pre-selected — logged-in
- `POST /expenses/add` — validate the form and insert the expense for
  `session["user_id"]`. On success, flash "Expense added." (category
  `success`) and redirect to `url_for('profile')`. On a validation error,
  re-render the form with status 400, an inline error, and the submitted
  values preserved — logged-in

Access behaviour (both methods):
- Signed out → redirect to `url_for('login')`
- `session["user_id"]` points to a user who no longer exists → `session.clear()`
  then redirect to `url_for('login')` (same pattern as `/profile` and `/analytics`)

The `/expenses/<id>/edit` and `/expenses/<id>/delete` stubs are **not** touched.

## Database changes
No database changes. The `expenses` table in `database/db.py` already has
`user_id` (FK to `users`, `ON DELETE CASCADE`), `amount REAL NOT NULL`,
`category TEXT NOT NULL`, `date TEXT NOT NULL` (ISO `YYYY-MM-DD`),
`description TEXT` (nullable) and `created_at`. The allowed categories are the
existing `CATEGORIES` tuple in `database/db.py`. Don't add a categories table
or a CHECK constraint.

## Templates
- **Create:** `templates/add_expense.html`
  - Extends `base.html` and sets `{% block title %}Add expense — Spendly{% endblock %}`
  - Loads `expense.css` via `{% block head %}`
  - A card containing a `<form method="post" action="{{ url_for('add_expense') }}">` with:
    - **Amount**: `<input type="number" name="amount" step="0.01" min="0.01" required>`,
      labelled with a ₹ prefix
    - **Category**: `<select name="category" required>` with a disabled
      placeholder option, then one `<option>` per entry in `categories`
      (passed from the route). The previously submitted value stays selected
      after an error.
    - **Date**: `<input type="date" name="date" required>`, with `max` set to today
    - **Description**: `<input type="text" name="description" maxlength="200">`, optional
    - Each field has a visible `<label for=...>`
  - An inline error area (`role="alert"`), shown only when `error` is set
  - A primary "Add expense" submit button and a secondary "Cancel" link to
    `url_for('profile')`
  - Lucide icon(s) with `aria-hidden="true"` are optional, matching existing usage
- **Modify:** `templates/profile.html`
  - Render flashed messages near the top of the profile (above or inside the
    user header card), so "Expense added." shows after the redirect. Use the
    same `get_flashed_messages(with_categories=true)` pattern as `login.html`,
    with `role="status"`.

## Files to change
- `app.py`
  - Import `CATEGORIES` and `create_expense` from `database.db`
  - Add a helper `_validate_expense(form, today)` that returns
    `(values, error)`. `values` is a dict with `amount`, `category`, `date`
    and `description`, cleaned and ready for insertion. `error` is the first
    error message, or `None`. It takes `today` as a parameter so tests are
    deterministic. Rules:
    - `amount`: strip, then parse with `Decimal`. It must be finite and
      `> 0`, have at most 2 decimal places, and be `<= 10,000,000`. Reject
      blank, non-numeric, `nan` and `inf`. Store it as `float` rounded to 2dp.
    - `category`: must be exactly one of `CATEGORIES`
    - `date`: strip, then require a valid canonical `YYYY-MM-DD` using the
      existing `_parse_iso_date()` (blank is an error here). It must not be
      after `today`.
    - `description`: strip; at most 200 characters; blank becomes `None`
  - Replace the `add_expense()` stub with `methods=["GET", "POST"]`. The view
    does the auth/stale-user check, then either renders the form or validates,
    calls `create_expense(...)`, flashes and redirects. No SQL in the view.
  - Pass `categories=CATEGORIES` and `today=date.today().isoformat()` to the
    template. On error, also pass `error` and the raw submitted values (`form`)
    so the fields are re-filled.
- `database/db.py`
  - Add `create_expense(user_id, amount, category, date, description)`. It
    inserts with a parameterised query, commits, returns the new id, and
    closes the connection in `finally` (same shape as `create_user`). It
    belongs in `db.py`, not `queries.py`, because `queries.py` is read-only.
- `templates/profile.html` — add the flash message block (see Templates)
- `static/css/profile.css` — style the flash message on the profile page if
  existing classes don't fit (CSS variables only)
- `CLAUDE.md`
  - Update the `GET /expenses/add` row in the routes table to "Implemented",
    and add a `POST /expenses/add` row
  - Add `create_expense()` to the `db.py` helper list in the Architecture block
  - Add `expense.css` to the static CSS list in the Architecture block

## Files to create
- `templates/add_expense.html` — the add-expense form page
- `static/css/expense.css` — styles for the add/edit expense form. It's shared
  so Step 8 can reuse it. Use CSS variables only and reuse `.form-input` /
  `.form-group` from `style.css` where possible.
- `tests/test_07-add-expense.py` — tests for this feature, written by the
  test-writer subagent from this spec. Use the existing `client`,
  `make_user` and `add_expense` fixtures in `tests/conftest.py`. Log in via
  `POST /login` and assert against the DB or `/profile`. Pass dates explicitly
  rather than relying on the seed data.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` via `get_db()` only.
- Use parameterised queries only (`?` placeholders). Never f-strings,
  `%` or `.format()` in SQL.
- Passwords are hashed with werkzeug (auth isn't touched in this step).
- Use CSS variables. Never hardcode hex values in `expense.css` or `profile.css`.
- All templates extend `base.html`.
- No inline `<style>` tags or `style=` attributes in new markup.
- Use `url_for()` for every internal link and the form `action`.
- Use vanilla HTML/JS only. Native `required`, `min`, `step`, `max`,
  `maxlength` and `type="date"` handle client-side hints. Server-side
  validation is still authoritative and must not rely on them.
- The `user_id` always comes from `session["user_id"]`. Never read it from
  the form or query string, even if one is submitted.
- Amount validation uses `Decimal`, not `float`, so `0.1 + 0.2`-style issues
  and `"1e3"` / `"nan"` / `"inf"` edge cases are handled deliberately.
  `"1e3"` may be accepted as 1000.00 if it passes all the other checks;
  `nan` and `inf` must be rejected.
- Category must be validated against `CATEGORIES` server-side (a tampered
  `<select>` value must be rejected with 400).
- On a validation error, return HTTP 400 and re-render the form. Don't
  redirect, and don't flash the error.
- On success, follow the POST/Redirect/GET pattern: `flash` then `redirect` to
  `/profile`.
- Rely on Jinja autoescaping when re-filling submitted values. Never use `|safe`.
- Keep route functions thin. Validation lives in the `_validate_expense`
  helper and the insert in `create_expense`.
- Don't implement the Step 8 (edit) or Step 9 (delete) stubs.
- CSRF protection is out of scope: no new packages, and it's consistent with
  the existing register/login forms.

## Definition of done
- [ ] Signed-out `GET /expenses/add` redirects to `/login`
- [ ] Signed-out `POST /expenses/add` redirects to `/login` and inserts nothing
- [ ] A session for a deleted user is cleared and redirected to `/login` on both GET and POST
- [ ] Signed-in `GET /expenses/add` returns 200 and shows the amount, category, date and description fields, an "Add expense" button and a Cancel link to `/profile`
- [ ] The category dropdown lists exactly the 7 categories from `CATEGORIES`
- [ ] The date field defaults to today's date
- [ ] Clicking "Add expense" on `/profile` opens the form, not the old stub string
- [ ] Submitting amount `250.50`, category `Food`, date `2026-09-15`, description `Dinner` redirects to `/profile`, shows "Expense added.", and the row appears in recent transactions with ₹250.50
- [ ] After adding, total spent and transaction count on `/profile` increase accordingly, and the category breakdown includes the new amount
- [ ] An expense with a blank description is saved with `description` NULL and shows as "—" in recent transactions
- [ ] The new row's `user_id` is the signed-in user, even if the form includes a `user_id` field for another user
- [ ] Amount blank, `0`, `-5`, `abc`, `nan`, `inf`, `12.345` or above 10,000,000 → 400, error shown, nothing inserted
- [ ] Category not in `CATEGORIES` (e.g. `Rent`) → 400, error shown, nothing inserted
- [ ] Date blank, `2026-13-01`, `2026-9-1` or a date after today → 400, error shown, nothing inserted
- [ ] A description longer than 200 characters → 400, error shown, nothing inserted
- [ ] After a validation error, the previously entered amount, category, date and description are still in the form
- [ ] HTML in the description (e.g. `<script>`) is escaped on `/profile`, not executed
- [ ] `/expenses/<id>/edit` and `/expenses/<id>/delete` still return their stub strings
- [ ] `expense.css` contains no hardcoded hex colours and `add_expense.html` has no `<style>` tags or `style=` attributes
- [ ] All existing tests (`pytest`) still pass
