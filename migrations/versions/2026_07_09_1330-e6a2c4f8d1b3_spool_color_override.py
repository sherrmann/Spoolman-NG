"""Add a per-spool color override.

Revision ID: e6a2c4f8d1b3
Revises: d5f9a1c3e7b2
Create Date: 2026-07-09 13:30:00.000000

An optional per-spool color that overrides the parent filament's color, so one filament definition
can cover multiple spool colors (issue #74). Three plain nullable ADD COLUMNs mirroring the
filament's color columns; NULL means "use the filament's color", so existing rows and integrations
are unaffected and the override is purely additive. Safe under CockroachDB's transactional DDL (no
backfill, no default, no type change).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e6a2c4f8d1b3"
down_revision = "d5f9a1c3e7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Perform the upgrade."""
    op.add_column("spool", sa.Column("color_hex", sa.String(length=8), nullable=True))
    op.add_column("spool", sa.Column("multi_color_hexes", sa.String(length=128), nullable=True))
    op.add_column("spool", sa.Column("multi_color_direction", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Perform the downgrade."""
    op.drop_column("spool", "multi_color_direction")
    op.drop_column("spool", "multi_color_hexes")
    op.drop_column("spool", "color_hex")
