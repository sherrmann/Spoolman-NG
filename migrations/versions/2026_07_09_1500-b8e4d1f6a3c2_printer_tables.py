"""printer_tables.

Revision ID: b8e4d1f6a3c2
Revises: a2c6e9f4b1d8
Create Date: 2026-07-09 15:00:00.000000

Promotes printers to a first-class entity (issue #75 / #26): a ``printer`` registry plus a
``printer_field`` side-table for custom fields, mirroring the vendor/filament/spool/location +
``*_field`` pattern. The optional ``spool.printer_id`` link is added in a separate follow-up
migration so this file only creates new tables (safe under CockroachDB's transactional DDL). Purely
additive — nothing references these tables yet.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8e4d1f6a3c2"
down_revision = "a2c6e9f4b1d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the printer and printer_field tables."""
    op.create_table(
        "printer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_printer_id"), "printer", ["id"], unique=False)

    op.create_table(
        "printer_field",
        sa.Column("printer_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["printer_id"], ["printer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("printer_id", "key"),
    )
    op.create_index(op.f("ix_printer_field_printer_id"), "printer_field", ["printer_id"], unique=False)
    op.create_index(op.f("ix_printer_field_key"), "printer_field", ["key"], unique=False)


def downgrade() -> None:
    """Drop the printer_field and printer tables."""
    op.drop_index(op.f("ix_printer_field_key"), table_name="printer_field")
    op.drop_index(op.f("ix_printer_field_printer_id"), table_name="printer_field")
    op.drop_table("printer_field")
    op.drop_index(op.f("ix_printer_id"), table_name="printer")
    op.drop_table("printer")
