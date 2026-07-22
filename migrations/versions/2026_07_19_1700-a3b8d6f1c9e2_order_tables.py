"""order_tables.

Revision ID: a3b8d6f1c9e2
Revises: f2a9c7e4b1d8
Create Date: 2026-07-19 17:00:00.000000

Adds the ``purchase_order`` and ``order_line`` tables (#298). Table name ``purchase_order`` because
``order`` is a reserved SQL word (same reasoning as ``user_account``). A line's ``arrived_at`` is
per-line to support split shipments. ``order_line.order_id`` cascades on order delete; the filament
FK does not cascade (filament delete is restricted in the application layer while a line references
it). Purely additive.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b8d6f1c9e2"
down_revision = "f2a9c7e4b1d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the purchase_order and order_line tables."""
    op.create_table(
        "purchase_order",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=True),
        sa.Column("ordered_at", sa.DateTime(), nullable=False),
        sa.Column("order_number", sa.String(length=256), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shop.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_purchase_order_id"), "purchase_order", ["id"], unique=False)

    op.create_table(
        "order_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("filament_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_per_unit", sa.Float(), nullable=True),
        sa.Column("arrived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_order.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filament_id"], ["filament.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_line_id"), "order_line", ["id"], unique=False)
    op.create_index(op.f("ix_order_line_order_id"), "order_line", ["order_id"], unique=False)


def downgrade() -> None:
    """Drop the order_line and purchase_order tables."""
    # No explicit drop_index: MySQL/MariaDB refuse to drop an index a foreign key still
    # needs (errno 1553), so let DROP TABLE remove the indexes on every backend.
    op.drop_table("order_line")
    op.drop_table("purchase_order")
