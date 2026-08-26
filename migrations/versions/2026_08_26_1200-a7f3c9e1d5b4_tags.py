"""tags.

Revision ID: a7f3c9e1d5b4
Revises: e2d8b4f6a9c3
Create Date: 2026-08-26 12:00:00.000000

Ported from upstream Donkie/Spoolman's fe4970567bb3, under a fork-owned revision id: this
fork's chain diverged before that revision was cut, so the id is invented fresh rather than
reused. The table shape (columns, indexes, FK ondelete behaviour) is identical to upstream's.

Purely additive: one new table, no existing column touched. See spoolman.database.models.Tag
for the full reasoning behind the schema.

This table is intentionally NOT wired to this fork's existing NFC subsystem, which links a
tag to a spool via the `nfc_tag_uid` extra field instead. The two coexist for now.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7f3c9e1d5b4"
down_revision = "e2d8b4f6a9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the tag table mapping physical NFC/RFID tag UIDs to what they identify."""
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("spool_id", sa.Integer(), nullable=True),
        sa.Column("filament_id", sa.Integer(), nullable=True),
        sa.Column("target_value", sa.String(length=64), nullable=True),
        sa.Column("format", sa.String(length=32), nullable=True),
        sa.Column("added", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["spool_id"],
            ["spool.id"],
        ),
        # Filament tags have no ORM relationship yet (nothing writes them), so the
        # database is what stops a deleted filament leaving tag rows behind.
        sa.ForeignKeyConstraint(
            ["filament_id"],
            ["filament.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tag_id"), "tag", ["id"], unique=False)
    op.create_index(op.f("ix_tag_spool_id"), "tag", ["spool_id"], unique=False)
    op.create_index(op.f("ix_tag_filament_id"), "tag", ["filament_id"], unique=False)
    # The whole point of the table: one physical tag means exactly one thing, enforced by
    # the database rather than by whichever client happened to write last.
    op.create_index(op.f("ix_tag_uid"), "tag", ["uid"], unique=True)


def downgrade() -> None:
    """Perform the downgrade."""
    op.drop_index(op.f("ix_tag_uid"), table_name="tag")
    op.drop_index(op.f("ix_tag_filament_id"), table_name="tag")
    op.drop_index(op.f("ix_tag_spool_id"), table_name="tag")
    op.drop_index(op.f("ix_tag_id"), table_name="tag")
    op.drop_table("tag")
