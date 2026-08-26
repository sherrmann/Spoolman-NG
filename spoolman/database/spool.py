"""Helper functions for interacting with spool database objects."""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy
from sqlalchemy import ColumnElement, Numeric, case, func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload
from sqlalchemy.sql.functions import coalesce

from spoolman.api.v1.models import EventType, Spool, SpoolEvent
from spoolman.database import filament, models, printer
from spoolman.database.extra_field_query import (
    ExtraFieldJoin,
    apply_extra_field_filters_and_sort,
    apply_spool_related_extra_filters,
    extra_field_join,
    extra_field_value_text,
)
from spoolman.database.utils import (
    LIKE_ESCAPE,
    SortOrder,
    add_where_clause_int,
    add_where_clause_int_opt,
    add_where_clause_str,
    add_where_clause_str_opt,
    escape_like,
    order_by_clauses,
    order_by_expression,
    parse_nested_field,
    utc_timezone_naive,
)
from spoolman.exceptions import ItemCreateError, ItemNotFoundError, SpoolMeasureError
from spoolman.extra_field_registry import EXTRA_FIELD_PREFIX, EntityType, ExtraField, ExtraFieldType, get_extra_fields
from spoolman.math import weight_from_length
from spoolman.tags import normalize_uid
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

# Weights are rounded to 6 decimal places (1 microgram) wherever they're written, to strip float64
# representation noise (e.g. 0.30000000000000004 from summing 0.1 + 0.2) without discarding real
# sub-gram increments — a slicer can legitimately report ~0.03 g per layer, which is still six
# orders of magnitude above this floor (#377).
WEIGHT_ROUND_DECIMALS = 6

# The SQL type every rounded weight expression carries. 18 total digits leaves 12 for the integer
# part — orders of magnitude more than any real spool weight in grams — with WEIGHT_ROUND_DECIMALS
# digits after the point. Shared by _round6 and by the zero-clamp literal in
# _used_weight_after_refill so that both branches of that CASE have the same type (see _round6).
WEIGHT_NUMERIC = Numeric(18, WEIGHT_ROUND_DECIMALS)


def _round6(expr: sqlalchemy.ColumnElement[float]) -> sqlalchemy.ColumnElement[float]:
    """Round a float SQL expression to WEIGHT_ROUND_DECIMALS places, portable across dialects.

    PostgreSQL (and CockroachDB, which follows PostgreSQL semantics here) has no two-argument
    ``round(double precision, integer)`` overload — only ``round(numeric, integer)`` — so a bare
    ``func.round(expr, 6)`` compiles and passes on SQLite/MySQL/MariaDB, then fails on
    PostgreSQL/CockroachDB with "function round(double precision, integer) does not exist". This
    codebase already hit this exact class of non-portable-two-argument-function bug once with
    ``func.max`` (see location.py's ``get_weight_aggregates``); the fix is the same idea — cast to
    Numeric first, so ``round`` resolves to the two-argument overload on every backend.

    The value this returns is therefore NUMERIC-typed, not double precision, and there is
    deliberately no cast back to Float. Where the rounded value is assigned straight to the column
    (``UPDATE ... SET used_weight = round(...)`` — the consumption path in use_weight_safe) that
    outer cast really is redundant: the assignment coerces to the column's type on every backend
    anyway, and on MySQL/MariaDB ``CAST(... AS FLOAT)`` isn't supported at all, so SQLAlchemy drops
    it from the compiled SQL and emits a warning for nothing.

    It is *not* redundant when the rounded value sits inside a ``CASE`` alongside another branch,
    which is what the refill path in _used_weight_after_refill builds. CockroachDB requires every
    branch of a ``CASE`` to resolve to the same type and rejects a mixed NUMERIC/FLOAT8 one outright
    ("incompatible value type: expected $5::FLOAT8 to be of type decimal, found type float");
    PostgreSQL, SQLite and MySQL/MariaDB all accept the mismatch, so only the CockroachDB leg of the
    integration matrix ever catches it. Rather than reintroduce the outer cast (and the MySQL
    warning) purely to reconcile the branches, _used_weight_after_refill casts its zero-clamp
    literal to WEIGHT_NUMERIC so both branches agree at the source — do not "simplify" that cast
    away. tests/test_spool_weight_sql_types.py guards both halves of this.
    """
    numeric_expr = sqlalchemy.cast(expr, WEIGHT_NUMERIC)
    return func.round(numeric_expr, WEIGHT_ROUND_DECIMALS)


def _used_weight_after_refill(weight: float) -> sqlalchemy.ColumnElement[float]:
    """Build the used_weight expression for a refill (``weight < 0``), clamped at zero.

    Both branches are deliberately WEIGHT_NUMERIC-typed: the rounded one because _round6 produces
    NUMERIC, the zero-clamp because CockroachDB rejects a ``CASE`` whose branches disagree on type.
    See _round6's docstring for the full reasoning.
    """
    new_used_weight = models.Spool.used_weight + weight
    return case(
        (new_used_weight >= 0.0, _round6(new_used_weight)),
        else_=sqlalchemy.cast(0.0, WEIGHT_NUMERIC),  # Set used_weight to 0 if the result would be negative
    )


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

    # Strip float64 representation noise regardless of which branch above set used_weight —
    # including a caller-supplied value, which can carry the same noise (#377).
    used_weight = round(used_weight, WEIGHT_ROUND_DECIMALS)

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
        # Explicitly populated (even empty), not left unset: an unset relationship on a
        # freshly-constructed object stays a pending lazy-load rather than an already-loaded
        # empty collection, and accessing it from the async post-commit path (spool_changed's
        # Spool.from_db) would raise MissingGreenlet instead of a lazy DB round trip.
        tags=[],
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
            # Wildcards in value_part are escaped, so a search of "%" looks for a literal
            # percent sign instead of matching every row.
            fuzzy_value = f"%{escape_like(value_part)}%"
            search_conditions.extend(
                [
                    models.Vendor.name.ilike(fuzzy_value, escape=LIKE_ESCAPE),
                    models.Filament.name.ilike(fuzzy_value, escape=LIKE_ESCAPE),
                    models.Filament.material.ilike(fuzzy_value, escape=LIKE_ESCAPE),
                    models.Filament.article_number.ilike(fuzzy_value, escape=LIKE_ESCAPE),
                    models.Spool.comment.ilike(fuzzy_value, escape=LIKE_ESCAPE),
                    models.Spool.lot_nr.ilike(fuzzy_value, escape=LIKE_ESCAPE),
                    models.Spool.location.ilike(fuzzy_value, escape=LIKE_ESCAPE),
                    sqlalchemy.cast(models.Spool.id, sqlalchemy.String).ilike(fuzzy_value, escape=LIKE_ESCAPE),
                ],
            )

    return search_conditions


async def find(  # noqa: C901, PLR0912, PLR0915
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
    tag: str | None = None,
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

    if tag is not None:
        # An inner join rather than a subquery, so the list query and the count query stay in
        # sync automatically: they share this statement. `uid` is unique, so at most one tag row
        # can match and the join cannot multiply result rows -- which is why the contains_eager
        # chain for filament/vendor above is unaffected.
        #
        # The join condition also does the filtering: a tag that points at something other than a
        # spool has a null `spool_id`, which matches no spool, so such a UID finds nothing here
        # rather than finding the wrong thing.
        stmt = stmt.join(models.Tag, models.Tag.spool_id == models.Spool.id).where(
            models.Tag.uid == normalize_uid(tag),
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


def _used_weight_from_remaining(initial_weight: float | None, remaining_weight: float) -> float:
    """Derive used_weight from a caller-supplied remaining_weight, as used by update()'s PATCH handling."""
    if initial_weight is None:
        raise ItemCreateError("remaining_weight can only be used if initial_weight is set.")
    return max(initial_weight - remaining_weight, 0)


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
            new_used_weight = _used_weight_from_remaining(spool.initial_weight, v)
            # Rounded like every other used_weight write path (#377): the subtraction can carry
            # the same float64 noise as the SQL accumulator in use_weight_safe does.
            spool.used_weight = round(new_used_weight, WEIGHT_ROUND_DECIMALS)
        elif k == "used_weight":
            # A caller can also set used_weight directly (#377): round it the same way.
            spool.used_weight = round(v, WEIGHT_ROUND_DECIMALS)
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
    # The accumulator is rounded in SQL (see _round6) rather than read back and rounded in Python,
    # for the same reason: rounding here must not turn this into a read-then-write (#377).
    if weight >= 0:
        await db.execute(
            sqlalchemy.update(models.Spool)
            .where(models.Spool.id == spool_id)
            .values(used_weight=_round6(models.Spool.used_weight + weight)),
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
        .values(used_weight=_used_weight_after_refill(weight)),
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


# ---------------------------------------------------------------------------------------------
# Spool grouping (GET /spool/group) and field-value rename (PATCH /spool/field/{field}).
# Ported from upstream's spoolman/database/spool.py (find_groups / rename_field_value), adapted to
# this fork's filter surface: no filament_multi_color_direction, first_used/last_used/registered
# range filters or include_empty (none of those exist elsewhere on this fork's spool endpoints
# yet, and grafting them on here would be new, unrequested API surface). filament/vendor extra
# field filters ARE wired in, via the already-ported apply_spool_related_extra_filters.
# ---------------------------------------------------------------------------------------------

# Mirrors the Spool.location column width, so an over-long rename is a 400 and not a 500.
LOCATION_MAX_LENGTH = 64

# The built-in axes a group_by (or a field rename) can name, and the column each groups on.
GROUP_BY_COLUMNS = {
    "filament": models.Spool.filament_id,
    "vendor": models.Filament.vendor_id,
    "material": models.Filament.material,
    "location": models.Spool.location,
}

# The two axes keyed by an entity id rather than by a value, and the column that names each
# group. The rest (material, location, extra fields) are their own title.
ENTITY_GROUP_BY_TITLES = {
    "filament": models.Filament.name,
    "vendor": models.Vendor.name,
}

# Extra fields whose value is a single plain string, and which can therefore be grouped on and
# renamed by value. Multi-choice is excluded because its value is a JSON *array*: two spools
# with overlapping-but-unequal selections are neither the same value nor cleanly different
# ones, and there is no single value to match or write.
SINGLE_VALUE_EXTRA_FIELD_TYPES = (ExtraFieldType.text, ExtraFieldType.choice)


def _blank_as_null(col: ColumnElement) -> ColumnElement:
    """Fold an empty string into NULL, so a value-keyed axis has ONE "no value" group.

    A spool with no value for a string field can spell that as NULL or as an empty string, and
    the two are distinct to the database -- left alone they become two groups the client can only
    render as the same "unassigned" one. Filtering already treats both as unset (see
    add_where_clause_str_opt and the empty branch of add_where_clause_extra_field), so grouping
    has to agree or a group's count will not match the spools that group's filter returns.
    """
    return func.nullif(col, "")


def _extra_field_key(spool_fields: Sequence[ExtraField], reference: str) -> str:
    """Resolve an `extra.<key>` reference to its bare key, rejecting fields that can't carry one.

    Shared by grouping and by renaming a value, which need the same guarantee: the field exists,
    and one spool has exactly one plain string in it.
    """
    field_key = reference[len(EXTRA_FIELD_PREFIX) :]
    field = next((f for f in spool_fields if f.key == field_key), None)
    if field is None:
        raise ValueError(f"Unknown spool extra field '{field_key}'.")
    is_multi_choice = field.field_type == ExtraFieldType.choice and field.multi_choice
    if field.field_type not in SINGLE_VALUE_EXTRA_FIELD_TYPES or is_multi_choice:
        raise ValueError(
            f"Spool extra field '{field_key}' does not hold a single plain value. "
            f"Only text and single-choice fields do.",
        )
    return field_key


async def _resolve_group_by(
    db: AsyncSession,
    group_by: str,
) -> tuple[ColumnElement, ColumnElement, ExtraFieldJoin | None]:
    """Resolve a group_by into the column to group on, the column to title groups by, and any join.

    Grouping is either on a built-in column or on one of the spool's extra fields. The latter
    lives in its own table, so it comes with a join the caller has to apply once the SELECT exists.
    """
    if group_by.startswith(EXTRA_FIELD_PREFIX):
        field_key = _extra_field_key(await get_extra_fields(db, EntityType.spool), group_by)
        join = extra_field_join(EntityType.spool, field_key)
        # The value is the group's title as well; there is no separate entity to name it.
        col = _blank_as_null(join.value)
        return col, col, join
    if group_by in ENTITY_GROUP_BY_TITLES:
        # Keyed by entity id, which has no blank spelling; the entity names the group.
        return GROUP_BY_COLUMNS[group_by], ENTITY_GROUP_BY_TITLES[group_by], None
    if group_by in GROUP_BY_COLUMNS:
        # material/location: the value is the group's title, and a blank one is no value.
        col = _blank_as_null(GROUP_BY_COLUMNS[group_by])
        return col, col, None
    raise ValueError(
        f"Invalid group_by field '{group_by}'. Must be one of {sorted(GROUP_BY_COLUMNS)} "
        f"or '{EXTRA_FIELD_PREFIX}<spool extra field key>'.",
    )


@dataclass
class SpoolGroupResult:
    """One aggregated spool group, with the grouped entity hydrated for its header."""

    key: object
    spool_count: int
    in_use_count: int
    total_remaining_weight: float
    last_used: datetime | None
    filament: models.Filament | None
    vendor: models.Vendor | None


def _group_aggregates() -> tuple[ColumnElement, ColumnElement, ColumnElement, ColumnElement]:
    """Build the four per-group aggregates as SQL expressions.

    Mirrors the remaining-weight formula used by Spool.from_db (including its max(..., 0) clamp,
    so an over-used spool contributes 0 rather than a negative number) so the group total agrees
    with what a client would compute by summing the individual spools itself.
    """
    remaining_expr = coalesce(
        coalesce(models.Spool.initial_weight, models.Filament.weight) - models.Spool.used_weight,
        0.0,
    )
    remaining_expr = case((remaining_expr < 0, 0.0), else_=remaining_expr)
    return (
        # COUNT of the spool's id, not COUNT(*), for parity with upstream: harmless here since
        # this fork's group query (unlike upstream's include_empty one) always selects FROM the
        # spools, so every row already has one, but it keeps the two implementations comparable.
        func.count(models.Spool.id).label("spool_count"),
        func.count(case((models.Spool.used_weight > 0, models.Spool.id))).label("in_use_count"),
        coalesce(func.sum(remaining_expr), 0.0).label("total_remaining_weight"),
        # Named apart from the `last_used` filter parameter: this is the group's aggregate.
        func.max(models.Spool.last_used).label("last_used"),
    )


def _apply_group_filters(
    stmt: sqlalchemy.Select,
    *,
    filament_name: str | None,
    filament_id: int | Sequence[int] | None,
    filament_material: str | None,
    vendor_name: str | None,
    vendor_id: int | Sequence[int] | None,
    location: str | None,
    lot_nr: str | None,
    allow_archived: bool,
) -> sqlalchemy.Select:
    """Join spool -> filament -> vendor and apply the filters find_groups shares with find().

    A private, find_groups-only helper -- find() inlines these same joins and where clauses
    itself, and is left untouched (see this port's additive-only constraint) rather than being
    refactored to share this builder.
    """
    stmt = stmt.join(models.Spool.filament, isouter=True).join(models.Filament.vendor, isouter=True)
    stmt = add_where_clause_int(stmt, models.Spool.filament_id, filament_id)
    stmt = add_where_clause_int_opt(stmt, models.Filament.vendor_id, vendor_id)
    stmt = add_where_clause_str(stmt, models.Vendor.name, vendor_name)
    stmt = add_where_clause_str_opt(stmt, models.Filament.name, filament_name)
    stmt = add_where_clause_str_opt(stmt, models.Filament.material, filament_material)
    stmt = add_where_clause_str_opt(stmt, models.Spool.location, location)
    stmt = add_where_clause_str_opt(stmt, models.Spool.lot_nr, lot_nr)
    if not allow_archived:
        # Since the archived field is nullable, and default is false, we need to check for both false or null
        stmt = stmt.where(
            sqlalchemy.or_(
                models.Spool.archived.is_(False),
                models.Spool.archived.is_(None),
            ),
        )
    return stmt


async def find_groups(
    *,
    db: AsyncSession,
    group_by: str,
    filament_name: str | None = None,
    filament_id: int | Sequence[int] | None = None,
    filament_material: str | None = None,
    vendor_name: str | None = None,
    vendor_id: int | Sequence[int] | None = None,
    location: str | None = None,
    lot_nr: str | None = None,
    allow_archived: bool = False,
    extra_field_filters: dict[str, str] | None = None,
    filament_extra_field_filters: dict[str, str] | None = None,
    vendor_extra_field_filters: dict[str, str] | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[SpoolGroupResult], int]:
    """Group matching spools by one axis and return per-group aggregates.

    Aggregation, group ordering and pagination happen in the database. Pagination is over
    groups, so a group is never split across pages and its aggregates are always complete.

    Returns a tuple of the requested page of groups and the total number of matching groups.
    """
    aggregates = _group_aggregates()
    spool_count, in_use_count, total_remaining, last_used_agg = aggregates

    group_col, title_col, extra_join = await _resolve_group_by(db, group_by)
    stmt = _apply_group_filters(
        sqlalchemy.select(group_col.label("group_key"), *aggregates),
        filament_name=filament_name,
        filament_id=filament_id,
        filament_material=filament_material,
        vendor_name=vendor_name,
        vendor_id=vendor_id,
        location=location,
        lot_nr=lot_nr,
        allow_archived=allow_archived,
    )
    if extra_join is not None:
        stmt = extra_join.apply(stmt, models.Spool.id)
    stmt = await apply_extra_field_filters_and_sort(
        db=db,
        stmt=stmt,
        base_obj=models.Spool,
        entity_type=EntityType.spool,
        extra_field_filters=extra_field_filters,
        sort_by=None,
    )
    # A filament's (or its vendor's) extra fields describe the filament, so they apply to the
    # spools grouped through it -- reached here through Spool.filament_id (the default link_column).
    stmt = await apply_spool_related_extra_filters(
        db=db,
        stmt=stmt,
        filament_filters=filament_extra_field_filters,
        vendor_filters=vendor_extra_field_filters,
    )
    stmt = stmt.group_by(group_col)

    # Total number of matching groups (before pagination).
    count_stmt = sqlalchemy.select(func.count()).select_from(stmt.order_by(None).subquery())
    total_count = (await db.execute(count_stmt)).scalar_one()

    # Group ordering. Every option is an aggregate (or the grouped column), so no non-grouped
    # bare column is referenced -- portable across SQLite, PostgreSQL, MySQL and CockroachDB.
    order_exprs = {
        "group.spool_count": spool_count,
        "group.in_use_count": in_use_count,
        "group.total_remaining": total_remaining,
        "group.last_used": last_used_agg,
        "group.title": func.min(title_col),
    }
    applied_sort = False
    if sort_by:
        for fieldstr, order in sort_by.items():
            expr = order_exprs.get(fieldstr)
            if expr is None:
                continue
            stmt = stmt.order_by(*order_by_clauses([expr], order))
            applied_sort = True
    if not applied_sort:
        stmt = stmt.order_by(*order_by_clauses([func.min(title_col)], SortOrder.ASC))
    # Break ties on the grouped column itself, so paging partitions the groups instead of
    # dropping or repeating one.
    stmt = stmt.order_by(group_col.asc())

    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)

    rows = (await db.execute(stmt)).all()

    # Hydrate the grouped entity for the header (filament/vendor). The value-keyed axes --
    # material, location, extra fields -- are their own header and need nothing.
    keys = [row.group_key for row in rows if row.group_key is not None]
    filament_map: dict[int, models.Filament] = {}
    vendor_map: dict[int, models.Vendor] = {}
    if group_by == "filament" and keys:
        fstmt = (
            sqlalchemy.select(models.Filament)
            .where(models.Filament.id.in_(keys))
            .options(joinedload(models.Filament.vendor))
        )
        filament_map = {f.id: f for f in (await db.execute(fstmt)).unique().scalars().all()}
    elif group_by == "vendor" and keys:
        vstmt = sqlalchemy.select(models.Vendor).where(models.Vendor.id.in_(keys))
        vendor_map = {v.id: v for v in (await db.execute(vstmt)).unique().scalars().all()}

    return [
        SpoolGroupResult(
            key=row.group_key,
            spool_count=int(row.spool_count or 0),
            in_use_count=int(row.in_use_count or 0),
            total_remaining_weight=float(row.total_remaining_weight or 0),
            last_used=row.last_used,
            filament=filament_map.get(row.group_key) if group_by == "filament" else None,
            vendor=vendor_map.get(row.group_key) if group_by == "vendor" else None,
        )
        for row in rows
    ], total_count


async def rename_field_value(
    *,
    db: AsyncSession,
    field: str,
    value: str,
    new_value: str,
) -> int:
    """Replace one value of one spool field wherever it occurs, in a single statement.

    rename_location generalised from location to the spool's other string fields, including its
    custom ones. A client that has grouped spools by a field can rename a whole group this way
    without reading out its members and patching them one at a time -- which it could only do
    for the spools it had actually paged in, and not atomically.

    Only fields the SPOOL owns can be renamed. A filament's material or vendor is a property of
    another entity: rewriting it "for these spools" would change filaments other spools share.

    Archived spools are included -- the value is the value, and skipping them would silently
    leave half the spools behind.

    Renaming onto a value that is already in use merges the two: each row is independently
    keyed by (spool_id, key) [for extra fields] or is just one spool's own location string, so
    two spools ending up with the same new value is not a collision -- it is simply both spools
    now sharing that value, same as if they had always matched.

    Like rename_location, no spool event is broadcast per row. The change is one statement over
    what may be hundreds of spools, and that fan-out is exactly what the websocket layer avoids
    elsewhere; other clients pick the change up on their next load.

    Returns the number of spools changed.
    """
    if field == "location":
        if len(new_value) > LOCATION_MAX_LENGTH:
            raise ValueError(f"A location can be at most {LOCATION_MAX_LENGTH} characters.")
        stmt = sqlalchemy.update(models.Spool).where(models.Spool.location == value).values(location=new_value)
    elif field.startswith(EXTRA_FIELD_PREFIX):
        field_key = _extra_field_key(await get_extra_fields(db, EntityType.spool), field)
        # Match on the DB-decoded scalar, so which JSON encoding wrote the value doesn't matter;
        # store the new one the way the rest of the API does.
        stmt = (
            sqlalchemy.update(models.SpoolField)
            .where(
                sqlalchemy.and_(
                    models.SpoolField.key == field_key,
                    extra_field_value_text(models.SpoolField.value) == value,
                ),
            )
            .values(value=json.dumps(new_value, ensure_ascii=False))
        )
    else:
        raise ValueError(
            f"Cannot rename values of '{field}'. Only fields the spool itself owns can be renamed: "
            f"location, or '{EXTRA_FIELD_PREFIX}<spool extra field key>'.",
        )

    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount
