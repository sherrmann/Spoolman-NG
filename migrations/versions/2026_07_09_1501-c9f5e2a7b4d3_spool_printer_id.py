"""spool_printer_id.

Revision ID: c9f5e2a7b4d3
Revises: b8e4d1f6a3c2
Create Date: 2026-07-09 15:01:00.000000

Adds the optional ``spool.printer_id`` link so a spool can be assigned to a printer (issue #75).
A single plain nullable ADD COLUMN — no default, no backfill, no DB-level foreign key (referential
integrity is enforced in the application layer, and printer deletion unassigns referencing spools),
so it is safe under CockroachDB's transactional DDL and never rewrites the central spool table on
SQLite. NULL means "not assigned to any printer", so existing rows and integrations are unaffected.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c9f5e2a7b4d3"
down_revision = "b8e4d1f6a3c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Perform the upgrade."""
    op.add_column("spool", sa.Column("printer_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Perform the downgrade."""
    op.drop_column("spool", "printer_id")
