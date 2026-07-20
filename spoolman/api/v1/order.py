"""Order related endpoints (#298)."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import Message, Order, OrderEvent, Spool
from spoolman.database import order
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/order",
    tags=["order"],
)

# ruff: noqa: D103


class OrderLineParameters(BaseModel):
    filament_id: int = Field(description="The filament type ordered on this line.")
    quantity: int = Field(default=1, ge=1, description="Number of spools ordered on this line.", examples=[2])
    price_per_unit: float | None = Field(None, ge=0, description="Price of one spool on this line.", examples=[19.9])
    arrived_at: datetime | None = Field(
        None,
        description="When this line arrived. Null means still outstanding. Usually set via /order/{id}/arrive.",
    )


class ArriveLine(BaseModel):
    line_id: int = Field(description="ID of the order line to mark arrived.")
    quantity: int | None = Field(
        None,
        ge=1,
        description="Delivered quantity. Omit for the whole line; a value below the line's count splits it.",
    )


class ArriveParameters(BaseModel):
    lines: list[ArriveLine] | None = Field(
        None,
        description="Lines to mark arrived. Omit to arrive every still-outstanding line in full.",
    )
    create_spools: bool = Field(default=False, description="Create one spool per arriving unit.")
    location_id: int | None = Field(None, description="Location entity ID to assign to the created spools.")


class ArriveResponse(BaseModel):
    spools: list[Spool] = Field(
        description="Spools created for the arriving quantities (empty when create_spools=false).",
    )


class OrderParameters(BaseModel):
    shop_id: int | None = Field(None, description="The shop this order was placed with.")
    ordered_at: datetime | None = Field(None, description="When the order was placed. Defaults to now.")
    order_number: str | None = Field(
        None, max_length=256, description="Shop order/reference number.", examples=["4711"]
    )
    url: str | None = Field(None, max_length=1024, description="Link to the order.")
    comment: str | None = Field(None, max_length=1024, description="Free text comment about this order.")
    lines: list[OrderLineParameters] | None = Field(
        None,
        description="The lines of this order. On PATCH, if present this fully replaces the line set.",
    )


@router.get(
    "",
    name="Find orders",
    description=(
        "Get a list of orders. A websocket is served on the same path to listen for updates to any order, or "
        "added or deleted orders. See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={200: {"model": list[Order]}, 299: {"model": OrderEvent, "description": "Websocket message"}},
)
async def find(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    shop_id: Annotated[
        int | None, Query(title="Shop ID", description="Filter to orders placed with this shop.")
    ] = None,
    sort: Annotated[
        str | None,
        Query(title="Sort", description='Comma-separated "field:direction" items.', examples=["ordered_at:desc"]),
    ] = None,
    limit: Annotated[int | None, Query(title="Limit", description="Maximum number of items in the response.")] = None,
    offset: Annotated[int, Query(title="Offset", description="Offset in the full result set if a limit is set.")] = 0,
) -> JSONResponse:
    try:
        sort_by = parse_sort(sort)
        db_items, total_count = await order.find(db=db, shop_id=shop_id, sort_by=sort_by, limit=limit, offset=offset)
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())

    orders_out = [Order.from_db(db_item) for db_item in db_items]
    return JSONResponse(
        content=jsonable_encoder(orders_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket("", name="Listen to order changes")
async def notify_any(websocket: WebSocket) -> None:
    await websocket.accept()
    websocket_manager.connect(("order",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("order",), websocket)


@router.get(
    "/{order_id}",
    name="Get order",
    description=(
        "Get a specific order. A websocket is served on the same path to listen for changes to the order. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": OrderEvent, "description": "Websocket message"}},
)
async def get(db: Annotated[AsyncSession, Depends(get_db_session)], order_id: int) -> Order:
    db_item = await order.get_by_id(db, order_id)
    return Order.from_db(db_item)


@router.websocket("/{order_id}", name="Listen to order changes")
async def notify(websocket: WebSocket, order_id: int) -> None:
    await websocket.accept()
    websocket_manager.connect(("order", str(order_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("order", str(order_id)), websocket)


@router.post(
    "",
    name="Add order",
    description="Add a new order (with its lines) to the database.",
    response_model_exclude_none=True,
    responses={404: {"model": Message}},
)
async def create(db: Annotated[AsyncSession, Depends(get_db_session)], body: OrderParameters) -> Order:
    db_item = await order.create(
        db=db,
        shop_id=body.shop_id,
        ordered_at=body.ordered_at,
        order_number=body.order_number,
        url=body.url,
        comment=body.comment,
        lines=[line.model_dump() for line in body.lines] if body.lines is not None else None,
    )
    return Order.from_db(db_item)


@router.patch(
    "/{order_id}",
    name="Update order",
    description=(
        "Update an order. Only fields specified in the request are affected. If `lines` is present it fully "
        "replaces the existing line set; omit it to leave the lines untouched."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}},
)
async def update(db: Annotated[AsyncSession, Depends(get_db_session)], order_id: int, body: OrderParameters) -> Order:
    patch_data = body.model_dump(exclude_unset=True)
    replace_lines = "lines" in patch_data
    db_item = await order.update(db=db, order_id=order_id, data=patch_data, replace_lines=replace_lines)
    return Order.from_db(db_item)


@router.post(
    "/{order_id}/arrive",
    name="Mark order arrived",
    description=(
        "Mark order lines arrived. Omit `lines` to arrive every outstanding line; a `quantity` below a line's "
        "count splits it into an arrived part and a still-open remainder. With `create_spools`, one spool per "
        "arriving unit is created, carrying the line price and (optional) location."
    ),
    response_model_exclude_none=True,
    response_model=ArriveResponse,
    responses={400: {"model": Message}, 404: {"model": Message}},
)
async def arrive(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    order_id: int,
    body: ArriveParameters,
):
    try:
        spools = await order.arrive(
            db=db,
            order_id=order_id,
            lines=[line.model_dump() for line in body.lines] if body.lines is not None else None,
            create_spools=body.create_spools,
            location_id=body.location_id,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())
    return ArriveResponse(spools=[Spool.from_db(s) for s in spools])


@router.delete(
    "/{order_id}",
    name="Delete order",
    description="Delete an order. Its lines are cascade-deleted.",
    responses={404: {"model": Message}},
)
async def delete(db: Annotated[AsyncSession, Depends(get_db_session)], order_id: int) -> Message:
    await order.delete(db, order_id)
    return Message(message="Success!")
