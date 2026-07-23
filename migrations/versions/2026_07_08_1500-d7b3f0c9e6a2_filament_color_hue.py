"""Add a precomputed color_hue column to filament for colour sorting.

Revision ID: d7b3f0c9e6a2
Revises: c2d5e8f1a3b6
Create Date: 2026-07-08 15:00:00.000000

Adds a single nullable ``color_hue`` column holding the hue (degrees, 0-360) derived from a
filament's ``color_hex``/``multi_color_hexes`` so the lists can sort by colour (issue #113). The
column is server-managed and not exposed on the API, so existing rows and integrations are
unaffected (NULL = no colour / not yet computed). A plain nullable ADD COLUMN with no default or
backfill, so it applies cleanly under CockroachDB's transactional DDL; the backfill of existing
rows is a separate migration (CockroachDB rejects DML against a column added in the same
transaction).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d7b3f0c9e6a2"
down_revision = "c2d5e8f1a3b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the color_hue column to filament."""
    op.add_column("filament", sa.Column("color_hue", sa.Float(), nullable=True))


def downgrade() -> None:
    """Drop the color_hue column from filament."""
    op.drop_column("filament", "color_hue")
