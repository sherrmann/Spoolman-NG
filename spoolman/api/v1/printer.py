"""Printer related endpoints.

Printers are a first-class entity (issue #75 / #26) so a spool can be assigned to a printer for
per-printer inventory tracking and usage attribution. The optional ``Spool.printer_id`` carries the
assignment; a nested ``printer`` object is embedded in the spool payload. Everything is additive: an
unassigned spool behaves exactly as before.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import Message, Printer, PrinterEvent
from spoolman.database import printer
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.extra_fields import EXTRA_FIELD_PREFIX, EntityType, get_extra_fields, validate_extra_field_dict
from spoolman.ws import websocket_manager

router = APIRouter(
    prefix="/printer",
    tags=["printer"],
)

# ruff: noqa: D103


class PrinterParameters(BaseModel):
    name: str = Field(max_length=64, description="Printer name.", examples=["Voron 2.4"])
    comment: str | None = Field(
        None,
        max_length=1024,
        description="Free text comment about this printer.",
        examples=[""],
    )
    extra: dict[str, str] | None = Field(
        None,
        description="Extra fields for this printer.",
    )


class PrinterUpdateParameters(PrinterParameters):
    name: str | None = Field(None, max_length=64, description="Printer name.", examples=["Voron 2.4"])

    @field_validator("name")
    @classmethod
    def prevent_none(cls: type["PrinterUpdateParameters"], v: str | None) -> str | None:
        """Prevent name from being None."""
        if v is None:
            raise ValueError("Value must not be None.")
        return v


@router.get(
    "",
    name="Find printer",
    description=(
        "Get a list of printers that matches the search query. "
        "A websocket is served on the same path to listen for updates to any printer, or added or "
        "deleted printers. See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={
        200: {"model": list[Printer]},
        299: {"model": PrinterEvent, "description": "Websocket message"},
    },
)
async def find(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[
        str | None,
        Query(
            title="Printer Name",
            description=(
                "Partial case-insensitive search term for the printer name. Separate multiple terms with a comma. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    sort: Annotated[
        str | None,
        Query(
            title="Sort",
            description=(
                'Sort the results by the given field. Should be a comma-separate string with "field:direction" items.'
            ),
            examples=["name:asc,id:desc"],
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(title="Limit", description="Maximum number of items in the response."),
    ] = None,
    offset: Annotated[int, Query(title="Offset", description="Offset in the full result set if a limit is set.")] = 0,
) -> JSONResponse:
    # Extract custom field filters from query parameters
    extra_field_filters = {}
    query_params = request.query_params
    for key, value in query_params.items():
        if key.startswith(EXTRA_FIELD_PREFIX):
            field_key = key[len(EXTRA_FIELD_PREFIX) :]  # Remove "extra." prefix
            extra_field_filters[field_key] = value

    try:
        sort_by = parse_sort(sort)
        db_items, total_count = await printer.find(
            db=db,
            name=name,
            extra_field_filters=extra_field_filters if extra_field_filters else None,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    # Populate the per-printer spool_count aggregate for the returned page.
    aggregates = await printer.get_aggregates(db, [db_item.id for db_item in db_items])
    printers_out = [Printer.from_db(db_item, spool_count=aggregates.get(db_item.id)) for db_item in db_items]

    # Set x-total-count header for pagination
    return JSONResponse(
        content=jsonable_encoder(printers_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket(
    "",
    name="Listen to printer changes",
)
async def notify_any(
    websocket: WebSocket,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("printer",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("printer",), websocket)


@router.get(
    "/{printer_id}",
    name="Get printer",
    description=(
        "Get a specific printer. A websocket is served on the same path to listen for changes to the printer. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": PrinterEvent, "description": "Websocket message"}},
)
async def get(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    printer_id: int,
) -> Printer:
    db_item = await printer.get_by_id(db, printer_id)
    spool_count = (await printer.get_aggregates(db, [printer_id])).get(printer_id, 0)
    return Printer.from_db(db_item, spool_count=spool_count)


@router.websocket(
    "/{printer_id}",
    name="Listen to printer changes",
)
async def notify(
    websocket: WebSocket,
    printer_id: int,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("printer", str(printer_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("printer", str(printer_id)), websocket)


@router.post(
    "",
    name="Add printer",
    description="Add a new printer to the database.",
    response_model_exclude_none=True,
    response_model=Printer,
    responses={400: {"model": Message}},
)
async def create(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: PrinterParameters,
):
    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.printer) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())

    db_item = await printer.create(
        db=db,
        name=body.name,
        comment=body.comment,
        extra=body.extra,
    )

    # The spool_count aggregate is a read-time view; POST returns the stored resource unchanged.
    return Printer.from_db(db_item)


@router.patch(
    "/{printer_id}",
    name="Update printer",
    description=(
        "Update any attribute of a printer. Only fields specified in the request will be affected. "
        "If extra is set, all existing extra fields will be removed and replaced with the new ones."
    ),
    response_model_exclude_none=True,
    response_model=Printer,
    responses={
        400: {"model": Message},
        404: {"model": Message},
    },
)
async def update(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    printer_id: int,
    body: PrinterUpdateParameters,
):
    patch_data = body.model_dump(exclude_unset=True)

    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.printer) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    db_item = await printer.update(
        db=db,
        printer_id=printer_id,
        data=patch_data,
    )

    return Printer.from_db(db_item)


@router.delete(
    "/{printer_id}",
    name="Delete printer",
    description="Delete a printer. Any spools assigned to it are unassigned (their printer_id is cleared).",
    responses={404: {"model": Message}},
)
async def delete(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    printer_id: int,
) -> Message:
    await printer.delete(db, printer_id)
    return Message(message="Success!")
