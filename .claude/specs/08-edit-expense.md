# Spec: Edit Expense

## Overview
Step 8 lets a signed-in user correct an expense they already recorded. Step 7
added the add-expense form, `_validate_expense()` and `create_expense()`, but
there is still no way to fix a typo in an amount, a wrong category or a
mistaken date. `/expenses/<id>/edit` is a stub that returns a plain string, and
the recent-transactions table on `/profile` has no way to reach it. This step
replaces the stub with a pre-filled form (same fields and validation as Step 7)
and a POST handler that updates the row, but only if it belongs to the session
user. It also adds an "Edit" link to each row of the recent-transactions table.
Step 9 (delete) will reuse the ownership-checked lookup and the per-row action
column added here.

## Depends on
- Step 1: Database setup (`expenses` table, `CATEGORIES` tuple, `get_db()`)
- Step 3: Login / Logout (`session["user_id"]`)
- Step 5: Backend routes for profile page (`get_recent_transactions()` in `queries.py`)
- Step 6: Date filter for profile page (`_parse_iso_date()` helper)
- Step 7: Add expense (`_validate_expense()`, `expense.css`, form layout, flash on `/profile`)

## Routes
The existing stub `/expenses/<int:id>/edit` is replaced with a real
implementation (`methods=["GET", "POST"]`):
- `GET /expenses/<id>/edit` — render the edit form pre-filled with the
  expense's current amount (formatted to 2dp), category, date and
  description (blank if `NULL`) — logged-in
- `POST /expenses/<id>/edit` — validate with the existing
  `_validate_expense(request.form, today)`, then update the row. On success,
  flash "Expense updated." (category `success`) and redirect to
  `url_for('profile')`. On a validation error, re-render the form with
  status 400, an inline error, and the submitted values preserved
  (not the stored values) — logged-in

Access behaviour (both methods, checked in this order):
1. Signed out → redirect to `url_for('login')`
2. `session["user_id"]` points to a user who no longer exists →
   `session.clear()` then redirect to `url_for('login')` (same pattern as
   `/profile`, `/analytics`, `/expenses/add`)
3. Expense id doesn't exist, **or** belongs to another user → `abort(404)`.
   Both cases return the same 404 so a user can't probe which ids exist.
   On POST, nothing is updated.

The `/expenses/<id>/delete` stub is **not** touched.

## Database changes
No database changes. The `expenses` table already has every column this step
needs (`id`, `user_id`, `amount`, `category`, `date`, `description`). The
ownership check is done in SQL (`WHERE id = ? AND user_id = ?`), not by a new
constraint. `created_at` is not changed on update, and no `updated_at` column
is added.

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`, sets `{% block title %}Edit expense — Spendly{% endblock %}`
  - Loads `expense.css` via `{% block head %}` and uses the same
    `auth-section expense` / `auth-card` structure as `add_expense.html`
  - Header: title "Edit expense", subtitle e.g. "Update the details of this expense"
  - `<form method="post" action="{{ url_for('edit_expense', id=expense_id) }}">`
    with the same four fields, attributes and `<label for=...>`s as
    `add_expense.html` (amount with ₹ prefix, `step="0.01"`, `min="0.01"`,
    `max="10000000"`; category `<select>` from `categories` with the current
    value selected; date with `max` set to today; description with
    `maxlength="200"`)
  - Inline error area (`role="alert"`, `.expense-error`), shown only when
    `error` is set
  - A primary "Save changes" submit button and a secondary "Cancel" link to
    `url_for('profile')`
- **Modify:** `templates/profile.html`
  - Add a narrow actions column to the recent-transactions table: a
    `<th scope="col">` whose "Actions" label is visually hidden, and per row an `<a href="{{ url_for('edit_expense', id=tx.id) }}">`
    with a Lucide `pencil` icon (`aria-hidden="true"`) and an accessible name
    such as `aria-label="Edit {{ tx.description }} on {{ tx.date }}"`
  - No delete link (Step 9)

## Files to change
- `app.py`
  - Import `update_expense` from `database.db` and `get_expense` from
    `database.queries`
  - Replace the `edit_expense(id)` stub with a `GET`/`POST` view. It does the
    auth/stale-user check, loads the expense with
    `get_expense(id, user_id)` and calls `abort(404)` if that returns `None`,
    then either renders the form or validates, calls
    `update_expense(id, user_id, **values)`, flashes and redirects. No SQL
    in the view. Import `abort` from `flask`.
  - Reuse `_validate_expense()` as-is. Update its docstring to say it's
    used by both the add and edit forms (it currently says "add-expense form").
  - Pass `categories=CATEGORIES`, `today=date.today().isoformat()` and
    `expense_id=id` to the template. On GET, pass `form` built from the
    stored row (`amount` as `"%.2f"`, `description` as `""` when `NULL`). On
    error, pass `form=request.form` and `error`.
- `database/db.py`
  - Add `update_expense(expense_id, user_id, amount, category, date, description)`.
    Runs `UPDATE expenses SET amount = ?, category = ?, date = ?, description = ?
    WHERE id = ? AND user_id = ?`, commits, returns `True` if exactly one row
    was updated (`cursor.rowcount == 1`), otherwise `False`. Closes the
    connection in `finally` (same shape as `create_expense`). The
    `user_id` in the `WHERE` clause is a second ownership guard even though
    the view already checked.
- `database/queries.py`
  - Add `get_expense(expense_id, user_id)`. Returns
    `{id, amount, category, date, description}` for that expense if it
    belongs to `user_id`, otherwise `None`. `amount` is a 2dp float;
    `description` is the raw value (may be `None`, not `NO_VALUE`).
  - Add `id` to the `SELECT` and the returned dicts in
    `get_recent_transactions()` so the profile table can link to each row.
    Existing keys and their values stay unchanged.
- `templates/profile.html` — add the edit action column (see Templates)
- `static/css/profile.css` — style the actions column and edit link (small
  icon button, visible focus ring, right-aligned). CSS variables only. Add a
  visually-hidden utility class here only if `style.css` doesn't already
  have one.
- `tests/test_07-add-expense.py` — `test_edit_stub_still_returns_stub_string`
  now fails by design. Remove it, or change it to only assert that the
  delete stub is untouched. Leave the delete-stub test as it is.
- `CLAUDE.md`
  - Change the `GET /expenses/<id>/edit` row to "Implemented" and add a
    `POST /expenses/<id>/edit` row describing the 404-on-not-owned behaviour
  - Add `update_expense()` to the `db.py` helper list in the Architecture block

## Files to create
- `templates/edit_expense.html` — the edit-expense form page
- `tests/test_08-edit-expense.py` — tests for this feature, written by the
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
- No inline `<style>` tags or new `style=` attributes.
- Use `url_for()` for every internal link and the form `action`.
- Vanilla HTML/JS only. No JS is needed for this step.
- Ownership is enforced server-side on **both** GET and POST. The
  `user_id` always comes from `session["user_id"]`. Never read it, or the
  expense id, from the form body. The id comes only from the URL.
- Not-found and not-yours both return `abort(404)`. Never 403, and never a
  raw string return.
- Reuse `_validate_expense()` unchanged in behaviour. Don't copy its rules
  into a second helper.
- On a validation error, return HTTP 400 and re-render with the submitted
  values. Don't redirect, don't flash the error, and don't touch the DB.
- On success, follow the POST/Redirect/GET pattern: `flash` then `redirect`
  to `/profile`.
- Rely on Jinja autoescaping when filling values. Never use `|safe`.
- Keep route functions thin. The lookup lives in `get_expense`
  (`queries.py`, read-only) and the write in `update_expense` (`db.py`).
- Don't implement the Step 9 (delete) stub or add a delete link.
- CSRF protection is out of scope: no new packages, and it's consistent with
  the existing forms.

## Definition of done
- [ ] Signed-out `GET` and `POST /expenses/<id>/edit` redirect to `/login`, and the POST changes nothing
- [ ] A session for a deleted user is cleared and redirected to `/login` on both GET and POST
- [ ] `GET /expenses/<id>/edit` for the user's own expense returns 200 with amount, category, date and description pre-filled from the DB, a "Save changes" button and a Cancel link to `/profile`
- [ ] An amount stored as `12.5` is pre-filled as `12.50`; a `NULL` description is pre-filled as empty, not "—" or "None"
- [ ] The category dropdown lists exactly the 7 `CATEGORIES`, with the stored category selected
- [ ] `GET` or `POST /expenses/<id>/edit` for a non-existent id returns 404
- [ ] `GET` or `POST /expenses/<id>/edit` for another user's expense returns 404, and the POST leaves that row unchanged
- [ ] Each row in "Recent transactions" on `/profile` has an Edit link pointing to that expense's edit page
- [ ] Changing amount to `99.99`, category to `Bills`, date to `2026-09-10` and description to `Updated` redirects to `/profile`, shows "Expense updated.", and the row shows the new values
- [ ] After editing, total spent, top category and the category breakdown on `/profile` reflect the new values, and the transaction count is unchanged
- [ ] Clearing the description saves `description` as NULL, shown as "—" on `/profile`
- [ ] Editing one expense doesn't change any other row (same user or other users)
- [ ] A `user_id` field in the POST body is ignored: the row's `user_id` doesn't change
- [ ] Amount blank, `0`, `-5`, `abc`, `nan`, `inf`, `12.345` or above 10,000,000 → 400, error shown, row unchanged
- [ ] Category not in `CATEGORIES` (e.g. `Rent`) → 400, error shown, row unchanged
- [ ] Date blank, `2026-13-01`, `2026-9-1` or a date after today → 400, error shown, row unchanged
- [ ] A description longer than 200 characters → 400, error shown, row unchanged
- [ ] After a validation error, the form shows the submitted values, not the stored ones
- [ ] HTML in the description (e.g. `<script>`) is escaped on the edit form and on `/profile`
- [ ] `/expenses/<id>/delete` still returns its stub string
- [ ] `profile.css` contains no hardcoded hex colours and `edit_expense.html` has no `<style>` tags or `style=` attributes
- [ ] All existing tests (`pytest`) still pass, with the Step 7 edit-stub test removed or updated
