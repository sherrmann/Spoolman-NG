"""nfc_tag_rehome.

Revision ID: d6f2a8c4e1b9
Revises: a7f3c9e1d5b4
Create Date: 2026-08-26 13:00:00.000000

Re-homes this fork's NFC tag bindings from the `spool_field` extra-field table
(key="nfc_tag_id") onto the `tag` table added by a7f3c9e1d5b4, which is upstream-shaped and
keyed on a tag's real hardware UID. spoolman.api.v1.nfc and the *_lookup.py modules now read
and write exclusively through `tag`; this migration carries forward what pre-existing
`nfc_tag_id` data CAN mean under that scheme.

Only Qidi bindings recover. A Qidi `nfc_tag_id` value ("qidi_{hex}") IS the tag's MIFARE UID
with a prefix (see spoolman.qidi_lookup.make_nfc_tag_id), so it converts to a real `tag` row:
uid=hex (renormalized the same way the runtime does), format="qidi".

TigerTag ("tigertag_{product}_{timestamp}"), OpenPrintTag-shaped values, and payload-hash
values ("{format}_payload_{sha256[:24]}") never contained a physical UID -- they cannot become
`tag` rows and nothing here invents one. Their `spool_field` rows are left exactly as they
are, not deleted; they simply stop being read. A spool bound only that way needs one rescan.

No schema change: the `tag` table already has everything this needs (uid, format, spool_id),
and per the fork's own decision the table stays byte-for-byte what upstream defines -- no
fork-owned column. Purely additive/data-only, so it applies cleanly under CockroachDB's
transactional DDL rules for DDL-vs-DML separation (there is no DDL here to separate from).

Idempotent: a uid already present in `tag` is skipped, never overwritten or duplicated, so a
downgrade-then-upgrade round trip (or any other re-run) converts the same rows and no more.

downgrade() removes only the rows this migration itself created. It identifies them by the
`spool_field` row that must still be sitting untouched at (spool_id, key="nfc_tag_id") with a
value that normalizes to that tag's own uid -- exactly the pairing this migration reads to
create the row, and a pairing no code post-migration can produce, since nothing writes that
field any longer.
"""

import logging
from datetime import datetime

import sqlalchemy as sa
from alembic import op

from spoolman.tags import normalize_uid

# revision identifiers, used by Alembic.
revision = "d6f2a8c4e1b9"
down_revision = "a7f3c9e1d5b4"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

QIDI_PREFIX = "qidi_"
QIDI_FORMAT = "qidi"

tag_table = sa.table(
    "tag",
    sa.column("id", sa.Integer),
    sa.column("uid", sa.String),
    sa.column("target_type", sa.String),
    sa.column("spool_id", sa.Integer),
    sa.column("format", sa.String),
    sa.column("added", sa.DateTime),
)
spool_field_table = sa.table(
    "spool_field",
    sa.column("spool_id", sa.Integer),
    sa.column("key", sa.String),
    sa.column("value", sa.String),
)


def upgrade() -> None:
    """Convert recoverable (Qidi) nfc_tag_id bindings into real tag rows; leave the rest."""
    conn = op.get_bind()
    existing_uids = {row.uid for row in conn.execute(sa.select(tag_table.c.uid)).all()}

    rows = conn.execute(
        sa.select(spool_field_table.c.spool_id, spool_field_table.c.value).where(
            spool_field_table.c.key == "nfc_tag_id",
        ),
    ).all()

    converted = 0
    left_behind = 0
    now = datetime.utcnow().replace(microsecond=0)

    for row in rows:
        value = row.value
        if not value or not value.startswith(QIDI_PREFIX):
            left_behind += 1
            continue

        try:
            uid = normalize_uid(value[len(QIDI_PREFIX) :])
        except ValueError:
            # Prefixed like a Qidi binding but not actually recoverable hex -- leave it.
            left_behind += 1
            continue

        if uid in existing_uids:
            # Already converted (idempotent re-run), or some other row already claims this
            # UID -- never overwrite either way.
            continue

        conn.execute(
            sa.insert(tag_table).values(
                uid=uid,
                target_type="spool",
                spool_id=row.spool_id,
                format=QIDI_FORMAT,
                added=now,
            ),
        )
        existing_uids.add(uid)
        converted += 1

    logger.info(
        "nfc_tag_id rehome: converted %d Qidi binding(s) to tag rows; left %d binding(s) in "
        "place with no recoverable UID (those spools need one rescan).",
        converted,
        left_behind,
    )


def downgrade() -> None:
    """Remove only the tag rows this migration created; the untouched spool_field rows remain."""
    conn = op.get_bind()

    # (spool_id -> {uid, ...}) for every still-present, still-unread nfc_tag_id binding that
    # normalizes to a Qidi UID. Built the same way upgrade() builds it, so it identifies
    # exactly the pairing upgrade() would (re-)create.
    qidi_bindings: dict[int, set[str]] = {}
    for row in conn.execute(
        sa.select(spool_field_table.c.spool_id, spool_field_table.c.value).where(
            spool_field_table.c.key == "nfc_tag_id",
            spool_field_table.c.value.like(f"{QIDI_PREFIX}%"),
        ),
    ).all():
        try:
            uid = normalize_uid(row.value[len(QIDI_PREFIX) :])
        except ValueError:
            continue
        qidi_bindings.setdefault(row.spool_id, set()).add(uid)

    removed = 0
    for row in conn.execute(
        sa.select(tag_table.c.id, tag_table.c.uid, tag_table.c.spool_id).where(tag_table.c.format == QIDI_FORMAT),
    ).all():
        if row.uid in qidi_bindings.get(row.spool_id, set()):
            conn.execute(sa.delete(tag_table).where(tag_table.c.id == row.id))
            removed += 1

    logger.info("nfc_tag_id rehome downgrade: removed %d tag row(s) created by this migration.", removed)
