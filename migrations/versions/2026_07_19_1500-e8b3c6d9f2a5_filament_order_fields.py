"""filament order fields (#298).

Three nullable columns on filament for the first-class 'ordered' state: ordered_at
(when the replenishment order was placed — doubles as the boolean and the order's
age), order_url (the shop/bulk-order link) and order_note (free text). Plain
additive ADD COLUMNs with no default or backfill, so the migration is metadata-only
and safe on every supported backend including CockroachDB.

These columns were reverted before release (superseded by first-class Orders & Shops,
#311). This revision is retained — rather than deleted — because ``:edge`` deployments
already stamped their database at ``e8b3c6d9f2a5``; removing the file leaves Alembic
unable to locate that revision ("Can't locate revision identified by 'e8b3c6d9f2a5'")
and startup migrations fail. The follow-up revision f4c9a2e7b1d8 drops the columns again,
so every database — fresh or already at this revision — converges to the same clean head.

Revision ID: e8b3c6d9f2a5
Revises: d4e7a1b9c6f2
Create Date: 2026-07-19 15:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e8b3c6d9f2a5"
down_revision = "d4e7a1b9c6f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the ordered_at, order_url and order_note columns to filament."""
    op.add_column("filament", sa.Column("ordered_at", sa.DateTime(), nullable=True))
    op.add_column("filament", sa.Column("order_url", sa.String(length=1024), nullable=True))
    op.add_column("filament", sa.Column("order_note", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    """Drop the ordered_at, order_url and order_note columns from filament."""
    op.drop_column("filament", "order_note")
    op.drop_column("filament", "order_url")
    op.drop_column("filament", "ordered_at")
