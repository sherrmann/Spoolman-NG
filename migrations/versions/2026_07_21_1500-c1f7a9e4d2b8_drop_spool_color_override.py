"""Drop the per-spool color override (revert of #74).

Removes the three ``spool`` columns added by e6a2c4f8d1b3 — color_hex, multi_color_hexes and
multi_color_direction. Color is an intrinsic property of a filament product, so it is modelled
only on ``filament``; the per-spool override was a second, conflicting source of truth for the
same attribute. Reverting it leaves the filament color as the single source, and the "different
color of the same filament" workflow is served by cloning the filament instead.

Unlike the #298/#309 order-field revert, these columns shipped in a release, so any override a
user stored is discarded when this upgrade runs (the effective swatch simply falls back to the
filament color, which is what an unset override already did). The add-columns revision
e6a2c4f8d1b3 is kept as a graph node so both paths converge on the same schema:

  * fresh install:  …d5f9a1c3e7b2 -> e6a2c4f8d1b3 (adds cols) -> … -> c1f7a9e4d2b8 (drops cols)
  * upgraded install: sits on e6a2c4f8d1b3 (has cols) -> … -> c1f7a9e4d2b8 (drops cols)

Whenever this upgrade runs the columns are guaranteed present, so the drops need no existence
guard. Plain metadata-only DROP COLUMNs, safe on every supported backend.

Revision ID: c1f7a9e4d2b8
Revises: d9c4e7f2a8b3
Create Date: 2026-07-21 15:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1f7a9e4d2b8"
down_revision = "d9c4e7f2a8b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the multi_color_direction, multi_color_hexes and color_hex columns from spool."""
    op.drop_column("spool", "multi_color_direction")
    op.drop_column("spool", "multi_color_hexes")
    op.drop_column("spool", "color_hex")


def downgrade() -> None:
    """Re-add the color_hex, multi_color_hexes and multi_color_direction columns to spool."""
    op.add_column("spool", sa.Column("color_hex", sa.String(length=8), nullable=True))
    op.add_column("spool", sa.Column("multi_color_hexes", sa.String(length=128), nullable=True))
    op.add_column("spool", sa.Column("multi_color_direction", sa.String(length=16), nullable=True))
