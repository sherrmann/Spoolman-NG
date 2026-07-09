"""Location related endpoints.

Locations are promoted to a first-class entity (issue #103) so custom fields can be attached to
them. This lives at the PLURAL ``/locations`` prefix on purpose: the singular ``/location`` path is
already owned by the byte-identical string endpoints in ``other.py`` (``GET /location`` returns the
distinct ``Spool.location`` strings, ``PATCH /location/{location}`` bulk-renames them), which must
stay unchanged for integrations. ``Spool.location`` remains a plain string column; this entity is a
parallel name registry.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import Location, LocationEvent, Message
from spoolman.database import location
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.extra_fields import EXTRA_FIELD_PREFIX, EntityType, get_extra_fields, validate_extra_field_dict
from spoolman.ws import websocket_manager

router = APIRouter(
    prefix="/locations",
    tags=["location"],
)

# ruff: noqa: D103


class LocationParameters(BaseModel):
    name: str = Field(max_length=64, description="Location name.", examples=["Dry Box 1"])
    comment: str | None = Field(
        None,
        max_length=1024,
        description="Free text comment about this location.",
        examples=[""],
    )
    extra: dict[str, str] | None = Field(
        None,
        description="Extra fields for this location.",
    )


class LocationUpdateParameters(LocationParameters):
    name: str | None = Field(None, max_length=64, description="Location name.", examples=["Dry Box 1"])

    @field_validator("name")
    @classmethod
    def prevent_none(cls: type["LocationUpdateParameters"], v: str | None) -> str | None:
        """Prevent name from being None."""
        if v is None:
            raise ValueError("Value must not be None.")
        return v


@router.get(
    "",
    name="Find location",
    description=(
        "Get a list of locations that matches the search query. "
        "A websocket is served on the same path to listen for updates to any location, or added or "
        "deleted locations. See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={
        200: {"model": list[Location]},
        299: {"model": LocationEvent, "description": "Websocket message"},
    },
)
async def find(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[
        str | None,
        Query(
            title="Location Name",
            description=(
                "Partial case-insensitive search term for the location name. Separate multiple terms with a comma. "
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
        db_items, total_count = await location.find(
            db=db,
            name=name,
            extra_field_filters=extra_field_filters if extra_field_filters else None,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    # Populate the per-location spool_count aggregate (issue #103) for the returned page.
    aggregates = await location.get_aggregates(db, [db_item.id for db_item in db_items])
    locations_out = [Location.from_db(db_item, spool_count=aggregates.get(db_item.id)) for db_item in db_items]

    # Set x-total-count header for pagination
    return JSONResponse(
        content=jsonable_encoder(locations_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket(
    "",
    name="Listen to location changes",
)
async def notify_any(
    websocket: WebSocket,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("location",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("location",), websocket)


@router.get(
    "/{location_id}",
    name="Get location",
    description=(
        "Get a specific location. A websocket is served on the same path to listen for changes to the location. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": LocationEvent, "description": "Websocket message"}},
)
async def get(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    location_id: int,
) -> Location:
    db_item = await location.get_by_id(db, location_id)
    spool_count = (await location.get_aggregates(db, [location_id])).get(location_id, 0)
    return Location.from_db(db_item, spool_count=spool_count)


@router.websocket(
    "/{location_id}",
    name="Listen to location changes",
)
async def notify(
    websocket: WebSocket,
    location_id: int,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("location", str(location_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("location", str(location_id)), websocket)


@router.post(
    "",
    name="Add location",
    description="Add a new location to the database.",
    response_model_exclude_none=True,
    response_model=Location,
    responses={400: {"model": Message}},
)
async def create(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: LocationParameters,
):
    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.location) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())

    db_item = await location.create(
        db=db,
        name=body.name,
        comment=body.comment,
        extra=body.extra,
    )

    # The spool_count aggregate is a read-time view; POST returns the stored resource unchanged.
    return Location.from_db(db_item)


@router.patch(
    "/{location_id}",
    name="Update location",
    description=(
        "Update any attribute of a location. Only fields specified in the request will be affected. "
        "If extra is set, all existing extra fields will be removed and replaced with the new ones."
    ),
    response_model_exclude_none=True,
    response_model=Location,
    responses={
        400: {"model": Message},
        404: {"model": Message},
    },
)
async def update(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    location_id: int,
    body: LocationUpdateParameters,
):
    patch_data = body.model_dump(exclude_unset=True)

    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.location) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    db_item = await location.update(
        db=db,
        location_id=location_id,
        data=patch_data,
    )

    return Location.from_db(db_item)


@router.delete(
    "/{location_id}",
    name="Delete location",
    description="Delete a location. This does not affect any spools; Spool.location is a free string.",
    responses={404: {"model": Message}},
)
async def delete(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    location_id: int,
) -> Message:
    await location.delete(db, location_id)
    return Message(message="Success!")
