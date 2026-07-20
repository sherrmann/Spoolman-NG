"""Merge the orders chain and the #317 edge-recovery chain.

Two independent PRs branched from d4e7a1b9c6f2: the Orders/Shops tables
(f2a9c7e4b1d8 -> a3b8d6f1c9e2, PR #318) and the edge-DB recovery for the
reverted #309 filament columns (e8b3c6d9f2a5 -> f4c9a2e7b1d8, PR #317).
Both end at the same filament schema and touch disjoint tables, so this
merge revision has no operations — it only rejoins the revision graph to
a single head.

Revision ID: b6e2d8a4c1f7
Revises: a3b8d6f1c9e2, f4c9a2e7b1d8
Create Date: 2026-07-20 21:30:00.000000
"""

# revision identifiers, used by Alembic.
revision = "b6e2d8a4c1f7"
down_revision = ("a3b8d6f1c9e2", "f4c9a2e7b1d8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Graph merge only — no schema operations."""


def downgrade() -> None:
    """Graph merge only — no schema operations."""
