"""Add per-filament low-stock threshold and reserve-count fields.

Revision ID: a1f4c7b9d2e3
Revises: e2258ccc175e
Create Date: 2026-07-08 13:30:00.000000

Both columns are nullable and default to NULL (feature off), so existing rows and
integrations are unaffected. Adds:
  - low_stock_threshold: alert when the total remaining weight across a filament's
    spools drops below this many grams (issue #109).
  - reserve_count: number of unopened spare spools kept in reserve, tracked without
    one Spool row per unit (issue #116).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1f4c7b9d2e3"
down_revision = "e2258ccc175e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add low_stock_threshold and reserve_count columns to filament."""
    op.add_column("filament", sa.Column("low_stock_threshold", sa.Float(), nullable=True))
    op.add_column("filament", sa.Column("reserve_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the low_stock_threshold and reserve_count columns from filament."""
    op.drop_column("filament", "reserve_count")
    op.drop_column("filament", "low_stock_threshold")
