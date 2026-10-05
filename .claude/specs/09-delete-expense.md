# Spec: Delete Expense

## Overview
Step 9 lets a signed-in user remove an expense they recorded by mistake.
Steps 7 and 8 added creating and editing expenses, the ownership-checked
`get_expense()` lookup, and a per-row actions column on the `/profile`
recent-transactions table. `/expenses/<id>/delete` is still a stub that
returns a plain string. This step replaces the stub with a two-step flow.
`GET` shows a confirmation page that summarises the expense. `POST` deletes
the row, but only if it belongs to the session user. Deleting is never done
on `GET`: links can be prefetched, crawled or embedded (`<img src>`), so a
destructive action behind a plain link is unsafe. The step also adds a
"Delete" icon link next to the existing "Edit" link on each profile row.
After this step the expense CRUD flow is complete.

## Depends on
- Step 1: Database setup (`expenses` table, `get_db()` with `PRAGMA foreign_keys = ON`)
- Step 3: Login / Logout (`session["user_id"]`)
- Step 5: Backend routes for profile page (`get_recent_transactions()` returns `id`)
- Step 7: Add expense (`expense.css`, form/card layout, flash on `/profile`)
- Step 8: Edit expense (`get_expense(id, user_id)` in `queries.py`, actions
  column and `.profile-edit` / `.profile-visually-hidden` styles in `profile.css`)

## Routes
The existing stub `/expenses/<int:id>/delete` is replaced with a real
implementation (`methods=["GET", "POST"]`). The URL and endpoint name
(`delete_expense`) stay the same.
- `GET /expenses/<id>/delete` — render a confirmation page showing the
  expense's date, description ("—" if `NULL`), category and amount (₹, 2dp),
  with a "Delete expense" submit button (POST to the same URL) and a
  "Cancel" link to `url_for('profile')`. Nothing is deleted. — logged-in
- `POST /expenses/<id>/delete` — delete the row, flash "Expense deleted."
  (category `success`), and redirect to `url_for('profile')`. The request
  body is ignored: no form fields are read or needed. — logged-in

Access behaviour (both methods, checked in this order, same as Step 8):
1. Signed out → redirect to `url_for('login')`
2. `session["user_id"]` points to a user who no longer exists →
   `session.clear()` then redirect to `url_for('login')`
3. Expense id doesn't exist, **or** belongs to another user → `abort(404)`.
   Both cases return the same 404. On POST, nothing is deleted.
4. POST only: if `delete_expense()` reports that no row was deleted (for
   example, it was removed in another tab between the lookup and the
   delete) → `abort(404)`

A second POST to the same id after a successful delete returns 404 (the
expense no longer exists).

## Database changes
No database changes. The `expenses` table already has `id` and `user_id`.
Nothing references `expenses`, so deleting a row cascades nothing. Ownership
is enforced in SQL (`WHERE id = ? AND user_id = ?`), not by a new
constraint. This is a hard delete: no `deleted_at` column, no soft delete,
no undo.

## Templates
- **Create:** `templates/delete_expense.html`
  - Extends `base.html`, sets `{% block title %}Delete expense — Spendly{% endblock %}`
  - Loads `expense.css` via `{% block head %}` and uses the same
    `auth-section expense` / `auth-container` / `auth-header` / `auth-card`
    structure as `edit_expense.html`
  - Header: title "Delete expense", subtitle such as "This can't be undone."
  - A read-only summary of the expense as a `<dl>` (Date, Description,
    Category, Amount). Description shows "—" when `NULL`. The date is wrapped
    in `<time datetime="...">`.
  - `<form method="post" action="{{ url_for('delete_expense', id=expense.id) }}">`
    containing only the buttons. No inputs: the id comes from the URL.
  - Actions row (`.expense-actions`): a secondary "Cancel" link to
    `url_for('profile')` and a destructive "Delete expense" submit button
    with a Lucide `trash-2` icon (`aria-hidden="true"`)
- **Modify:** `templates/profile.html`
  - In the existing `.profile-actions` cell, add a second link after the edit
    link: `<a href="{{ url_for('delete_expense', id=tx.id) }}" class="profile-delete">`
    with a Lucide `trash-2` icon (`aria-hidden="true"`) and an accessible name
    built the same way as the edit link's, e.g.
    `aria-label="Delete {{ ... }} on {{ tx.date }}"`
  - It links to the confirmation page. It is not a form and does not
    delete directly.

## Files to change
- `app.py`
  - Import `delete_expense` from `database.db`. It clashes with the view
    function name, so import it under an alias (e.g.
    `from database.db import delete_expense as db_delete_expense`) or rename
    the DB helper. Don't rename the route endpoint.
  - Replace the `delete_expense(id)` stub (and the "Placeholder routes"
    section header, now empty) with a `GET`/`POST` view placed after
    `edit_expense`. It does the auth/stale-user check, loads the expense with
    `get_expense(id, user_id)` and calls `abort(404)` if that returns `None`.
    On GET it renders `delete_expense.html` with `expense=expense`. On POST
    it calls the DB helper, calls `abort(404)` if it returns `False`, then
    flashes and redirects. No SQL in the view.
- `database/db.py`
  - Add `delete_expense(expense_id, user_id)`. Runs
    `DELETE FROM expenses WHERE id = ? AND user_id = ?`, commits, and returns
    `True` if exactly one row was deleted (`cursor.rowcount == 1`), otherwise
    `False`. Closes the connection in `finally`, the same shape as
    `update_expense`. The `user_id` in the `WHERE` clause is a second
    ownership guard even though the view already checked.
- `templates/profile.html` — add the delete link (see Templates)
- `static/css/profile.css`
  - Style `.profile-delete` like `.profile-edit` (same size, radius and
    focus ring). Share the rules with a combined selector rather than
    copying them. On hover/focus use `var(--danger)` text and
    `var(--danger-light)` background.
  - Put a small gap between the two icons in `.profile-actions`.
- `static/css/expense.css`
  - Add a destructive button style for the confirm page (e.g.
    `.expense-delete`): `var(--danger)` background, `var(--paper-card)` text,
    the same size, radius and focus ring as `.btn-primary` in
    `.expense-actions`, and a hover state.
  - Add styles for the summary `<dl>` (e.g. `.expense-summary`): label/value
    rows, muted labels, tabular numbers for the amount.
  - Update the header comment to "Expense form (add / edit / delete)".
- `tests/test_07-add-expense.py` — `test_delete_stub_still_returns_stub_string`
  now fails by design. Remove it.
- `tests/test_08-edit-expense.py` — `test_delete_stub_still_returns_stub_string`
  and `test_profile_has_no_delete_link` now fail by design. Remove both.
- `CLAUDE.md`
  - Replace the `GET /expenses/<id>/delete` "Stub — Step 9" row with
    "Implemented" rows for `GET` (confirmation page) and `POST` (deletes,
    404 if not owned)
  - Add `delete_expense()` to the `db.py` helper list in the Architecture block
  - Update the `expense.css` comment to "Expense form (add/edit/delete) styles"

## Files to create
- `templates/delete_expense.html` — the delete confirmation page
- `tests/test_09-delete-expense.py` — tests for this feature, written by the
  test-writer subagent from this spec. Use the existing `client`,
  `make_user` and `add_expense` fixtures in `tests/conftest.py`. Log in via
  `POST /login` and assert against the DB or `/profile`. Pass dates
  explicitly rather than relying on the seed data.

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
- Vanilla HTML only. No JavaScript, and no `confirm()` dialog. The
  confirmation page is the confirmation.
- **Never delete on GET.** Only a POST removes a row.
- Ownership is enforced server-side on **both** GET and POST. The
  `user_id` always comes from `session["user_id"]`. The expense id comes
  only from the URL. Never read either from the form body.
- Not-found and not-yours both return `abort(404)`. Never 403, and never a
  raw string return.
- On success, follow the POST/Redirect/GET pattern: `flash` then `redirect`
  to `/profile`.
- Rely on Jinja autoescaping for the description. Never use `|safe`.
- Keep route functions thin. The lookup is the existing `get_expense`
  (`queries.py`, read-only). The write is `delete_expense` (`db.py`).
- Don't add a bulk delete, soft delete or undo.
- CSRF protection is out of scope: no new packages, and it's consistent with
  the existing forms.

## Definition of done
- [ ] Signed-out `GET` and `POST /expenses/<id>/delete` redirect to `/login`, and the POST deletes nothing
- [ ] A session for a deleted user is cleared and redirected to `/login` on both GET and POST
- [ ] `GET /expenses/<id>/delete` for the user's own expense returns 200 and shows its date, description, category and amount (e.g. `₹12.50`), a "Delete expense" button and a Cancel link to `/profile`
- [ ] A `NULL` description is shown as "—" on the confirmation page, not "None"
- [ ] `GET /expenses/<id>/delete` does **not** delete the row (it's still in the DB and on `/profile` afterwards)
- [ ] The confirmation form posts to `/expenses/<id>/delete` and contains no `user_id` or id input
- [ ] `GET` or `POST /expenses/<id>/delete` for a non-existent id returns 404
- [ ] `GET` or `POST /expenses/<id>/delete` for another user's expense returns 404, and the POST leaves that row in the DB
- [ ] `POST /expenses/<id>/delete` for the user's own expense redirects to `/profile`, shows "Expense deleted.", and the row is gone from the DB and from "Recent transactions"
- [ ] After deleting, the transaction count drops by 1, and total spent, top category and the category breakdown on `/profile` reflect the removal
- [ ] Deleting one expense doesn't remove any other row (same user or other users), and doesn't affect the `users` table
- [ ] A second `POST` to the same id after a successful delete returns 404
- [ ] Deleting a user's last expense shows the "No expenses yet." empty state on `/profile`
- [ ] Each row in "Recent transactions" on `/profile` has a Delete link pointing to that expense's `/expenses/<id>/delete` page, alongside the existing Edit link, each with a distinct accessible name
- [ ] HTML in the description (e.g. `<script>`) is escaped on the confirmation page
- [ ] `profile.css` and `expense.css` contain no hardcoded hex colours, and `delete_expense.html` has no `<style>` tags or `style=` attributes
- [ ] All existing tests (`pytest`) still pass, with the Step 7/8 delete-stub tests and the "no delete link" test removed
