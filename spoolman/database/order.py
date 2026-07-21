"""Helper functions for interacting with order database objects (#298)."""

import logging
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from spoolman.api.v1.models import EventType, Order, OrderEvent
from spoolman.database import filament, models, shop
from spoolman.database.utils import SortOrder, add_where_clause_int_opt, order_by_expression, utc_timezone_naive
from spoolman.exceptions import ItemNotFoundError
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)


async def _build_lines(db: AsyncSession, lines: list[dict] | None) -> list[models.OrderLine]:
    """Build OrderLine rows from a list of line dicts, validating each filament FK exists."""
    built: list[models.OrderLine] = []
    for line in lines or []:
        # Validate the filament exists (clean 404 instead of a deferred FK error).
        await filament.get_by_id(db, line["filament_id"])
        built.append(
            models.OrderLine(
                filament_id=line["filament_id"],
                quantity=line.get("quantity", 1),
                price_per_unit=line.get("price_per_unit"),
                arrived_at=utc_timezone_naive(line["arrived_at"]) if line.get("arrived_at") is not None else None,
            ),
        )
    return built


async def create(
    *,
    db: AsyncSession,
    shop_id: int | None = None,
    ordered_at: datetime | None = None,
    order_number: str | None = None,
    url: str | None = None,
    comment: str | None = None,
    lines: list[dict] | None = None,
) -> models.Order:
    """Add a new order (with its lines) to the database."""
    shop_item: models.Shop | None = None
    if shop_id is not None:
        shop_item = await shop.get_by_id(db, shop_id)

    order = models.Order(
        registered=datetime.utcnow().replace(microsecond=0),
        shop=shop_item,
        ordered_at=utc_timezone_naive(ordered_at)
        if ordered_at is not None
        else datetime.utcnow().replace(microsecond=0),
        order_number=order_number,
        url=url,
        comment=comment,
        lines=await _build_lines(db, lines),
    )
    db.add(order)
    await db.commit()
    order = await get_by_id(db, order.id)
    await order_changed(order, EventType.ADDED)
    return order


async def get_by_id(db: AsyncSession, order_id: int) -> models.Order:
    """Get an order object from the database by the unique ID, with shop and lines loaded."""
    order = await db.get(models.Order, order_id, options=[joinedload("*")])
    if order is None:
        raise ItemNotFoundError(f"No order with ID {order_id} found.")
    return order


async def find(
    *,
    db: AsyncSession,
    shop_id: int | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Order], int]:
    """Find a list of order objects. Returns (items, total count of matching items).

    An order's lines are a one-to-many collection eager-loaded via ``joinedload`` (lazy=joined),
    so the SELECT that fetches an order fans out to one row per line. Applying SQL LIMIT/OFFSET to
    that fanned-out query windows the joined rows, not distinct orders, which would truncate a
    boundary order's line set or return fewer than ``limit`` orders. So when paginating we resolve
    the page on distinct order ids first — a query over the orders table alone, where LIMIT/OFFSET
    are unambiguous — and only then load those orders' full object graph (#319).
    """

    def _apply_sort(statement: Select) -> Select:
        if sort_by is not None:
            for fieldstr, order in sort_by.items():
                statement = statement.order_by(order_by_expression(getattr(models.Order, fieldstr), order))
        return statement

    if limit is not None:
        count_stmt = add_where_clause_int_opt(select(func.count(models.Order.id)), models.Order.shop_id, shop_id)
        total_count = (await db.execute(count_stmt)).scalar() or 0

        # The page of order ids, ordered and windowed over the orders table alone (no line join).
        id_stmt = add_where_clause_int_opt(select(models.Order.id), models.Order.shop_id, shop_id)
        id_stmt = _apply_sort(id_stmt).offset(offset).limit(limit)
        page_ids = list((await db.execute(id_stmt)).scalars().all())
        if not page_ids:
            return [], total_count

        # Load the full graph (shop + lines + ...) for just this page, re-ordered to match it.
        stmt = _apply_sort(select(models.Order).options(joinedload("*")).where(models.Order.id.in_(page_ids)))
        rows = await db.execute(stmt, execution_options={"populate_existing": True})
        return list(rows.unique().scalars().all()), total_count

    stmt = add_where_clause_int_opt(select(models.Order).options(joinedload("*")), models.Order.shop_id, shop_id)
    stmt = _apply_sort(stmt)
    rows = await db.execute(stmt, execution_options={"populate_existing": True})
    result = list(rows.unique().scalars().all())
    return result, len(result)


async def update(*, db: AsyncSession, order_id: int, data: dict, replace_lines: bool) -> models.Order:
    """Update an order. When replace_lines is True, the line set is fully replaced by data['lines']."""
    order = await get_by_id(db, order_id)
    for k, v in data.items():
        if k == "lines":
            continue  # handled below
        if k == "shop_id":
            order.shop = await shop.get_by_id(db, v) if v is not None else None
        elif k == "ordered_at":
            order.ordered_at = utc_timezone_naive(v) if v is not None else order.ordered_at
        else:
            setattr(order, k, v)
    if replace_lines:
        # delete-orphan cascade removes the old lines when the collection is reassigned.
        order.lines = await _build_lines(db, data.get("lines"))
    await db.commit()
    order = await get_by_id(db, order_id)
    await order_changed(order, EventType.UPDATED)
    return order


def _resolve_arrival_requests(
    order: models.Order,
    order_id: int,
    lines: list[dict] | None,
) -> list[tuple[models.OrderLine, int]]:
    """Resolve the requested arrivals into (line, arriving_quantity) pairs.

    ``lines`` is None means every still-outstanding line, arriving in full. Otherwise each entry names
    a line and an optional quantity (defaulting to the whole line).
    """
    if lines is None:
        return [(line, line.quantity) for line in order.lines if line.arrived_at is None]

    by_id = {line.id: line for line in order.lines}
    requests: list[tuple[models.OrderLine, int]] = []
    for req in lines:
        line = by_id.get(req["line_id"])
        if line is None:
            raise ItemNotFoundError(f"Order {order_id} has no line with ID {req['line_id']}.")
        if line.arrived_at is not None:
            raise ValueError(f"Order line {line.id} has already arrived.")
        qty = req.get("quantity")
        if qty is None or qty == line.quantity:
            requests.append((line, line.quantity))
        elif qty > line.quantity:
            raise ValueError(
                f"quantity {qty} exceeds outstanding quantity {line.quantity} for line {line.id}",
            )
        else:
            if qty < 1:
                raise ValueError("Arrival quantity must be >= 1.")
            requests.append((line, qty))
    return requests


def _apply_arrival(
    order: models.Order,
    line: models.OrderLine,
    qty: int,
    now: datetime,
) -> list[tuple[int, float | None]]:
    """Mark ``line`` arrived (splitting it if ``qty`` is a partial quantity).

    Returns one (filament_id, price_per_unit) tuple per arriving unit.
    """
    if qty == line.quantity:
        line.arrived_at = now
        return [(line.filament_id, line.price_per_unit)] * line.quantity

    # Split: shrink the open line, add a new arrived line for the delivered quantity.
    line.quantity -= qty
    order.lines.append(
        models.OrderLine(
            filament_id=line.filament_id,
            quantity=qty,
            price_per_unit=line.price_per_unit,
            arrived_at=now,
        ),
    )
    return [(line.filament_id, line.price_per_unit)] * qty


async def arrive(
    *,
    db: AsyncSession,
    order_id: int,
    lines: list[dict] | None = None,
    create_spools: bool = False,
    location_id: int | None = None,
) -> list[models.Spool]:
    """Mark order lines arrived, splitting on a partial quantity, optionally creating spools.

    ``lines`` is a list of {"line_id": int, "quantity"?: int}; omitted or None means every still-
    outstanding line, arriving in full. A quantity below a line's count splits the line into an
    arrived part (quantity) and a still-open remainder. When ``create_spools`` is True, one spool per
    arriving unit is created, copying the line's ``price_per_unit`` into the spool price and the
    resolved location name (from ``location_id``) into the spool location.

    Returns the created spools (empty when ``create_spools`` is False).
    """
    from spoolman.database import location, spool  # noqa: PLC0415  (avoid import cycle at module load)

    order = await get_by_id(db, order_id)
    requests = _resolve_arrival_requests(order, order_id, lines)

    now = datetime.utcnow().replace(microsecond=0)
    location_name: str | None = None
    if location_id is not None:
        location_name = (await location.get_by_id(db, location_id)).name

    arriving: list[tuple[int, float | None]] = []  # (filament_id, price_per_unit) per unit
    for line, qty in requests:
        arriving.extend(_apply_arrival(order, line, qty, now))

    # Stage the spools alongside the line mutations so both persist in a single commit (#322).
    # Committing the lines first and then creating spools one-by-one (each its own commit) could
    # leave lines arrived with only some of their spools if the loop failed part-way, with no retry
    # path (re-arrive rejects already-arrived lines). spool.build stages without committing.
    created: list[models.Spool] = []
    if create_spools:
        for filament_id, price in arriving:
            created.append(
                await spool.build(db=db, filament_id=filament_id, price=price, location=location_name),
            )

    await db.commit()

    order = await get_by_id(db, order_id)
    await order_changed(order, EventType.UPDATED)
    for created_spool in created:
        await spool.spool_changed(created_spool, EventType.ADDED)
    return created


async def delete(db: AsyncSession, order_id: int) -> None:
    """Delete an order. Its lines cascade (ORM delete-orphan + DB ON DELETE CASCADE)."""
    order = await get_by_id(db, order_id)
    await db.delete(order)
    await db.commit()
    await order_changed(order, EventType.DELETED)


async def order_changed(order: models.Order, typ: EventType) -> None:
    """Notify websocket clients that an order has changed."""
    try:
        await websocket_manager.send(
            ("order", str(order.id)),
            OrderEvent(
                type=typ,
                resource="order",
                date=datetime.utcnow(),
                payload=Order.from_db(order),
            ),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")
