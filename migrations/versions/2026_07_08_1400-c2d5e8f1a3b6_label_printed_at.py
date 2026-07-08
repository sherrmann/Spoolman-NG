"""Add label_printed_at tracking to spool and filament.

Revision ID: c2d5e8f1a3b6
Revises: a1f4c7b9d2e3
Create Date: 2026-07-08 14:00:00.000000

Records when a label was last printed for a spool or filament (issue #93, extended to
filaments by #755). Both columns are nullable and default to NULL ("never printed"), so
existing rows and integrations are unaffected. Two plain nullable ADD COLUMNs — safe to
apply together under CockroachDB's transactional DDL (no backfill, no default, no type
change).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c2d5e8f1a3b6"
down_revision = "a1f4c7b9d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Perform the upgrade."""
    op.add_column("spool", sa.Column("label_printed_at", sa.DateTime(), nullable=True))
    op.add_column("filament", sa.Column("label_printed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Perform the downgrade."""
    op.drop_column("filament", "label_printed_at")
    op.drop_column("spool", "label_printed_at")
