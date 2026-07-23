"""Persist SpoolmanDB catalog descriptors on the local filament.

Revision ID: a2c6e9f4b1d8
Revises: f7b3a1c5d2e4
Create Date: 2026-07-09 14:30:00.000000

The external catalog (ExternalFilament) already carries spool_type, finish, pattern, translucent
and glow, but none of it survived once a filament was imported locally because the Filament table
had no columns for them (issue #91, also #567). Add five optional nullable columns so the import no
longer silently drops that data. spool_type/finish/pattern are short strings holding the catalog
enum values; translucent/glow are nullable booleans (NULL = unknown, distinct from an explicit
False). Purely additive: existing rows and API consumers are unaffected, and the read models omit
these when unset. Safe under CockroachDB's transactional DDL — five plain nullable ADD COLUMNs, no
default, no backfill, no type change.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a2c6e9f4b1d8"
down_revision = "f7b3a1c5d2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the spool_type, finish, pattern, translucent and glow columns to filament."""
    op.add_column("filament", sa.Column("spool_type", sa.String(length=16), nullable=True))
    op.add_column("filament", sa.Column("finish", sa.String(length=16), nullable=True))
    op.add_column("filament", sa.Column("pattern", sa.String(length=16), nullable=True))
    op.add_column("filament", sa.Column("translucent", sa.Boolean(), nullable=True))
    op.add_column("filament", sa.Column("glow", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Drop the spool_type, finish, pattern, translucent and glow columns from filament."""
    op.drop_column("filament", "glow")
    op.drop_column("filament", "translucent")
    op.drop_column("filament", "pattern")
    op.drop_column("filament", "finish")
    op.drop_column("filament", "spool_type")
