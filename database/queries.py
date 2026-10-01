"""Read-only query helpers for page views. Pure sqlite3 — no Flask imports."""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from database.db import get_db

NO_VALUE = "—"


# ------------------------------------------------------------------ #
# Shared helpers                                                      #
# ------------------------------------------------------------------ #

def _format_member_since(created_at):
    """Turn a 'YYYY-MM-DD HH:MM:SS' timestamp into 'Month YYYY', or ''."""
    try:
        return datetime.fromisoformat(created_at).strftime("%B %Y")
    except (TypeError, ValueError):
        return ""


def _fetch_category_totals(conn, user_id):
    """Return [(category, total)] for a user, largest first, ties by name.

    Totals are rounded once here so every caller (stats and breakdown)
    works from identical figures.
    """
    rows = conn.execute(
        "SELECT category, ROUND(SUM(amount), 2) AS total "
        "FROM expenses WHERE user_id = ? "
        "GROUP BY category ORDER BY total DESC, category ASC",
        (user_id,),
    ).fetchall()
    return [(row["category"], round(float(row["total"]), 2)) for row in rows]


# ------------------------------------------------------------------ #
# User                                                                #
# ------------------------------------------------------------------ #

def get_user_by_id(user_id):
    """Return {name, email, member_since} for a user, or None if missing."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "name": row["name"],
        "email": row["email"],
        "member_since": _format_member_since(row["created_at"]),
    }


# --- SUBAGENT A: transactions --------------------------------------- #

def get_recent_transactions(user_id, limit=10):
    """Return the user's most recent expenses, newest first."""
    if limit <= 0:
        # SQLite treats a negative LIMIT as "no limit", so short-circuit.
        return []
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT date, description, category, amount "
            "FROM expenses WHERE user_id = ? "
            "ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "date": row["date"],
            "description": row["description"] or NO_VALUE,
            "category": row["category"],
            "amount": round(float(row["amount"]), 2),
        }
        for row in rows
    ]


# --- SUBAGENT B: summary stats -------------------------------------- #

def get_summary_stats(user_id):
    """Return {total_spent, transaction_count, top_category} for a user."""
    conn = get_db()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        totals = _fetch_category_totals(conn, user_id)
    finally:
        conn.close()
    return {
        "total_spent": float(round(sum(amount for _, amount in totals), 2)),
        "transaction_count": int(count),
        "top_category": totals[0][0] if totals else NO_VALUE,
    }


# --- SUBAGENT C: category breakdown --------------------------------- #

def _allocate_pct(amounts):
    """Integer percentages summing to 100; the largest absorbs the remainder."""
    total = sum(Decimal(str(a)) for a in amounts)
    if total <= 0:
        return [0] * len(amounts)
    pcts = [
        int(
            (Decimal(str(a)) * 100 / total).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        for a in amounts
    ]
    pcts[0] += 100 - sum(pcts)
    return pcts


def get_category_breakdown(user_id):
    """Return [{name, amount, pct}] for a user, largest category first."""
    conn = get_db()
    try:
        totals = _fetch_category_totals(conn, user_id)
    finally:
        conn.close()
    pcts = _allocate_pct([amount for _, amount in totals])
    return [
        {"name": name, "amount": amount, "pct": pct}
        for (name, amount), pct in zip(totals, pcts)
    ]
