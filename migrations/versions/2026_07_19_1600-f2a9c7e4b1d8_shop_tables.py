"""shop_tables.

Revision ID: f2a9c7e4b1d8
Revises: d4e7a1b9c6f2
Create Date: 2026-07-19 16:00:00.000000

Adds the first-class ``shop`` table (#298): where a reorder is placed, distinct from the manufacturer
Vendor. ``name`` is unique; ``ships_to`` is a comma-separated region list in a Text column (no JSON
columns in this schema). Purely additive — nothing existing references it.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f2a9c7e4b1d8"
down_revision = "d4e7a1b9c6f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the shop table."""
    op.create_table(
        "shop",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("homepage", sa.String(length=1024), nullable=True),
        sa.Column("ships_to", sa.Text(), nullable=True),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shop_id"), "shop", ["id"], unique=False)
    op.create_index(op.f("ix_shop_name"), "shop", ["name"], unique=True)


def downgrade() -> None:
    """Drop the shop table."""
    op.drop_index(op.f("ix_shop_name"), table_name="shop")
    op.drop_index(op.f("ix_shop_id"), table_name="shop")
    op.drop_table("shop")
