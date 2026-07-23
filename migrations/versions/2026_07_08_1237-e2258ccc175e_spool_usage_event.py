"""spool_usage_event.

Revision ID: e2258ccc175e
Revises: e7a41c9d2b53
Create Date: 2026-07-08 12:37:16.188366
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2258ccc175e"
down_revision = "e7a41c9d2b53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the spool_usage_event table and its indexes."""
    op.create_table(
        "spool_usage_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("spool_id", sa.Integer(), nullable=False),
        sa.Column("time", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("measured_weight", sa.Float(), nullable=True),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["spool_id"], ["spool.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_spool_usage_event_id"), "spool_usage_event", ["id"], unique=False)
    op.create_index(op.f("ix_spool_usage_event_spool_id"), "spool_usage_event", ["spool_id"], unique=False)
    op.create_index(op.f("ix_spool_usage_event_time"), "spool_usage_event", ["time"], unique=False)
    # Ordering index for the per-spool history query, and a uniqueness guard for idempotency keys.
    # NULL idempotency_key values are distinct in a unique index on all four backends, so keyless
    # events (the default) never collide.
    op.create_index(
        "ix_spool_usage_event_spool_time",
        "spool_usage_event",
        ["spool_id", "time"],
        unique=False,
    )
    op.create_index(
        "uq_spool_usage_event_idempotency",
        "spool_usage_event",
        ["spool_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the spool_usage_event table and its indexes."""
    op.drop_index("uq_spool_usage_event_idempotency", table_name="spool_usage_event")
    op.drop_index("ix_spool_usage_event_spool_time", table_name="spool_usage_event")
    op.drop_index(op.f("ix_spool_usage_event_time"), table_name="spool_usage_event")
    op.drop_index(op.f("ix_spool_usage_event_spool_id"), table_name="spool_usage_event")
    op.drop_index(op.f("ix_spool_usage_event_id"), table_name="spool_usage_event")
    op.drop_table("spool_usage_event")
