"""TigerTag to Spoolman spool matching and reverse mapping."""

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spoolman.database import tag as tag_db
from spoolman.database.models import Filament, Spool
from spoolman.tags import normalize_uid
from spoolman.tigertag_codec import TigerTagData

logger = logging.getLogger(__name__)

TIGERTAG_FORMAT = "tigertag"


def make_nfc_tag_id(tag_data: TigerTagData) -> str | None:
    """Build a human-readable TigerTag identity string from (id_product, timestamp).

    Historically this composite key was also how Spoolman matched and bound tags, stored as a
    `SpoolField(key="nfc_tag_id")`. That is no longer true: this fork's NFC subsystem now reads
    and writes exclusively through the upstream `tag` table (spoolman.database.tag), which is
    keyed on a tag's real hardware UID and nothing else -- see `find_spool_by_tigertag` and
    `bind_spool_to_tigertag` below. This function survives purely to label a decoded tag for
    humans/API consumers (`NfcBindResponse.nfc_tag_id`, `NfcCreateFromTagResponse`'s retry
    guard used to key off it too, and no longer does); it plays no part in matching or binding.

    Returns None if the tag doesn't carry a usable product id and timestamp.
    """
    if tag_data.id_product > 0 and tag_data.timestamp > 0:
        return f"tigertag_{tag_data.id_product}_{tag_data.timestamp}"
    return None


async def bind_spool_to_tigertag(db: AsyncSession, spool: Spool, uid_hex: str) -> bool:
    """Bind a spool to a specific physical TigerTag by its hardware UID.

    Returns True if a new tag row was created, False if this spool already held this exact
    physical tag (idempotent re-bind).

    Raises:
        ValueError: If uid_hex is not a valid hexadecimal tag UID.
        TagConflictError: If the UID is already linked to a different spool.

    """
    uid = normalize_uid(uid_hex)
    already = await tag_db.find_spool_by_uid(db, uid)
    if already is not None and already.id == spool.id:
        return False
    await tag_db.link(db=db, spool_id=spool.id, uid=uid, tag_format=TIGERTAG_FORMAT)
    logger.info("Bound spool %d to TigerTag uid %s", spool.id, uid)
    return True


async def find_spool_by_tigertag(
    db: AsyncSession,
    tag_data: TigerTagData,
    uid_hex: str | None = None,
    auto_bind: bool = True,
) -> Spool | None:
    """Find a Spoolman spool matching decoded TigerTag data.

    Matching strategies (tried in order):
    1. Exact match by this tag's own hardware UID, via the `tag` table. Requires the reader
       (or caller) to have reported a UID; without one this strategy is skipped entirely.
    2. Fuzzy match by Filament.external_id == "tigertag_{id_product}"
       (returns most recent non-archived spool for that filament)
    3. Direct match by Spool.id == id_product (for tags written by Spoolman)

    When auto_bind is True and a spool is found via strategy 2 (not yet bound) and a UID is
    known, that UID is bound to the spool for future exact matches.

    Args:
        db: Database session.
        tag_data: Decoded TigerTag data.
        uid_hex: The scanned tag's hardware UID, if known.
        auto_bind: Automatically bind an unbound UID to a spool matched by strategy 2.

    Returns:
        Optional[Spool]: The matched spool, or None if no match found.

    """
    uid = None
    if uid_hex:
        try:
            uid = normalize_uid(uid_hex)
        except ValueError:
            uid = None

    if uid is not None:
        # Strategy 1: exact match by this physical tag's own UID.
        spool = await tag_db.find_spool_by_uid(db, uid)
        if spool is not None:
            logger.debug("TigerTag exact match: spool %d via tag uid %s", spool.id, uid)
            return spool

    if tag_data.id_product > 0:
        # Strategy 2: Match by external_id on filament
        external_id = f"tigertag_{tag_data.id_product}"
        stmt = (
            select(Spool)
            .join(Spool.filament)
            .options(
                selectinload(Spool.filament).selectinload(Filament.vendor),
                selectinload(Spool.extra),
            )
            .where(Filament.external_id == external_id)
            .where(Spool.archived.is_(False))
            .order_by(Spool.registered.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        spool = result.unique().scalar_one_or_none()
        if spool is not None:
            if auto_bind and uid is not None:
                await tag_db.try_link(db=db, spool_id=spool.id, uid=uid, tag_format=TIGERTAG_FORMAT)
            return spool

        # Strategy 3: Last-resort match by spool ID, for home-grown tags Spoolman wrote without a
        # real TigerTag catalog product ID (map_spool_to_tigertag falls back to id_product = spool.id).
        # id_product is otherwise a TigerTag *catalog* identifier from a different number space, so a
        # genuine third-party tag whose id_product happens to equal a spool PK would match the wrong
        # spool. Never auto-bind on this heuristic match — a binding is permanent and we cannot tell a
        # Spoolman-written id from a catalog id, so only return the (transient) best-effort result.
        stmt = (
            select(Spool)
            .options(
                selectinload(Spool.filament).selectinload(Filament.vendor),
                selectinload(Spool.extra),
            )
            .where(Spool.id == tag_data.id_product)
        )
        result = await db.execute(stmt)
        spool = result.unique().scalar_one_or_none()
        if spool is not None:
            logger.debug(
                "TigerTag heuristic spool-id match: spool %d == id_product %d (not auto-bound)",
                spool.id,
                tag_data.id_product,
            )
            return spool

    return None


def map_spool_to_tigertag(
    spool: Spool,
    brand_map: dict[str, int] | None = None,
    material_map: dict[str, int] | None = None,
    diameter_map: float | None = None,
) -> TigerTagData:
    """Map a Spoolman spool/filament to TigerTag binary data.

    Args:
        spool: The Spoolman spool to encode.
        brand_map: Optional mapping of brand name -> TigerTag brand ID.
        material_map: Optional mapping of material name -> TigerTag material type ID.
        diameter_map: Not used, diameter is determined from filament data.

    Returns:
        TigerTagData: The TigerTag data ready for encoding.

    """
    filament = spool.filament
    data = TigerTagData()

    # TigerTag Maker v1.0 magic number and type
    data.id_tigertag = 0x5BF59264  # TigerTag Maker V1
    data.id_type = 142  # Filament

    # Set product ID: use TigerTag product ID if available, otherwise use spool ID
    if filament.external_id and filament.external_id.startswith("tigertag_"):
        try:
            data.id_product = int(filament.external_id.split("_", 1)[1])
        except (ValueError, IndexError):
            data.id_product = spool.id
    else:
        data.id_product = spool.id

    if brand_map and filament.vendor and filament.vendor.name:
        vendor_name = filament.vendor.name.lower()
        for name, brand_id in brand_map.items():
            if name.lower() == vendor_name:
                data.id_brand = brand_id
                break

    if material_map and filament.material:
        material_name = filament.material.lower()
        for name, material_id in material_map.items():
            if name.lower() == material_name:
                data.id_material = material_id
                break

    if filament.diameter:
        if abs(filament.diameter - 1.75) < 0.1:
            data.id_diameter = 1
        elif abs(filament.diameter - 2.85) < 0.1:
            data.id_diameter = 2

    if filament.color_hex:
        data.color_hex = filament.color_hex

    if filament.weight:
        data.weight = int(filament.weight)

    if filament.settings_extruder_temp:
        data.nozzle_temp = filament.settings_extruder_temp
    if filament.settings_bed_temp:
        data.bed_temp = filament.settings_bed_temp

    # Timestamp - TigerTag uses seconds since 2000-01-01 GMT
    data.timestamp = int(time.time()) - 946684800

    return data
