"""Helper functions for interacting with shop database objects (#298)."""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import EventType, Shop, ShopEvent
from spoolman.database import models
from spoolman.database.utils import SortOrder, add_where_clause_str, order_by_expression
from spoolman.exceptions import ItemCreateError, ItemDeleteError, ItemNotFoundError
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)


def _join_ships_to(ships_to: list[str] | None) -> str | None:
    """Serialize a region list to the stored comma-separated string. Empty list -> None."""
    if not ships_to:
        return None
    return ",".join(ships_to)


async def create(
    *,
    db: AsyncSession,
    name: str,
    homepage: str | None = None,
    ships_to: list[str] | None = None,
    comment: str | None = None,
) -> models.Shop:
    """Add a new shop to the database. Raises ItemCreateError on a duplicate name."""
    shop = models.Shop(
        name=name,
        registered=datetime.utcnow().replace(microsecond=0),
        homepage=homepage,
        ships_to=_join_ships_to(ships_to),
        comment=comment,
    )
    db.add(shop)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ItemCreateError(f"A shop named '{name}' already exists.") from exc
    await shop_changed(shop, EventType.ADDED)
    return shop


async def get_by_id(db: AsyncSession, shop_id: int) -> models.Shop:
    """Get a shop object from the database by the unique ID."""
    shop = await db.get(models.Shop, shop_id)
    if shop is None:
        raise ItemNotFoundError(f"No shop with ID {shop_id} found.")
    return shop


async def find(
    *,
    db: AsyncSession,
    name: str | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Shop], int]:
    """Find a list of shop objects by search criteria.

    Returns a tuple of (items, total count of matching items).
    """
    stmt = select(models.Shop)
    stmt = add_where_clause_str(stmt, models.Shop.name, name)

    total_count = None
    if sort_by is not None:
        for fieldstr, order in sort_by.items():
            field = getattr(models.Shop, fieldstr)
            stmt = stmt.order_by(order_by_expression(field, order))

    if limit is not None:
        total_count_stmt = stmt.with_only_columns(func.count(), maintain_column_froms=True).order_by(None)
        total_count = (await db.execute(total_count_stmt)).scalar()
        stmt = stmt.offset(offset).limit(limit)

    rows = await db.execute(stmt, execution_options={"populate_existing": True})
    result = list(rows.unique().scalars().all())
    if total_count is None:
        total_count = len(result)
    return result, total_count


async def update(*, db: AsyncSession, shop_id: int, data: dict) -> models.Shop:
    """Update the fields of a shop object. Raises ItemCreateError on a duplicate name."""
    shop = await get_by_id(db, shop_id)
    for k, v in data.items():
        if k == "ships_to":
            shop.ships_to = _join_ships_to(v)
        else:
            setattr(shop, k, v)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ItemCreateError(f"A shop named '{data.get('name')}' already exists.") from exc
    await shop_changed(shop, EventType.UPDATED)
    return shop


async def delete(db: AsyncSession, shop_id: int) -> None:
    """Delete a shop object.

    Restricted while any order references the shop (#298). FKs are not enforced on SQLite in this
    codebase, so the reference is checked explicitly rather than via a DB IntegrityError.
    """
    shop = await get_by_id(db, shop_id)
    order_count = await db.scalar(
        select(func.count(models.Order.id)).where(models.Order.shop_id == shop_id),
    )
    if order_count:
        raise ItemDeleteError(f"Cannot delete shop {shop_id}: {order_count} order(s) reference it.")
    await db.delete(shop)
    await db.commit()
    await shop_changed(shop, EventType.DELETED)


async def shop_changed(shop: models.Shop, typ: EventType) -> None:
    """Notify websocket clients that a shop has changed."""
    try:
        await websocket_manager.send(
            ("shop", str(shop.id)),
            ShopEvent(
                type=typ,
                resource="shop",
                date=datetime.utcnow(),
                payload=Shop.from_db(shop),
            ),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")
