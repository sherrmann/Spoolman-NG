"""Add manufacturer extruder/bed temperature ranges to filaments.

Revision ID: f7b3a1c5d2e4
Revises: e6a2c4f8d1b3
Create Date: 2026-07-09 14:00:00.000000

Filaments only stored a single recommended extruder/bed temperature (settings_extruder_temp /
settings_bed_temp), yet manufacturers publish a recommended *range* and the fork's own 3D Filament
Profiles importer already parses temp_min/temp_max before collapsing them to a midpoint (issue
#112). Add four optional nullable columns holding the min/max of each range. NULL means "no range
recorded"; the existing single-value columns are untouched, so every API consumer (Moonraker,
OctoPrint, Home Assistant) is unaffected and the change is purely additive. Safe under CockroachDB's
transactional DDL: four plain nullable ADD COLUMNs, no default, no backfill, no type change.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f7b3a1c5d2e4"
down_revision = "e6a2c4f8d1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the extruder/bed temperature range columns to filament."""
    op.add_column("filament", sa.Column("settings_extruder_temp_min", sa.Integer(), nullable=True))
    op.add_column("filament", sa.Column("settings_extruder_temp_max", sa.Integer(), nullable=True))
    op.add_column("filament", sa.Column("settings_bed_temp_min", sa.Integer(), nullable=True))
    op.add_column("filament", sa.Column("settings_bed_temp_max", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the extruder/bed temperature range columns from filament."""
    op.drop_column("filament", "settings_bed_temp_max")
    op.drop_column("filament", "settings_bed_temp_min")
    op.drop_column("filament", "settings_extruder_temp_max")
    op.drop_column("filament", "settings_extruder_temp_min")
