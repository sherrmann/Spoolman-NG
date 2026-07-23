"""drop filament order fields (revert of #298/#309).

Removes the three ``filament`` columns added by e8b3c6d9f2a5 — ordered_at, order_url and
order_note — which were reverted before release (#311) in favour of first-class Orders &
Shops. e8b3c6d9f2a5 is kept as a graph node so Alembic can still locate the revision that
``:edge`` databases were already stamped at; this revision then drops the columns, so both
paths converge on the same schema:

  * fresh install:        d4e7a1b9c6f2 -> e8b3c6d9f2a5 (adds cols) -> f4c9a2e7b1d8 (drops cols)
  * already-deployed edge: sits at e8b3c6d9f2a5 (has cols) -> f4c9a2e7b1d8 (drops cols)

Whenever this upgrade runs the columns are guaranteed present, so the drops need no
existence guard. Plain metadata-only DROP COLUMNs, safe on every supported backend.

Revision ID: f4c9a2e7b1d8
Revises: e8b3c6d9f2a5
Create Date: 2026-07-20 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4c9a2e7b1d8"
down_revision = "e8b3c6d9f2a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the ordered_at, order_url and order_note columns from filament."""
    op.drop_column("filament", "order_note")
    op.drop_column("filament", "order_url")
    op.drop_column("filament", "ordered_at")


def downgrade() -> None:
    """Re-add the ordered_at, order_url and order_note columns to filament."""
    op.add_column("filament", sa.Column("ordered_at", sa.DateTime(), nullable=True))
    op.add_column("filament", sa.Column("order_url", sa.String(length=1024), nullable=True))
    op.add_column("filament", sa.Column("order_note", sa.String(length=1024), nullable=True))
