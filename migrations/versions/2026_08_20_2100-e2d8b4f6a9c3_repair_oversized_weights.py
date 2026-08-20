"""Repair weight values too large for the client to read back as numbers.

Revision ID: e2d8b4f6a9c3
Revises: c1f7a9e4d2b8
Create Date: 2026-08-20 21:00:00.000000

Follow-up to #377/#383. That fix closed the path that *created* these values — the client no longer
turns a noisy float into a string and concatenates weight totals, and ``used_weight`` is rounded on
every write — but it shipped no repair, so a row poisoned before that release is still sitting in
the database.

The class repaired here is values whose magnitude exceeds JavaScript's ``Number.MAX_SAFE_INTEGER``
(9007199254740991). That bound is not arbitrary: it is exactly where the browser's deserializer
still hands back a *string* rather than a number, because that is the rule which keeps oversized
CockroachDB ids exact (#69) and it is applied per value, not per field. A weight in that range
therefore re-triggers the original defect on read — ``sum + weight`` becomes concatenation — no
matter how it got there. It is also physically absurd on its face: 9e15 grams is nine billion
tonnes, so no legitimate row can be caught by this.

Poisoned values are **cleared, not corrected**. The true value is unrecoverable, and inventing a
plausible-looking number would bury the damage where nobody would ever question it; a blank field
gets noticed and fixed, a wrong one does not. Nullable columns become NULL ("unknown" — a state
every one of these columns and the UI already handle). The two NOT NULL columns fall back to the
column's natural zero, which is the only bounded value available to them.

Data-only: no DDL, so this applies cleanly under CockroachDB's transactional DDL. The downgrade is
deliberately a no-op — the discarded values cannot be reconstructed, and pretending otherwise would
be worse than admitting the migration is one-way.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "e2d8b4f6a9c3"
down_revision = "c1f7a9e4d2b8"
branch_labels = None
depends_on = None

# JavaScript's Number.MAX_SAFE_INTEGER — see the module docstring for why this specific bound.
MAX_SAFE_INTEGER = 9007199254740991

# (table, column, replacement). NULL wherever the column is nullable; 0 for the two NOT NULL
# columns, which have no "unknown" to fall back to.
_WEIGHT_COLUMNS = (
    ("vendor", "empty_spool_weight", "NULL"),
    ("filament", "weight", "NULL"),
    ("filament", "spool_weight", "NULL"),
    ("spool", "initial_weight", "NULL"),
    ("spool", "spool_weight", "NULL"),
    ("spool", "used_weight", "0"),
    ("spool_usage_event", "measured_weight", "NULL"),
    ("spool_usage_event", "delta", "0"),
)


def upgrade() -> None:
    """Clear every weight value beyond the safe-integer range."""
    for table, column, replacement in _WEIGHT_COLUMNS:
        # ABS() is available on every supported backend. The IS NOT NULL guard keeps the statement
        # a no-op on the overwhelmingly common case of a database with nothing wrong with it.
        # S608: the table/column/replacement names are literals from the tuple above, never input.
        op.execute(
            f"UPDATE {table} SET {column} = {replacement} "  # noqa: S608
            # `col != col` is the portable NaN test: every comparison against NaN is false, so
            # the ABS() bound alone never matches one. SQLite coerces NaN to NULL on write, but
            # PostgreSQL stores it, and it breaks response rendering exactly like inf does.
            f"WHERE {column} IS NOT NULL "
            f"AND (ABS({column}) > {MAX_SAFE_INTEGER} OR {column} != {column})",
        )


def downgrade() -> None:
    """No-op: the cleared values are unrecoverable."""
