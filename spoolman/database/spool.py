"""Helper functions for interacting with spool database objects."""

import logging
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy
from sqlalchemy import case, func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload
from sqlalchemy.sql.functions import coalesce

from spoolman.api.v1.models import EventType, Spool, SpoolEvent
from spoolman.database import filament, models, printer
from spoolman.database.extra_field_query import apply_extra_field_filters_and_sort
from spoolman.database.utils import (
    SortOrder,
    add_where_clause_int,
    add_where_clause_int_opt,
    add_where_clause_str,
    add_where_clause_str_opt,
    order_by_expression,
    parse_nested_field,
    utc_timezone_naive,
)
from spoolman.exceptions import ItemCreateError, ItemNotFoundError, SpoolMeasureError
from spoolman.extra_field_registry import EntityType
from spoolman.math import weight_from_length
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)


async def build(
    *,
    db: AsyncSession,
    filament_id: int,
    remaining_weight: float | None = None,
    initial_weight: float | None = None,
    spool_weight: float | None = None,
    used_weight: float | None = None,
    first_used: datetime | None = None,
    last_used: datetime | None = None,
    price: float | None = None,
    location: str | None = None,
    printer_id: int | None = None,
    lot_nr: str | None = None,
    comment: str | None = None,
    archived: bool = False,
    diameter: float | None = None,
    extra: dict[str, str] | None = None,
) -> models.Spool:
    """Build a spool and stage it in the session, WITHOUT committing or notifying.

    This is the object-construction half of :func:`create`: it validates the filament (and optional
    printer) FKs, derives the weights and adds the row to the session. The caller owns the commit and
    the ADDED websocket event. :func:`create` does both for the single-spool case; the order arrival
    flow (#322) stages several spools together with the order-line mutations and commits them as one
    transaction, so a mid-way failure can't leave lines arrived with only some of their spools.
    """
    filament_item = await filament.get_by_id(db, filament_id)

    # #75: validate the optional printer assignment (no DB-level FK), so a bad id is a clean 404.
    # Assign the loaded object (not the raw id) so the printer relationship is populated for the
    # post-commit spool_changed payload without an async lazy-load.
    printer_item = await printer.get_by_id(db, printer_id) if printer_id is not None else None

    # Set spool_weight to spool_weight if spool_weight is not null and spool_weight not provided
    if spool_weight is None and filament_item.spool_weight is not None:
        spool_weight = filament_item.spool_weight

    # Calculate initial_weight if not provided
    if initial_weight is None and filament_item.weight is not None:
        initial_weight = filament_item.weight

    if used_weight is None:
        if remaining_weight is not None:
            if initial_weight is None or initial_weight == 0:
                raise ItemCreateError(
                    "remaining_weight can only be used if the initial_weight is "
                    "defined or the filament has a weight set.",
                )
            used_weight = max(initial_weight - remaining_weight, 0)
        else:
            used_weight = 0

    # Convert datetime values to UTC and remove timezone info
    if first_used is not None:
        first_used = utc_timezone_naive(first_used)
    if last_used is not None:
        last_used = utc_timezone_naive(last_used)

    spool = models.Spool(
        filament=filament_item,
        registered=datetime.utcnow().replace(microsecond=0),
        initial_weight=initial_weight,
        spool_weight=spool_weight,
        used_weight=used_weight,
        price=price,
        first_used=first_used,
        last_used=last_used,
        location=location,
        lot_nr=lot_nr,
        comment=comment,
        archived=archived,
        diameter=diameter,
        printer=printer_item,
        extra=[models.SpoolField(key=k, value=v) for k, v in (extra or {}).items()],
    )
    db.add(spool)
    return spool


async def create(
    *,
    db: AsyncSession,
    filament_id: int,
    remaining_weight: float | None = None,
    initial_weight: float | None = None,
    spool_weight: float | None = None,
    used_weight: float | None = None,
    first_used: datetime | None = None,
    last_used: datetime | None = None,
    price: float | None = None,
    location: str | None = None,
    printer_id: int | None = None,
    lot_nr: str | None = None,
    comment: str | None = None,
    archived: bool = False,
    diameter: float | None = None,
    extra: dict[str, str] | None = None,
) -> models.Spool:
    """Add a new spool to the database. Leave weight empty to assume full spool."""
    spool = await build(
        db=db,
        filament_id=filament_id,
        remaining_weight=remaining_weight,
        initial_weight=initial_weight,
        spool_weight=spool_weight,
        used_weight=used_weight,
        first_used=first_used,
        last_used=last_used,
        price=price,
        location=location,
        printer_id=printer_id,
        lot_nr=lot_nr,
        comment=comment,
        archived=archived,
        diameter=diameter,
        extra=extra,
    )
    await db.commit()
    await spool_changed(spool, EventType.ADDED)
    return spool


async def get_by_id(db: AsyncSession, spool_id: int) -> models.Spool:
    """Get a spool object from the database by the unique ID."""
    spool = await db.get(
        models.Spool,
        spool_id,
        options=[joinedload("*")],  # Load all nested objects as well
    )
    if spool is None:
        raise ItemNotFoundError(f"No spool with ID {spool_id} found.")
    return spool


def _build_search_filters(search: str) -> list:
    """Build search filter conditions for spool free-text search.

    Mirrors the filament search (comma-separated terms, quoted exact match, fuzzy match,
    numeric ID) but spans the spool's own text — comment, lot number, location — plus its
    filament's vendor name, name, material and article number. Issue #51.

    Returns a list of SQLAlchemy conditions to be combined with OR.
    """
    search_conditions = []
    for value_part in search.split(","):
        if len(value_part) == 0:
            continue

        if value_part[0] == '"' and value_part[-1] == '"':
            exact_value = value_part[1:-1]
            search_conditions.extend(
                [
                    models.Vendor.name == exact_value,
                    models.Filament.name == exact_value,
                    models.Filament.material == exact_value,
                    models.Filament.article_number == exact_value,
                    models.Spool.comment == exact_value,
                    models.Spool.lot_nr == exact_value,
                    models.Spool.location == exact_value,
                ],
            )
            if exact_value.lstrip("-").isdigit():
                search_conditions.append(models.Spool.id == int(exact_value))
        else:
            fuzzy_value = f"%{value_part}%"
            search_conditions.extend(
                [
                    models.Vendor.name.ilike(fuzzy_value),
                    models.Filament.name.ilike(fuzzy_value),
                    models.Filament.material.ilike(fuzzy_value),
                    models.Filament.article_number.ilike(fuzzy_value),
                    models.Spool.comment.ilike(fuzzy_value),
                    models.Spool.lot_nr.ilike(fuzzy_value),
                    models.Spool.location.ilike(fuzzy_value),
                    sqlalchemy.cast(models.Spool.id, sqlalchemy.String).ilike(fuzzy_value),
                ],
            )

    return search_conditions


async def find(  # noqa: C901, PLR0912
    *,
    db: AsyncSession,
    search: str | None = None,
    filament_name: str | None = None,
    filament_id: int | Sequence[int] | None = None,
    filament_material: str | None = None,
    vendor_name: str | None = None,
    vendor_id: int | Sequence[int] | None = None,
    location: str | None = None,
    lot_nr: str | None = None,
    allow_archived: bool = False,
    archived: bool | None = None,
    extra_field_filters: dict[str, str] | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Spool], int]:
    """Find a list of spool objects by search criteria.

    Sort by a field by passing a dict with the field name as key and the sort order as value.
    The field name can contain nested fields, e.g. filament.name.

    Returns a tuple containing the list of items and the total count of matching items.
    """
    stmt = (
        sqlalchemy.select(models.Spool)
        .join(models.Spool.filament, isouter=True)
        .join(models.Filament.vendor, isouter=True)
        .options(
            contains_eager(models.Spool.filament).contains_eager(models.Filament.vendor),
            # Eager-load the optional printer (#75) so the list's Spool.from_db doesn't lazy-load it.
            joinedload(models.Spool.printer),
        )
    )

    stmt = add_where_clause_int(stmt, models.Spool.filament_id, filament_id)
    stmt = add_where_clause_int_opt(stmt, models.Filament.vendor_id, vendor_id)
    stmt = add_where_clause_str(stmt, models.Vendor.name, vendor_name)
    stmt = add_where_clause_str_opt(stmt, models.Filament.name, filament_name)
    stmt = add_where_clause_str_opt(stmt, models.Filament.material, filament_material)
    stmt = add_where_clause_str_opt(stmt, models.Spool.location, location)
    stmt = add_where_clause_str_opt(stmt, models.Spool.lot_nr, lot_nr)

    if search is not None:
        search_conditions = _build_search_filters(search)
        if search_conditions:
            stmt = stmt.where(sqlalchemy.or_(*search_conditions))

    if archived is not None:
        # Explicit archived-state filter: true → only archived, false → only active.
        # Overrides allow_archived, which merely widens the default active-only view.
        if archived:
            stmt = stmt.where(models.Spool.archived.is_(True))
        else:
            stmt = stmt.where(
                sqlalchemy.or_(
                    models.Spool.archived.is_(False),
                    models.Spool.archived.is_(None),
                ),
            )
    elif not allow_archived:
        # Since the archived field is nullable, and default is false, we need to check for both false or null
        stmt = stmt.where(
            sqlalchemy.or_(
                models.Spool.archived.is_(False),
                models.Spool.archived.is_(None),
            ),
        )

    total_count = None

    stmt = await apply_extra_field_filters_and_sort(
        db=db,
        stmt=stmt,
        base_obj=models.Spool,
        entity_type=EntityType.spool,
        extra_field_filters=extra_field_filters,
        sort_by=sort_by,
    )

    if sort_by is not None:
        for fieldstr, order in sort_by.items():
            # Check if this is a custom field sort
            if fieldstr.startswith("extra."):
                continue

            sorts = []
            if fieldstr == "remaining_weight":
                sorts.append(
                    coalesce(models.Spool.initial_weight, models.Filament.weight) - models.Spool.used_weight,
                )
            elif fieldstr == "remaining_length":
                # Simplified weight -> length formula. Absolute value is not correct but the proportionality
                # is still kept, which means the sort order is correct. #101: prefer the per-spool diameter
                # override when set (coalesce), matching the from_db length math.
                spool_diameter = coalesce(models.Spool.diameter, models.Filament.diameter)
                sorts.append(
                    (coalesce(models.Spool.initial_weight, models.Filament.weight) - models.Spool.used_weight)
                    / models.Filament.density
                    / (spool_diameter * spool_diameter),
                )
            elif fieldstr == "used_length":
                spool_diameter = coalesce(models.Spool.diameter, models.Filament.diameter)
                sorts.append(
                    models.Spool.used_weight / models.Filament.density / (spool_diameter * spool_diameter),
                )
            elif fieldstr == "filament.combined_name":
                sorts.append(models.Vendor.name)
                sorts.append(models.Filament.name)
            elif fieldstr == "price":
                sorts.append(coalesce(models.Spool.price, models.Filament.price))
            else:
                sorts.append(parse_nested_field(models.Spool, fieldstr))

            stmt = stmt.order_by(*(order_by_expression(f, order) for f in sorts))

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
    spool_id: int,
    data: dict,
) -> models.Spool:
    """Update the fields of a spool object."""
    spool = await get_by_id(db, spool_id)
    used_weight_before = spool.used_weight
    for k, v in data.items():
        if k == "filament_id":
            spool.filament = await filament.get_by_id(db, v)
            # If there is no initial_weight, calculate it from the filament weight
            if spool.initial_weight is None and spool.filament.weight is not None:
                spool.initial_weight = spool.filament.weight

        elif k == "remaining_weight":
            if spool.initial_weight is None:
                raise ItemCreateError("remaining_weight can only be used if initial_weight is set.")
            spool.used_weight = max(spool.initial_weight - v, 0)
        elif isinstance(v, datetime):
            setattr(spool, k, utc_timezone_naive(v))
        elif k == "extra":
            # Merge semantics (#233): keys present are replaced, a None value deletes the
            # key, keys not mentioned stay. Unlike the other entities, which replace all.
            spool.extra = [f for f in spool.extra if f.key not in v]
            spool.extra.extend([models.SpoolField(key=k2, value=v2) for k2, v2 in v.items() if v2 is not None])
        elif k == "printer_id":
            # #75: validate the reassignment (no DB-level FK) and set the relationship object so the
            # post-commit spool_changed payload has it loaded; a null clears the assignment.
            spool.printer = await printer.get_by_id(db, v) if v is not None else None
        else:
            setattr(spool, k, v)
    # Record a usage event when a manual edit changed used_weight (e.g. the "reset usage" action,
    # #77). first_used/last_used are intentionally not touched here — this is an edit, not a use.
    if spool.used_weight != used_weight_before:
        _record_usage_event(db, spool_id, "update", spool.used_weight - used_weight_before)
    await db.commit()
    await spool_changed(spool, EventType.UPDATED)
    return spool


async def delete(db: AsyncSession, spool_id: int) -> None:
    """Delete a spool object."""
    spool = await get_by_id(db, spool_id)
    # Remove usage events explicitly: SQLite doesn't enforce the FK's ON DELETE CASCADE, and there
    # is no ORM relationship (see models.SpoolUsageEvent) to cascade them. Same transaction as the
    # spool delete. Issue #50.
    await db.execute(
        sqlalchemy.delete(models.SpoolUsageEvent).where(models.SpoolUsageEvent.spool_id == spool_id),
    )
    await db.delete(spool)
    # Commit before notifying so the deletion is durable and visible to subsequent
    # requests; post-commit notification must be the last, infallible step.
    await db.commit()
    await spool_changed(spool, EventType.DELETED)


async def get_usage_events(
    db: AsyncSession,
    spool_id: int,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.SpoolUsageEvent], int]:
    """Return a spool's usage events, most recent first, with the total count (#50)."""
    base = sqlalchemy.select(models.SpoolUsageEvent).where(models.SpoolUsageEvent.spool_id == spool_id)
    total = (
        await db.execute(
            sqlalchemy.select(func.count()).select_from(base.order_by(None).subquery()),
        )
    ).scalar_one()
    stmt = base.order_by(models.SpoolUsageEvent.time.desc(), models.SpoolUsageEvent.id.desc())
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    rows = await db.execute(stmt)
    return list(rows.scalars().all()), total


async def find_usage_event_by_key(
    db: AsyncSession,
    spool_id: int,
    idempotency_key: str,
) -> models.SpoolUsageEvent | None:
    """Return a prior usage event for this spool with the given idempotency key, if any (#60)."""
    stmt = sqlalchemy.select(models.SpoolUsageEvent).where(
        models.SpoolUsageEvent.spool_id == spool_id,
        models.SpoolUsageEvent.idempotency_key == idempotency_key,
    )
    return (await db.execute(stmt)).scalars().first()


async def clear_extra_field(db: AsyncSession, key: str) -> None:
    """Delete all extra fields with a specific key."""
    await db.execute(
        sqlalchemy.delete(models.SpoolField).where(models.SpoolField.key == key),
    )
    await db.commit()


def _record_usage_event(
    db: AsyncSession,
    spool_id: int,
    event_type: str,
    delta: float,
    *,
    measured_weight: float | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> None:
    """Stage a usage-event row in the current session (#50).

    Added — not committed — so it lands in the same transaction as the weight mutation it records.
    `delta` is the change actually applied to used_weight (sign: consumed positive, refilled
    negative), i.e. exactly what use_weight_safe returns.
    """
    db.add(
        models.SpoolUsageEvent(
            spool_id=spool_id,
            time=datetime.utcnow().replace(microsecond=0),
            event_type=event_type,
            delta=delta,
            measured_weight=measured_weight,
            comment=comment,
            idempotency_key=idempotency_key,
        ),
    )


async def use_weight_safe(db: AsyncSession, spool_id: int, weight: float) -> float:
    """Consume filament from a spool by weight in a way that is safe against race conditions.

    Args:
        db (AsyncSession): Database session
        spool_id (int): Spool ID
        weight (float): Filament weight to consume, in grams

    Returns:
        float: The actual change applied to used_weight after clamping at zero. This equals
            ``weight`` unless the result would have gone negative, in which case used_weight is
            clamped to 0 and the returned delta is only what was actually consumed.

    """
    # Consumption (weight >= 0) can never trigger the clamp at zero, so the applied delta always
    # equals the requested weight. Keep this path a single atomic UPDATE with no preceding read:
    # adding a read-before-write here turns concurrent uses into read/write transactions that
    # deadlock (MariaDB) or hit serialization retries (CockroachDB SERIALIZABLE), losing updates.
    if weight >= 0:
        await db.execute(
            sqlalchemy.update(models.Spool)
            .where(models.Spool.id == spool_id)
            .values(used_weight=models.Spool.used_weight + weight),
        )
        return weight

    # Refill (weight < 0) may clamp used_weight at 0, so read the prior value to report the real
    # applied delta. Refills are not part of the high-concurrency hot path.
    used_before = (
        await db.execute(sqlalchemy.select(models.Spool.used_weight).where(models.Spool.id == spool_id))
    ).scalar_one_or_none()
    await db.execute(
        sqlalchemy.update(models.Spool)
        .where(models.Spool.id == spool_id)
        .values(
            used_weight=case(
                (models.Spool.used_weight + weight >= 0.0, models.Spool.used_weight + weight),
                else_=0.0,  # Set used_weight to 0 if the result would be negative
            ),
        ),
    )
    if used_before is None:
        return weight  # Spool not found; caller's get_by_id will raise ItemNotFoundError.
    return max(0.0, used_before + weight) - used_before


async def use_weight(
    db: AsyncSession,
    spool_id: int,
    weight: float,
    *,
    event_type: str = "use",
    measured_weight: float | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> models.Spool:
    """Consume filament from a spool by weight.

    Increases the used_weight attribute of the spool.
    Updates the first_used and last_used attributes where appropriate.
    Records a usage event in the same transaction (#50). measure() passes event_type="measure"
    (plus the gross measured_weight) so the record reflects the real caller rather than "use".

    Args:
        db (AsyncSession): Database session
        spool_id (int): Spool ID
        weight (float): Filament weight to consume, in grams
        event_type (str): Usage event type to record ("use" or, from measure(), "measure").
        measured_weight (float | None): Gross measured weight to store on the event (measure only).
        comment (str | None): Optional comment to record with the event.
        idempotency_key (str | None): Optional key stored with the event to make the call replay-safe.

    Returns:
        models.Spool: Updated spool object

    """
    weight_delta = await use_weight_safe(db, spool_id, weight)

    spool = await get_by_id(db, spool_id)

    if spool.first_used is None:
        spool.first_used = datetime.utcnow().replace(microsecond=0)
    spool.last_used = datetime.utcnow().replace(microsecond=0)

    _record_usage_event(
        db,
        spool_id,
        event_type,
        weight_delta,
        measured_weight=measured_weight,
        comment=comment,
        idempotency_key=idempotency_key,
    )
    await db.commit()
    await spool_changed(spool, EventType.UPDATED, {"weight_delta": weight_delta})
    return spool


async def use_length(
    db: AsyncSession,
    spool_id: int,
    length: float,
    *,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> models.Spool:
    """Consume filament from a spool by length.

    Increases the used_weight attribute of the spool.
    Updates the first_used and last_used attributes where appropriate.
    Records a usage event in the same transaction (#50).

    Args:
        db (AsyncSession): Database session
        spool_id (int): Spool ID
        length (float): Length of filament to consume, in mm
        comment (str | None): Optional comment to record with the event.
        idempotency_key (str | None): Optional key stored with the event to make the call replay-safe.

    Returns:
        models.Spool: Updated spool object

    """
    # Get the effective diameter (per-spool override when set, else the filament's — #101) and density.
    result = await db.execute(
        sqlalchemy.select(
            coalesce(models.Spool.diameter, models.Filament.diameter),
            models.Filament.density,
        )
        .join(models.Spool, models.Spool.filament_id == models.Filament.id)
        .where(models.Spool.id == spool_id),
    )
    try:
        filament_info = result.one()
    except NoResultFound as exc:
        raise ItemNotFoundError("Filament not found for spool.") from exc

    # Calculate and use weight
    weight = weight_from_length(
        length=length,
        diameter=filament_info[0],
        density=filament_info[1],
    )
    weight_delta = await use_weight_safe(db, spool_id, weight)

    # Get spool with new weight and update first_used and last_used
    spool = await get_by_id(db, spool_id)

    if spool.first_used is None:
        spool.first_used = datetime.utcnow().replace(microsecond=0)
    spool.last_used = datetime.utcnow().replace(microsecond=0)

    _record_usage_event(db, spool_id, "use", weight_delta, comment=comment, idempotency_key=idempotency_key)
    await db.commit()
    await spool_changed(spool, EventType.UPDATED, {"weight_delta": weight_delta})
    return spool


async def measure(
    db: AsyncSession,
    spool_id: int,
    weight: float,
    *,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> models.Spool:
    """Record usage based on current gross weight of spool.

    Increases the used_weight attribute of the spool.
    Updates the first_used and last_used attributes where appropriate.
    The recorded usage event is tagged type="measure" and carries the gross measured weight (#50).

    Args:
        db (AsyncSession): Database session
        spool_id (int): Spool ID
        weight (float): Length of filament to consume, in mm
        comment (str | None): Optional comment to record with the event.
        idempotency_key (str | None): Optional key stored with the event to make the call replay-safe.

    Returns:
        models.Spool: Updated spool object

    """
    spool_result = await db.execute(
        sqlalchemy.select(models.Spool.initial_weight, models.Spool.used_weight, models.Spool.spool_weight).where(
            models.Spool.id == spool_id,
        ),
    )

    try:
        spool_info = spool_result.one()
    except NoResultFound as exc:
        raise SpoolMeasureError("Spool not found.") from exc

    initial_weight = spool_info[0]
    spool_weight = spool_info[2]
    if initial_weight is None or initial_weight == 0 or spool_weight is None or spool_weight == 0:
        # Get filament weight and spool_weight
        result = await db.execute(
            sqlalchemy.select(models.Filament.weight, models.Filament.spool_weight)
            .join(models.Spool, models.Spool.filament_id == models.Filament.id)
            .where(models.Spool.id == spool_id),
        )
        try:
            filament_info = result.one()
        except NoResultFound as exc:
            raise ItemNotFoundError("Filament not found for spool.") from exc

        if spool_weight is None or spool_weight == 0:
            spool_weight = filament_info[1]

        if initial_weight is None or initial_weight == 0:
            initial_weight = filament_info[0] if filament_info[0] is not None else 0

    if initial_weight is None or initial_weight == 0:
        raise SpoolMeasureError("Initial weight is not set.")

    if spool_weight is None:
        # No tare weight on the spool or its filament (#229): treat it as 0, matching the
        # remaining-weight math everywhere else, instead of crashing on None arithmetic.
        spool_weight = 0

    initial_gross_weight = initial_weight + spool_weight

    # if the measurement is greater than the initial weight, set the initial weight to the measurement
    if weight > initial_gross_weight:
        return await reset_initial_weight(
            db,
            spool_id,
            weight - spool_weight,
            event_type="measure",
            measured_weight=weight,
            comment=comment,
            idempotency_key=idempotency_key,
        )

    # Calculate the current net weight
    current_use = initial_gross_weight - spool_info[1]

    # Calculate the weight used since last measure
    weight_to_use = current_use - weight

    # If the measured weight is less than the empty weight, use the rest of the spool
    if (initial_gross_weight - weight_to_use) < spool_weight:
        weight_to_use = current_use - spool_weight

    return await use_weight(
        db,
        spool_id,
        weight_to_use,
        event_type="measure",
        measured_weight=weight,
        comment=comment,
        idempotency_key=idempotency_key,
    )


async def find_locations(
    *,
    db: AsyncSession,
) -> list[str]:
    """Find a list of spool locations by searching for distinct values in the spool table."""
    stmt = sqlalchemy.select(models.Spool.location).distinct()
    rows = await db.execute(stmt)
    return [row[0] for row in rows.all() if row[0] is not None]


async def find_lot_numbers(
    *,
    db: AsyncSession,
) -> list[str]:
    """Find a list of spool lot numbers by searching for distinct values in the spool table."""
    stmt = sqlalchemy.select(models.Spool.lot_nr).distinct()
    rows = await db.execute(stmt)
    return [row[0] for row in rows.all() if row[0] is not None]


async def spool_changed(spool: models.Spool, typ: EventType, delta: dict | None = None) -> None:
    """Notify websocket clients that a spool has changed."""
    try:
        spool = Spool.from_db(spool)
        await websocket_manager.send(
            ("spool", str(spool.id)),
            SpoolEvent(type=typ, resource="spool", date=datetime.utcnow(), payload=spool, payload_extras=delta),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")


async def _notify_spools(db: AsyncSession, stmt: sqlalchemy.Select) -> None:
    """Emit a synthetic spool 'updated' event for every spool matched by `stmt` (#130).

    The spool websocket payload embeds its filament (and the filament's vendor), so a spool-only
    subscriber's cached view silently goes stale when that filament or vendor is edited. These
    synthetic events are refresh plumbing so such subscribers re-read the spool; they are not a
    durable contract. Gated on there being at least one spool subscriber and batch-loading the
    affected spools, so an edit costs nothing (one cheap tree check, no query) when nobody listens.
    """
    if not websocket_manager.has_subscribers(("spool",)):
        return
    result = await db.execute(stmt.options(joinedload("*")))
    for spool in result.unique().scalars().all():
        await spool_changed(spool, EventType.UPDATED)


async def notify_spools_of_filament_change(db: AsyncSession, filament_id: int) -> None:
    """Re-emit spool events for every spool of the given filament (#130)."""
    await _notify_spools(db, sqlalchemy.select(models.Spool).where(models.Spool.filament_id == filament_id))


async def notify_spools_of_vendor_change(db: AsyncSession, vendor_id: int) -> None:
    """Re-emit spool events for every spool whose filament belongs to the given vendor (#130)."""
    await _notify_spools(
        db,
        sqlalchemy.select(models.Spool).where(
            models.Spool.filament_id.in_(
                sqlalchemy.select(models.Filament.id).where(models.Filament.vendor_id == vendor_id),
            ),
        ),
    )


async def reset_initial_weight(
    db: AsyncSession,
    spool_id: int,
    weight: float,
    *,
    event_type: str = "measure",
    measured_weight: float | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> models.Spool:
    """Reset inital weight to new weight and used_weight to 0.

    Records a usage event whose delta is the drop in used_weight (used_weight goes to 0). Only
    called from measure() today, hence the "measure" default event type. Issue #50.
    """
    spool = await get_by_id(db, spool_id)

    delta = -spool.used_weight
    spool.initial_weight = weight
    spool.used_weight = 0
    _record_usage_event(
        db,
        spool_id,
        event_type,
        delta,
        measured_weight=measured_weight,
        comment=comment,
        idempotency_key=idempotency_key,
    )
    await db.commit()
    await spool_changed(spool, EventType.UPDATED)
    return spool


async def rename_location(
    *,
    db: AsyncSession,
    current_name: str,
    new_name: str,
) -> None:
    """Rename all spools with the current location name to the new name."""
    await db.execute(
        sqlalchemy.update(models.Spool).where(models.Spool.location == current_name).values(location=new_name),
    )
    await db.commit()
