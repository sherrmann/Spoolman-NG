"""Helper functions for interacting with printer database objects (issue #75)."""

import logging
from datetime import datetime

import sqlalchemy
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import EventType, Printer, PrinterEvent
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
) -> models.Printer:
    """Add a new printer to the database."""
    printer = models.Printer(
        name=name,
        registered=datetime.utcnow().replace(microsecond=0),
        comment=comment,
        extra=[models.PrinterField(key=k, value=v) for k, v in (extra or {}).items()],
    )
    db.add(printer)
    await db.commit()
    await printer_changed(printer, EventType.ADDED)
    return printer


async def get_by_id(db: AsyncSession, printer_id: int) -> models.Printer:
    """Get a printer object from the database by the unique ID."""
    printer = await db.get(models.Printer, printer_id)
    if printer is None:
        raise ItemNotFoundError(f"No printer with ID {printer_id} found.")
    return printer


async def get_aggregates(db: AsyncSession, printer_ids: list[int]) -> dict[int, int]:
    """Return {printer_id: spool_count} for the given printers (issue #75).

    spool_count counts non-archived spools currently assigned to the printer via Spool.printer_id.
    Printers with none are reported as 0. A single grouped query keeps the list read path free of an
    N+1.
    """
    if not printer_ids:
        return {}

    active_spool = sqlalchemy.or_(models.Spool.archived.is_(False), models.Spool.archived.is_(None))
    count_stmt = (
        select(models.Spool.printer_id, func.count(models.Spool.id))
        .where(models.Spool.printer_id.in_(printer_ids), active_spool)
        .group_by(models.Spool.printer_id)
    )
    counts = {int(pid): int(count) for pid, count in (await db.execute(count_stmt)).all()}
    return {pid: counts.get(pid, 0) for pid in printer_ids}


async def find(
    *,
    db: AsyncSession,
    name: str | None = None,
    extra_field_filters: dict[str, str] | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Printer], int]:
    """Find a list of printer objects by search criteria.

    Returns a tuple containing the list of items and the total count of matching items.
    """
    stmt = select(models.Printer)

    stmt = add_where_clause_str(stmt, models.Printer.name, name)

    total_count = None

    stmt = await apply_extra_field_filters_and_sort(
        db=db,
        stmt=stmt,
        base_obj=models.Printer,
        entity_type=EntityType.printer,
        extra_field_filters=extra_field_filters,
        sort_by=sort_by,
    )

    if sort_by is not None:
        for fieldstr, order in sort_by.items():
            if fieldstr.startswith("extra."):
                continue
            field = getattr(models.Printer, fieldstr)
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
    printer_id: int,
    data: dict,
) -> models.Printer:
    """Update the fields of a printer object."""
    printer = await get_by_id(db, printer_id)
    for k, v in data.items():
        if k == "extra":
            printer.extra = [models.PrinterField(key=k, value=v) for k, v in v.items()]
        else:
            setattr(printer, k, v)
    await db.commit()
    await printer_changed(printer, EventType.UPDATED)
    return printer


async def delete(db: AsyncSession, printer_id: int) -> None:
    """Delete a printer object.

    There is no DB-level foreign key on Spool.printer_id, so unassign any spools that reference this
    printer first (application-level ON DELETE SET NULL) — deleting a printer must never delete the
    valuable spool inventory, only detach it.
    """
    printer = await get_by_id(db, printer_id)
    await db.execute(
        sqlalchemy.update(models.Spool).where(models.Spool.printer_id == printer_id).values(printer_id=None),
    )
    await db.delete(printer)
    # Commit before notifying so the deletion is durable and visible to subsequent
    # requests; post-commit notification must be the last, infallible step.
    await db.commit()
    await printer_changed(printer, EventType.DELETED)


async def clear_extra_field(db: AsyncSession, key: str) -> None:
    """Delete all extra fields with a specific key."""
    await db.execute(
        sqlalchemy.delete(models.PrinterField).where(models.PrinterField.key == key),
    )
    await db.commit()


async def printer_changed(printer: models.Printer, typ: EventType) -> None:
    """Notify websocket clients that a printer has changed."""
    try:
        await websocket_manager.send(
            ("printer", str(printer.id)),
            PrinterEvent(
                type=typ,
                resource="printer",
                date=datetime.utcnow(),
                payload=Printer.from_db(printer),
            ),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")
