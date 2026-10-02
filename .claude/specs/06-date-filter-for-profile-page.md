# Spec: Date Filter for Profile Page

## Overview
Step 6 lets a signed-in user narrow the profile page to a chosen period. Today
`/profile` always shows all-time figures: total spent, transaction count, top
category, the 10 most recent transactions and the category breakdown. This
step adds a filter bar with quick presets (This month, Last 30 days, This year,
All time) and a custom start/end date range. The filter is passed as GET query
parameters (`/profile?start=YYYY-MM-DD&end=YYYY-MM-DD`), so filtered views can
be bookmarked and the back button works. All three data sections recalculate
for the selected range. User info (name, email, member since) is unaffected.
This is the first read-side feature built on the Step 5 query layer, and it
comes before the add/edit/delete expense steps (7–9). Once those land, users
will have enough data that a period view becomes useful.

## Depends on
- Step 1: Database setup (`expenses.date` stored as `YYYY-MM-DD` text)
- Step 3: Login / Logout (`session["user_id"]`)
- Step 4: Profile page design (template sections and `profile.css`)
- Step 5: Backend routes for profile page (`database/queries.py` helpers)

## Routes
No new routes. The existing `GET /profile` route is modified:
- `GET /profile` — now accepts optional query params `start` and `end`
  (each `YYYY-MM-DD`, both inclusive) — logged-in

Behaviour:
- Neither param → all-time view (identical to current behaviour)
- Only `start` → everything on or after `start`
- Only `end` → everything on or before `end`
- Both → everything between them, inclusive
- Malformed date, or `start` after `end` → ignore both params, render the
  all-time view with status 200 and an inline error message in the filter bar
  (no redirect, no `abort()`, because a bad filter isn't an HTTP error)
- Signed-out user → redirect to `/login` (unchanged)

Param names are `start` / `end`, not `from` / `to`, because `from` is a Python
keyword and would break `url_for('profile', from=...)`.

## Database changes
No database changes. `expenses.date` is already `TEXT NOT NULL` in ISO
`YYYY-MM-DD` form (see `database/db.py` `SCHEMA` and `_seed_date`), so plain
string comparison (`date >= ?`, `date <= ?`) orders correctly.

## Templates
- **Create:** none
- **Modify:** `templates/profile.html`
  - Add a filter bar between the user header card and the stats `<dl>`:
    - A row of preset links built with `url_for('profile', start=..., end=...)`
      (All time → `url_for('profile')` with no params). The active preset gets
      `aria-current="true"` and an active class.
    - A `<form method="get" action="{{ url_for('profile') }}">` with two
      `<input type="date">` fields (`name="start"`, `name="end"`) that are
      pre-filled with the current valid values, plus an "Apply" submit button
      and a "Clear" link to `url_for('profile')`. Each input has a visible
      `<label>`.
    - An error message area (`role="alert"`) shown only when `date_filter.error` is set
  - When a filter is active, show a period label near the stats, e.g.
    "Showing 1 Sep 2026 – 30 Sep 2026" / "Since 1 Sep 2026" / "Up to 30 Sep 2026"
  - Update the transactions caption so it doesn't say "most recent of N
    expenses" as if N were all-time. N is now the count for the selected period.
  - Empty states: branch only on whether a filter is active. When no filter is
    active, keep "No expenses yet." / "No spending to break down yet." verbatim.
    When a filter is active and matches nothing, show "No expenses in this
    period." with a link to clear the filter, and "No spending in this period."
    in the category panel.

## Files to change
- `app.py`
  - Add a helper `_parse_date_range(args)` that returns `(start, end, error)`,
    where `start` / `end` are canonical ISO strings (`"YYYY-MM-DD"`) or `None`,
    and `error` is a message string or `None`. Strip each value first; blank
    counts as "not provided". Parse with `datetime.strptime(value, "%Y-%m-%d")`
    and also require `parsed.date().isoformat() == value`, because strptime
    alone accepts `2026-9-1`. Don't use `date.fromisoformat`, which accepts
    extra formats like `20260901` on 3.11+.
  - Add a helper `_date_presets(today)` that returns a list of
    `{label, start, end}` dicts (ISO strings, or `None`) for This month (1st to
    last day of the month), Last 30 days (today − 29 days to today), This year
    (Jan 1 to Dec 31), and All time (`None`, `None`). It takes `today` as a
    parameter so tests can be deterministic.
  - `profile()` parses the range, passes `start_date` / `end_date` to the three
    query helpers, and passes `presets` and a `date_filter` dict to the
    template. The dict has keys `start`, `end`, `error`, `active` (label of the
    first preset whose start/end match exactly, else `None`), `label` (period
    label or `None`) and `is_active` (bool). No SQL or `get_db()` in the view.
- `database/queries.py`
  - `get_summary_stats`, `get_recent_transactions`, `get_category_breakdown`
    and `_fetch_category_totals` gain keyword args `start_date=None,
    end_date=None` (ISO strings or `None`). Existing positional calls must keep
    working unchanged, which keeps `test_profile_context_contract` passing.
- `static/css/profile.css` — styles for the filter bar, preset chips, date
  inputs, the active state, the error message and the period label
- `CLAUDE.md` — update the `GET /profile` row in the routes table to mention
  the `start` / `end` date filter

## Files to create
- `tests/test_date_filter.py` — tests for this feature, written by the test-writer
  subagent from this spec. Insert expenses on fixed dates with the existing
  `make_user` / `add_expense` fixtures. Don't rely on seed data, because seed
  dates are clamped to the current day and shift with the calendar.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` via `get_db()` only.
- Use parameterised queries only. Never f-strings or `%`/`.format()` in SQL.
  - Keep the SQL static by using the null-guard pattern instead of building
    clauses dynamically:
    `AND (? IS NULL OR date >= ?) AND (? IS NULL OR date <= ?)`, with each
    bound value passed twice.
- Passwords are hashed with werkzeug (nothing changes here in this step; don't touch auth).
- Use CSS variables. Never hardcode hex values in `profile.css`.
- All templates extend `base.html`.
- No inline `<style>` tags and no new inline `style=` attributes.
  (The existing category bar width remains as known debt from Step 4.)
- Build every internal link and the form `action` with `url_for()`.
- Vanilla HTML only for the filter. Native `<input type="date">` submits
  `YYYY-MM-DD`, so no JS is needed. Don't add JS libraries.
- Use Lucide icons (e.g. `calendar-range`) with `aria-hidden="true"`, matching
  existing usage.
- Date range bounds are inclusive on both ends.
- The filter applies to summary stats, recent transactions and category
  breakdown together, so the three sections must always agree. Category
  `pct` must still sum to 100 for a non-empty range, and `total_spent` must
  still equal the sum of category amounts.
- `get_recent_transactions` keeps its `limit=10` within the filtered range.
- Never echo raw query-string input into the page unescaped. Rely on Jinja
  autoescaping, and only re-fill the inputs with values that passed validation.
- Don't implement stub routes for Steps 7–9.

## Definition of done
- [ ] Visiting `/profile` with no query params shows the same all-time figures as before this step
- [ ] The filter bar shows presets This month, Last 30 days, This year and All time, plus start/end date inputs with Apply and Clear
- [ ] Clicking "This month" changes the URL to `/profile?start=<1st of month>&end=<last day of month>` and only that month's expenses are counted in total spent, transactions, top category and breakdown
- [ ] With expenses on 2026-08-15 (₹100) and 2026-09-10 (₹50), `/profile?start=2026-09-01&end=2026-09-30` shows total ₹50.00, 1 transaction, and only the 2026-09-10 row
- [ ] An expense dated exactly on `start` or `end` is included (inclusive bounds)
- [ ] `/profile?start=2026-09-01` alone shows everything from that date onward, and `/profile?end=2026-08-31` alone shows everything up to it
- [ ] Category percentages for a filtered view sum to 100%, and the top category reflects only the filtered range
- [ ] The active preset is visually highlighted and has `aria-current`
- [ ] Date inputs are pre-filled with the active range after applying a filter
- [ ] `/profile?start=not-a-date` returns 200, shows an error message, and falls back to all-time figures
- [ ] `/profile?start=2026-09-30&end=2026-09-01` (start after end) returns 200, shows an error message, and falls back to all-time figures
- [ ] A filter that matches no expenses shows "No expenses in this period." with a clear-filter link, ₹0.00 total and 0 transactions, without errors
- [ ] One user's filtered view never includes another user's expenses
- [ ] Signed-out `GET /profile?start=2026-09-01` still redirects to `/login`
- [ ] `profile.css` contains no hardcoded hex colours and `profile.html` has no `<style>` tags
- [ ] All existing tests in `tests/test_profile.py` and `tests/test_backend_connection.py` still pass
