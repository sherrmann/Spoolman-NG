"""location_backfill.

Revision ID: c4e8f2a3b5d9
Revises: b3d9e1f2a4c7
Create Date: 2026-07-09 12:01:00.000000

Backfills the location registry (issue #103) with one row per DISTINCT non-blank ``Spool.location``
string already in use, so existing locations are immediately manageable as entities. Separate from
the CREATE TABLE migration because CockroachDB runs each migration in its own transaction and
rejects DML against a table created in the same transaction (see the ``f1a8c4d2b9e7`` color_hue
backfill and the ``304a32906234`` spool_weight_population migration for the same pattern).
Idempotent: only inserts names not already present, so a re-run (e.g. the migration round-trip test)
does not create duplicates.
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4e8f2a3b5d9"
down_revision = "b3d9e1f2a4c7"
branch_labels = None
depends_on = None

location = sa.table(
    "location",
    sa.column("id", sa.Integer),
    sa.column("registered", sa.DateTime),
    sa.column("name", sa.String),
)
spool = sa.table(
    "spool",
    sa.column("location", sa.String),
)


def upgrade() -> None:
    """Insert a location row for each distinct non-blank spool location not already registered."""
    conn = op.get_bind()
    existing = {row.name for row in conn.execute(sa.select(location.c.name)).all()}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = conn.execute(sa.select(spool.c.location).distinct()).all()
    for row in rows:
        loc = row.location
        if loc is None or loc.strip() == "" or loc in existing:
            continue
        existing.add(loc)
        conn.execute(sa.insert(location).values(name=loc, registered=now))


def downgrade() -> None:
    """No-op; backfilled rows can't be told from user rows, and the table is dropped by b3d9e1f2a4c7."""
