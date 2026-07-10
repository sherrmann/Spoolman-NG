"""Helper functions for interacting with vendor database objects."""

import logging
from datetime import datetime, timezone

import sqlalchemy
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import EventType, Vendor, VendorEvent
from spoolman.database import models
from spoolman.database.extra_field_query import apply_extra_field_filters_and_sort
from spoolman.database.utils import SortOrder, add_where_clause_str, add_where_clause_str_opt, order_by_expression
from spoolman.exceptions import ItemNotFoundError
from spoolman.extra_field_registry import EntityType
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)


async def create(
    *,
    db: AsyncSession,
    name: str | None = None,
    comment: str | None = None,
    empty_spool_weight: float | None = None,
    external_id: str | None = None,
    extra: dict[str, str] | None = None,
) -> models.Vendor:
    """Add a new vendor to the database."""
    vendor = models.Vendor(
        name=name,
        registered=datetime.now(timezone.utc).replace(microsecond=0),
        comment=comment,
        empty_spool_weight=empty_spool_weight,
        external_id=external_id,
        extra=[models.VendorField(key=k, value=v) for k, v in (extra or {}).items()],
    )
    db.add(vendor)
    await db.commit()
    await vendor_changed(vendor, EventType.ADDED)
    return vendor


async def get_by_id(db: AsyncSession, vendor_id: int) -> models.Vendor:
    """Get a vendor object from the database by the unique ID."""
    vendor = await db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise ItemNotFoundError(f"No vendor with ID {vendor_id} found.")
    return vendor


async def get_aggregates(db: AsyncSession, vendor_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Return {vendor_id: (filament_count, spool_count)} for the given vendors (issue #49).

    filament_count counts filament types from the vendor; spool_count counts non-archived spools
    across those filaments. Vendors with none are reported as (0, 0). Two small grouped queries keep
    the list read path free of an N+1 pattern.
    """
    if not vendor_ids:
        return {}

    filament_count_stmt = (
        select(models.Filament.vendor_id, func.count(models.Filament.id))
        .where(models.Filament.vendor_id.in_(vendor_ids))
        .group_by(models.Filament.vendor_id)
    )
    filament_counts = {int(vid): int(count) for vid, count in (await db.execute(filament_count_stmt)).all()}

    active_spool = sqlalchemy.or_(models.Spool.archived.is_(False), models.Spool.archived.is_(None))
    spool_count_stmt = (
        select(models.Filament.vendor_id, func.count(models.Spool.id))
        .join(models.Spool, models.Spool.filament_id == models.Filament.id)
        .where(models.Filament.vendor_id.in_(vendor_ids), active_spool)
        .group_by(models.Filament.vendor_id)
    )
    spool_counts = {int(vid): int(count) for vid, count in (await db.execute(spool_count_stmt)).all()}

    return {vid: (filament_counts.get(vid, 0), spool_counts.get(vid, 0)) for vid in vendor_ids}


async def find(
    *,
    db: AsyncSession,
    name: str | None = None,
    external_id: str | None = None,
    extra_field_filters: dict[str, str] | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Vendor], int]:
    """Find a list of vendor objects by search criteria.

    Returns a tuple containing the list of items and the total count of matching items.
    """
    stmt = select(models.Vendor)

    stmt = add_where_clause_str(stmt, models.Vendor.name, name)
    stmt = add_where_clause_str_opt(stmt, models.Vendor.external_id, external_id)

    total_count = None

    stmt = await apply_extra_field_filters_and_sort(
        db=db,
        stmt=stmt,
        base_obj=models.Vendor,
        entity_type=EntityType.vendor,
        extra_field_filters=extra_field_filters,
        sort_by=sort_by,
    )

    if sort_by is not None:
        for fieldstr, order in sort_by.items():
            # Check if this is a custom field sort
            if fieldstr.startswith("extra."):
                continue

            field = getattr(models.Vendor, fieldstr)
            stmt = stmt.order_by(order_by_expression(field, order))

    if limit is not None:
        total_count_stmt = stmt.with_only_columns(func.count(), maintain_column_froms=True).order_by(None)
        total_count = (await db.execute(total_count_stmt)).scalar()
        stmt = stmt.offset(offset).limit(limit)

    rows = await db.execute(
        stmt,
        execution_options={"populate_existing": True},
    )
    result = list(rows.unique().scalars().all())
    if total_count is None:
        total_count = len(result)

    return result, total_count


async def update(
    *,
    db: AsyncSession,
    vendor_id: int,
    data: dict,
) -> models.Vendor:
    """Update the fields of a vendor object."""
    vendor = await get_by_id(db, vendor_id)
    for k, v in data.items():
        if k == "extra":
            vendor.extra = [models.VendorField(key=k, value=v) for k, v in v.items()]
        else:
            setattr(vendor, k, v)
    await db.commit()
    await vendor_changed(vendor, EventType.UPDATED)
    # Spool payloads embed their filament's vendor, so refresh spool subscribers too (#130). Lazy
    # import to avoid a cycle; a no-op when nothing is subscribed to spool events.
    from spoolman.database import spool  # noqa: PLC0415

    await spool.notify_spools_of_vendor_change(db, vendor.id)
    return vendor


async def delete(db: AsyncSession, vendor_id: int) -> None:
    """Delete a vendor object."""
    vendor = await get_by_id(db, vendor_id)
    await db.delete(vendor)
    # Commit before notifying so the deletion is durable and visible to subsequent
    # requests; post-commit notification must be the last, infallible step.
    await db.commit()
    await vendor_changed(vendor, EventType.DELETED)


async def clear_extra_field(db: AsyncSession, key: str) -> None:
    """Delete all extra fields with a specific key."""
    await db.execute(
        sqlalchemy.delete(models.VendorField).where(models.VendorField.key == key),
    )
    await db.commit()


async def vendor_changed(vendor: models.Vendor, typ: EventType) -> None:
    """Notify websocket clients that a vendor has changed."""
    try:
        await websocket_manager.send(
            ("vendor", str(vendor.id)),
            VendorEvent(
                type=typ,
                resource="vendor",
                date=datetime.now(timezone.utc),
                payload=Vendor.from_db(vendor),
            ),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")
