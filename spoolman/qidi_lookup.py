"""Qidi tag to Spoolman spool matching, binding, and auto-creation."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spoolman.database import filament as filament_db
from spoolman.database import spool as spool_db
from spoolman.database import tag as tag_db
from spoolman.database import vendor as vendor_db
from spoolman.database.models import Filament, Spool
from spoolman.exceptions import TagConflictError
from spoolman.qidi_codec import (
    MATERIAL_CODE_MAP,
    QidiTagData,
    color_code_from_hex,
    material_code_from_name,
)
from spoolman.tags import normalize_uid

logger = logging.getLogger(__name__)

QIDI_VENDOR_NAME = "Qidi"
QIDI_FORMAT = "qidi"


def make_nfc_tag_id(tag_uid_hex: str) -> str:
    """Build a human-readable Qidi tag identity string from its MIFARE Classic UID.

    Kept only for API-response continuity (`NfcBindResponse.nfc_tag_id`) and for reading
    pre-existing `SpoolField(key="nfc_tag_id")` data during the one-time migration that
    converts it into real `tag` rows. Matching and binding now go entirely through the
    upstream `tag` table, keyed on the UID itself -- see `find_spool_by_qidi_tag` and
    `bind_spool_to_qidi_tag`.
    """
    return f"qidi_{tag_uid_hex.lower()}"


async def bind_spool_to_qidi_tag(db: AsyncSession, spool: Spool, tag_uid_hex: str) -> bool:
    """Bind a spool to a specific Qidi tag by its hardware UID.

    Returns True if a new tag row was created, False if this spool already held it.

    Raises:
        ValueError: If tag_uid_hex is not a valid hexadecimal tag UID.
        TagConflictError: If the UID is already linked to a different spool.

    """
    uid = normalize_uid(tag_uid_hex)
    already = await tag_db.find_spool_by_uid(db, uid)
    if already is not None and already.id == spool.id:
        return False
    await tag_db.link(db=db, spool_id=spool.id, uid=uid, tag_format=QIDI_FORMAT)
    logger.info("Bound spool %d to Qidi tag uid %s", spool.id, uid)
    return True


async def find_spool_by_qidi_tag(
    db: AsyncSession,
    tag_data: QidiTagData,
    tag_uid_hex: str | None = None,
    auto_bind: bool = True,
) -> Spool | None:
    """Find a Spoolman spool matching a Qidi tag.

    Matching strategies (tried in order):
    1. Exact match by this tag's own hardware UID, via the `tag` table.
    2. Fuzzy match by material type + color hex on filament

    When auto_bind is True and a spool is found via strategy 2, and a UID is known, that UID
    is bound to the spool for future exact matches.

    Args:
        db: Database session.
        tag_data: Decoded Qidi tag data.
        tag_uid_hex: Hex-encoded MIFARE Classic UID (e.g. "A1B2C3D4").
        auto_bind: Automatically bind unbound tags to matched spools.

    Returns:
        The matched spool, or None if no match found.

    """
    uid = None
    if tag_uid_hex:
        try:
            uid = normalize_uid(tag_uid_hex)
        except ValueError:
            uid = None

    if uid is not None:
        # Strategy 1: exact match by this physical tag's own UID.
        spool = await tag_db.find_spool_by_uid(db, uid)
        if spool is not None:
            logger.debug("Qidi exact match: spool %d via tag uid %s", spool.id, uid)
            return spool

    # Strategy 2: Fuzzy match by material + color on filament
    color_hex = tag_data.color_hex.lower()
    material_type = tag_data.material_type

    stmt = (
        select(Spool)
        .join(Spool.filament)
        .options(
            selectinload(Spool.filament).selectinload(Filament.vendor),
            selectinload(Spool.extra),
        )
        .where(Filament.material == material_type)
        # Compare colour case-insensitively: Qidi-created filaments store an uppercase hex while the
        # lookup value is lowercased, so an exact compare never matches on case-sensitive backends
        # (Postgres/CockroachDB), producing duplicate spools on every rescan.
        .where(func.lower(Filament.color_hex) == color_hex)
        .where(Spool.archived.is_(False))
        .order_by(Spool.registered.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    spool = result.unique().scalar_one_or_none()
    if spool is not None:
        logger.debug("Qidi fuzzy match: spool %d via material=%s color=%s", spool.id, material_type, color_hex)
        if auto_bind and uid is not None:
            await tag_db.try_link(db=db, spool_id=spool.id, uid=uid, tag_format=QIDI_FORMAT)
        return spool

    return None


def map_spool_to_qidi(spool: Spool) -> QidiTagData:
    """Map a Spoolman spool/filament to Qidi tag data for writing.

    Args:
        spool: The Spoolman spool to encode.

    Returns:
        QidiTagData ready for encoding.

    """
    filament = spool.filament
    data = QidiTagData()

    if filament.material:
        # Try exact Qidi material name first (e.g. "PLA Silk")
        code = material_code_from_name(filament.material)
        if code is not None:
            data.material_code = code
        else:
            # Try matching the Spoolman material type to any Qidi material
            # Pick the first (most generic) match
            material_lower = filament.material.lower()
            for c, (_name, spoolman_type) in sorted(MATERIAL_CODE_MAP.items()):
                if spoolman_type.lower() == material_lower:
                    data.material_code = c
                    break

    if filament.color_hex:
        code = color_code_from_hex(filament.color_hex)
        if code is not None:
            data.color_code = code

    return data


async def create_spool_from_qidi_tag(
    db: AsyncSession,
    tag_data: QidiTagData,
    tag_uid_hex: str | None = None,
) -> Spool:
    """Create a filament and spool from Qidi tag data.

    Creates a Qidi vendor (if needed), filament with the tag's material/color,
    and a spool linked to it. Binds the tag UID if available.
    """
    vendor_id = await _find_or_create_vendor(db, QIDI_VENDOR_NAME)
    name = f"Qidi {tag_data.material_name}"
    color_hex = tag_data.color_hex if tag_data.color_hex != "000000" else None

    # Default diameter 1.75mm (Qidi tags don't store diameter)
    db_filament = await filament_db.create(
        db=db,
        density=1.24,
        diameter=1.75,
        name=name,
        vendor_id=vendor_id,
        material=tag_data.material_type,
        weight=None,
        color_hex=color_hex,
        external_id=None,
    )

    db_spool = await spool_db.create(db=db, filament_id=db_filament.id)

    if tag_uid_hex:
        try:
            uid = normalize_uid(tag_uid_hex)
        except ValueError:
            uid = None
        if uid is not None:
            try:
                await tag_db.link(db=db, spool_id=db_spool.id, uid=uid, tag_format=QIDI_FORMAT)
                logger.info("Bound new spool %d to Qidi tag uid %s", db_spool.id, uid)
            except TagConflictError:
                logger.warning("Could not bind new spool %d to uid %s: already claimed", db_spool.id, uid)

    return db_spool


async def _find_or_create_vendor(db: AsyncSession, name: str) -> int:
    """Find a vendor by name or create one."""
    vendors, _ = await vendor_db.find(db=db, name=name)
    if vendors:
        return vendors[0].id
    new_vendor = await vendor_db.create(db=db, name=name)
    return new_vendor.id
