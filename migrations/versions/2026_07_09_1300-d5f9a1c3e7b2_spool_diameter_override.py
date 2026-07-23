"""Add a per-spool filament diameter override.

Revision ID: d5f9a1c3e7b2
Revises: c4e8f2a3b5d9
Create Date: 2026-07-09 13:00:00.000000

A measured, per-spool filament diameter that overrides the parent filament's nominal diameter in
length math, since actual diameter varies roll-to-roll (issue #101). A single plain nullable ADD
COLUMN — NULL means "use the filament's diameter", so existing rows and integrations are unaffected
and length calculations only change for spools that opt in. Safe under CockroachDB's transactional
DDL (no backfill, no default, no type change).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d5f9a1c3e7b2"
down_revision = "c4e8f2a3b5d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the diameter column to spool."""
    op.add_column("spool", sa.Column("diameter", sa.Float(), nullable=True))


def downgrade() -> None:
    """Drop the diameter column from spool."""
    op.drop_column("spool", "diameter")
