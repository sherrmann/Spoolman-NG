"""Helper functions for interacting with location database objects."""

import logging
from datetime import datetime, timezone

import sqlalchemy
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import EventType, Location, LocationEvent
from spoolman.database import models
from spoolman.database.extra_field_query import apply_extra_field_filters_and_sort
from spoolman.database.utils import SortOrder, add_where_clause_str, order_by_expression
from spoolman.exceptions import ItemNotFoundError
from spoolman.extra_field_registry import EntityType
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)


async def create(
    *,
    db: AsyncSession,
    name: str,
    comment: str | None = None,
    extra: dict[str, str] | None = None,
) -> models.Location:
    """Add a new location to the database."""
    location = models.Location(
        name=name,
        registered=datetime.now(timezone.utc).replace(microsecond=0),
        comment=comment,
        extra=[models.LocationField(key=k, value=v) for k, v in (extra or {}).items()],
    )
    db.add(location)
    await db.commit()
    await location_changed(location, EventType.ADDED)
    return location


async def get_by_id(db: AsyncSession, location_id: int) -> models.Location:
    """Get a location object from the database by the unique ID."""
    location = await db.get(models.Location, location_id)
    if location is None:
        raise ItemNotFoundError(f"No location with ID {location_id} found.")
    return location


async def get_aggregates(db: AsyncSession, location_ids: list[int]) -> dict[int, int]:
    """Return {location_id: spool_count} for the given locations (issue #103).

    spool_count counts non-archived spools currently stored at the location, matched by name against
    the plain ``Spool.location`` string (the entity is a name registry; there is no FK). Locations
    with none are reported as 0. A single grouped query keeps the list read path free of an N+1.
    """
    if not location_ids:
        return {}

    name_rows = (
        await db.execute(select(models.Location.id, models.Location.name).where(models.Location.id.in_(location_ids)))
    ).all()
    names = {int(lid): name for lid, name in name_rows}
    if not names:
        return {}

    active_spool = sqlalchemy.or_(models.Spool.archived.is_(False), models.Spool.archived.is_(None))
    count_stmt = (
        select(models.Spool.location, func.count(models.Spool.id))
        .where(models.Spool.location.in_(list(names.values())), active_spool)
        .group_by(models.Spool.location)
    )
    counts_by_name = {loc: int(count) for loc, count in (await db.execute(count_stmt)).all()}

    return {lid: counts_by_name.get(name, 0) for lid, name in names.items()}


async def find(
    *,
    db: AsyncSession,
    name: str | None = None,
    extra_field_filters: dict[str, str] | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Location], int]:
    """Find a list of location objects by search criteria.

    Returns a tuple containing the list of items and the total count of matching items.
    """
    stmt = select(models.Location)

    stmt = add_where_clause_str(stmt, models.Location.name, name)

    total_count = None

    stmt = await apply_extra_field_filters_and_sort(
        db=db,
        stmt=stmt,
        base_obj=models.Location,
        entity_type=EntityType.location,
        extra_field_filters=extra_field_filters,
        sort_by=sort_by,
    )

    if sort_by is not None:
        for fieldstr, order in sort_by.items():
            if fieldstr.startswith("extra."):
                continue
            field = getattr(models.Location, fieldstr)
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
    location_id: int,
    data: dict,
) -> models.Location:
    """Update the fields of a location object."""
    location = await get_by_id(db, location_id)
    for k, v in data.items():
        if k == "extra":
            location.extra = [models.LocationField(key=k, value=v) for k, v in v.items()]
        else:
            setattr(location, k, v)
    await db.commit()
    await location_changed(location, EventType.UPDATED)
    return location


async def delete(db: AsyncSession, location_id: int) -> None:
    """Delete a location object."""
    location = await get_by_id(db, location_id)
    await db.delete(location)
    # Commit before notifying so the deletion is durable and visible to subsequent
    # requests; post-commit notification must be the last, infallible step.
    await db.commit()
    await location_changed(location, EventType.DELETED)


async def clear_extra_field(db: AsyncSession, key: str) -> None:
    """Delete all extra fields with a specific key."""
    await db.execute(
        sqlalchemy.delete(models.LocationField).where(models.LocationField.key == key),
    )
    await db.commit()


async def location_changed(location: models.Location, typ: EventType) -> None:
    """Notify websocket clients that a location has changed."""
    try:
        await websocket_manager.send(
            ("location", str(location.id)),
            LocationEvent(
                type=typ,
                resource="location",
                date=datetime.now(timezone.utc),
                payload=Location.from_db(location),
            ),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")
