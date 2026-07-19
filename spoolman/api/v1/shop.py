"""Shop related endpoints (#298)."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import Message, Shop, ShopEvent
from spoolman.database import shop
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.exceptions import ItemCreateError, ItemDeleteError
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/shop",
    tags=["shop"],
)

# ruff: noqa: D103


class ShopParameters(BaseModel):
    name: str = Field(max_length=64, description="Shop name (unique).", examples=["3DJake"])
    homepage: str | None = Field(
        None, max_length=1024, description="Shop homepage URL.", examples=["https://3djake.com"]
    )
    ships_to: list[str] | None = Field(
        None,
        description="Free-form region codes this shop ships to, e.g. ['CH', 'EU'].",
        examples=[["CH", "EU"]],
    )
    comment: str | None = Field(None, max_length=1024, description="Free text comment about this shop.", examples=[""])


class ShopUpdateParameters(ShopParameters):
    name: str | None = Field(None, max_length=64, description="Shop name (unique).", examples=["3DJake"])

    @field_validator("name")
    @classmethod
    def prevent_none(cls: type["ShopUpdateParameters"], v: str | None) -> str | None:
        """Prevent name from being None."""
        if v is None:
            raise ValueError("Value must not be None.")
        return v


@router.get(
    "",
    name="Find shop",
    description=(
        "Get a list of shops that matches the search query. "
        "A websocket is served on the same path to listen for updates to any shop, or added or deleted shops. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={200: {"model": list[Shop]}, 299: {"model": ShopEvent, "description": "Websocket message"}},
)
async def find(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[
        str | None,
        Query(
            title="Shop Name",
            description=(
                "Partial case-insensitive search term for the shop name. Separate multiple terms with a comma. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    sort: Annotated[
        str | None,
        Query(
            title="Sort",
            description='Sort by the given field. Comma-separated string of "field:direction" items.',
            examples=["name:asc,id:desc"],
        ),
    ] = None,
    limit: Annotated[int | None, Query(title="Limit", description="Maximum number of items in the response.")] = None,
    offset: Annotated[int, Query(title="Offset", description="Offset in the full result set if a limit is set.")] = 0,
) -> JSONResponse:
    try:
        sort_by = parse_sort(sort)
        db_items, total_count = await shop.find(db=db, name=name, sort_by=sort_by, limit=limit, offset=offset)
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())

    shops_out = [Shop.from_db(db_item) for db_item in db_items]
    return JSONResponse(
        content=jsonable_encoder(shops_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket("", name="Listen to shop changes")
async def notify_any(websocket: WebSocket) -> None:
    await websocket.accept()
    websocket_manager.connect(("shop",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("shop",), websocket)


@router.get(
    "/{shop_id}",
    name="Get shop",
    description=(
        "Get a specific shop. A websocket is served on the same path to listen for changes to the shop. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": ShopEvent, "description": "Websocket message"}},
)
async def get(db: Annotated[AsyncSession, Depends(get_db_session)], shop_id: int) -> Shop:
    db_item = await shop.get_by_id(db, shop_id)
    return Shop.from_db(db_item)


@router.websocket("/{shop_id}", name="Listen to shop changes")
async def notify(websocket: WebSocket, shop_id: int) -> None:
    await websocket.accept()
    websocket_manager.connect(("shop", str(shop_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("shop", str(shop_id)), websocket)


@router.post(
    "",
    name="Add shop",
    description="Add a new shop to the database.",
    response_model_exclude_none=True,
    response_model=Shop,
    responses={409: {"model": Message}},
)
async def create(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: ShopParameters,
):
    try:
        db_item = await shop.create(
            db=db,
            name=body.name,
            homepage=body.homepage,
            ships_to=body.ships_to,
            comment=body.comment,
        )
    except ItemCreateError as e:
        return JSONResponse(status_code=409, content=Message(message=str(e)).model_dump())
    return Shop.from_db(db_item)


@router.patch(
    "/{shop_id}",
    name="Update shop",
    description="Update any attribute of a shop. Only fields specified in the request will be affected.",
    response_model_exclude_none=True,
    response_model=Shop,
    responses={404: {"model": Message}, 409: {"model": Message}},
)
async def update(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    shop_id: int,
    body: ShopUpdateParameters,
):
    patch_data = body.model_dump(exclude_unset=True)
    try:
        db_item = await shop.update(db=db, shop_id=shop_id, data=patch_data)
    except ItemCreateError as e:
        return JSONResponse(status_code=409, content=Message(message=str(e)).model_dump())
    return Shop.from_db(db_item)


@router.delete(
    "/{shop_id}",
    name="Delete shop",
    description="Delete a shop. Rejected with 409 while any order references it.",
    responses={404: {"model": Message}, 409: {"model": Message}},
)
async def delete(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    shop_id: int,
):
    try:
        await shop.delete(db, shop_id)
    except ItemDeleteError as e:
        return JSONResponse(status_code=409, content=Message(message=str(e)).model_dump())
    return Message(message="Success!")
