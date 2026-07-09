"""location_tables.

Revision ID: b3d9e1f2a4c7
Revises: f1a8c4d2b9e7
Create Date: 2026-07-09 12:00:00.000000

Promotes locations to a first-class entity (issue #103): a ``location`` name registry plus a
``location_field`` side-table for custom fields, mirroring the vendor/filament/spool + ``*_field``
pattern. ``Spool.location`` stays a plain string column and the existing ``/location`` string
endpoints are unchanged, so this is parallel and additive. The backfill of the existing distinct
locations is a SEPARATE migration because CockroachDB runs each migration in its own transaction
and rejects DML against a table created in the same transaction.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b3d9e1f2a4c7"
down_revision = "f1a8c4d2b9e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the location and location_field tables."""
    op.create_table(
        "location",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_location_id"), "location", ["id"], unique=False)

    op.create_table(
        "location_field",
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("location_id", "key"),
    )
    op.create_index(op.f("ix_location_field_location_id"), "location_field", ["location_id"], unique=False)
    op.create_index(op.f("ix_location_field_key"), "location_field", ["key"], unique=False)


def downgrade() -> None:
    """Drop the location_field and location tables."""
    op.drop_index(op.f("ix_location_field_key"), table_name="location_field")
    op.drop_index(op.f("ix_location_field_location_id"), table_name="location_field")
    op.drop_table("location_field")
    op.drop_index(op.f("ix_location_id"), table_name="location")
    op.drop_table("location")
