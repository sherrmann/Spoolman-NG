"""filament_image.

Revision ID: d9c4e7f2a8b3
Revises: b6e2d8a4c1f7
Create Date: 2026-07-21 12:00:00.000000

Adds the ``image`` table for user-uploaded reference photos (#88), stored as DB blobs so every
existing backup path (SQLite file rotation, external-DB dumps) captures them without doc changes,
plus a nullable ``filament.image_id`` pointer. The bytes live in their own table so filament
list/find queries never touch them, and so vendor/spool photos can reuse the table later. The blob
column carries a LONGBLOB variant on MySQL/MariaDB because plain LargeBinary maps to a 64 KB BLOB
there. Like ``spool.printer_id``, the pointer is a plain nullable column with no DB-level foreign
key (the image row lifecycle is managed in the application layer), so both statements are safe
under CockroachDB's transactional DDL and SQLite never rewrites the filament table.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

# revision identifiers, used by Alembic.
revision = "d9c4e7f2a8b3"
down_revision = "b6e2d8a4c1f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the image table and the filament.image_id pointer."""
    op.create_table(
        "image",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_image_id"), "image", ["id"], unique=False)
    op.add_column("filament", sa.Column("image_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the filament.image_id pointer and the image table."""
    op.drop_column("filament", "image_id")
    op.drop_index(op.f("ix_image_id"), table_name="image")
    op.drop_table("image")
