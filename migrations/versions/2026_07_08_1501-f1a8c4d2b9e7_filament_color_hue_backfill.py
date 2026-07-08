"""Backfill filament.color_hue from existing colours.

Revision ID: f1a8c4d2b9e7
Revises: d7b3f0c9e6a2
Create Date: 2026-07-08 15:01:00.000000

Populates the ``color_hue`` column added by the previous migration for filaments that already have
a colour (issue #113). This must be a separate migration from the ADD COLUMN because CockroachDB's
alembic execution runs each migration in its own transaction and rejects DML against a column
created in the same transaction (see the 2024-03-26 spool_weight_population migration for the same
pattern). The hue is computed in Python — the same helper the write path uses — because portable
hue arithmetic in SQL across the four supported dialects is impractical.
"""

import sqlalchemy as sa
from alembic import op

from spoolman.math import color_hex_to_hue

# revision identifiers, used by Alembic.
revision = "f1a8c4d2b9e7"
down_revision = "d7b3f0c9e6a2"
branch_labels = None
depends_on = None

filament = sa.table(
    "filament",
    sa.column("id", sa.Integer),
    sa.column("color_hex", sa.String),
    sa.column("multi_color_hexes", sa.String),
    sa.column("color_hue", sa.Float),
)


def upgrade() -> None:
    """Compute and store the hue of every filament that already has a colour."""
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(filament.c.id, filament.c.color_hex, filament.c.multi_color_hexes),
    ).all()
    for row in rows:
        hue = color_hex_to_hue(row.color_hex, row.multi_color_hexes)
        if hue is not None:
            conn.execute(sa.update(filament).where(filament.c.id == row.id).values(color_hue=hue))


def downgrade() -> None:
    """Clear the backfilled hues (the column itself is dropped by the previous migration)."""
    op.get_bind().execute(sa.update(filament).values(color_hue=None))
