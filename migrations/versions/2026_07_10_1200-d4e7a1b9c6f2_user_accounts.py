"""user_accounts.

Revision ID: d4e7a1b9c6f2
Revises: c9f5e2a7b4d3
Create Date: 2026-07-10 12:00:00.000000

Adds the optional user-accounts table for password login and admin/read-only roles (issue #52).
Named ``user_account`` because ``user`` is a reserved word in PostgreSQL/MySQL. Purely additive — a
single new table, nothing references it, and accounts stay dormant until an admin is created, so the
default deployment is unchanged.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e7a1b9c6f2"
down_revision = "c9f5e2a7b4d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the user_account table."""
    op.create_table(
        "user_account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_account_id"), "user_account", ["id"], unique=False)
    op.create_index(op.f("ix_user_account_username"), "user_account", ["username"], unique=True)


def downgrade() -> None:
    """Drop the user_account table."""
    op.drop_index(op.f("ix_user_account_username"), table_name="user_account")
    op.drop_index(op.f("ix_user_account_id"), table_name="user_account")
    op.drop_table("user_account")
