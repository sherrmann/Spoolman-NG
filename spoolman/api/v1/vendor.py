"""Vendor related endpoints."""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import duplicates
from spoolman.api.v1.models import Message, Vendor, VendorEvent
from spoolman.database import vendor
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.extra_fields import EXTRA_FIELD_PREFIX, EntityType, get_extra_fields, validate_extra_field_dict
from spoolman.ws import websocket_manager

router = APIRouter(
    prefix="/vendor",
    tags=["vendor"],
)

# ruff: noqa: D103


class VendorParameters(BaseModel):
    name: str = Field(max_length=64, description="Vendor name.", examples=["Polymaker"])
    comment: str | None = Field(
        None,
        max_length=1024,
        description="Free text comment about this vendor.",
        examples=[""],
    )
    empty_spool_weight: float | None = Field(
        None,
        ge=0,
        description="The weight of an empty spool, in grams.",
        examples=[200],
    )
    external_id: str | None = Field(
        None,
        max_length=256,
        description=(
            "Set if this vendor comes from an external database. This contains the ID in the external database."
        ),
        examples=["eSun"],
    )
    extra: dict[str, str] | None = Field(
        None,
        description="Extra fields for this vendor.",
    )


class VendorUpdateParameters(VendorParameters):
    name: str | None = Field(None, max_length=64, description="Vendor name.", examples=["Polymaker"])
    extra: dict[str, str | None] | None = Field(  # type: ignore[assignment]  # None clears the key
        None,
        description=(
            "Extra fields to change on this vendor. Keys present are set to the given value, "
            "a null value removes the key, and keys not mentioned are left unchanged."
        ),
    )

    @field_validator("name")
    @classmethod
    def prevent_none(cls: type["VendorUpdateParameters"], v: str | None) -> str | None:
        """Prevent name from being None."""
        if v is None:
            raise ValueError("Value must not be None.")
        return v


@router.get(
    "",
    name="Find vendor",
    description=(
        "Get a list of vendors that matches the search query. "
        "A websocket is served on the same path to listen for updates to any vendor, or added or deleted vendors. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={
        200: {"model": list[Vendor]},
        299: {"model": VendorEvent, "description": "Websocket message"},
    },
)
async def find(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[
        str | None,
        Query(
            title="Vendor Name",
            description=(
                "Partial case-insensitive search term for the vendor name. Separate multiple terms with a comma. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    external_id: Annotated[
        str | None,
        Query(
            title="Vendor External ID",
            description=(
                "Exact match for the vendor external ID. "
                "Separate multiple IDs with a comma. "
                "Specify empty string to match filaments with no external ID. "
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
        db_items, total_count = await vendor.find(
            db=db,
            name=name,
            external_id=external_id,
            extra_field_filters=extra_field_filters if extra_field_filters else None,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    # Populate the per-vendor filament_count / spool_count aggregates (issue #49) for the returned
    # page, then attach them to each response object.
    aggregates = await vendor.get_aggregates(db, [db_item.id for db_item in db_items])
    vendors_out = [
        Vendor.from_db(
            db_item,
            filament_count=aggregates.get(db_item.id, (None, None))[0],
            spool_count=aggregates.get(db_item.id, (None, None))[1],
        )
        for db_item in db_items
    ]

    # Set x-total-count header for pagination
    return JSONResponse(
        content=jsonable_encoder(vendors_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket(
    "",
    name="Listen to vendor changes",
)
async def notify_any(
    websocket: WebSocket,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("vendor",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("vendor",), websocket)


@router.get(
    "/{vendor_id}",
    name="Get vendor",
    description=(
        "Get a specific vendor. A websocket is served on the same path to listen for changes to the vendor. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": VendorEvent, "description": "Websocket message"}},
)
async def get(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    vendor_id: int,
) -> Vendor:
    db_item = await vendor.get_by_id(db, vendor_id)
    filament_count, spool_count = (await vendor.get_aggregates(db, [vendor_id])).get(vendor_id, (0, 0))
    return Vendor.from_db(db_item, filament_count=filament_count, spool_count=spool_count)


@router.websocket(
    "/{vendor_id}",
    name="Listen to vendor changes",
)
async def notify(
    websocket: WebSocket,
    vendor_id: int,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("vendor", str(vendor_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("vendor", str(vendor_id)), websocket)


@router.post(
    "",
    name="Add vendor",
    description="Add a new vendor to the database.",
    response_model_exclude_none=True,
    response_model=Vendor,
    responses={400: {"model": Message}},
)
async def create(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: VendorParameters,
):
    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.vendor) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())

    db_item = await vendor.create(
        db=db,
        name=body.name,
        comment=body.comment,
        empty_spool_weight=body.empty_spool_weight,
        external_id=body.external_id,
        extra=body.extra,
    )

    # The stock aggregates are a read-time view; POST returns the stored resource unchanged so the
    # create response shape stays identical to before this feature (integrations POSTing are unaffected).
    return Vendor.from_db(db_item)


class SimilarVendorRequest(BaseModel):
    name: str = Field(max_length=64, description="The vendor name being typed.")
    exclude_id: int | None = Field(None, description="A vendor to leave out, such as the one being renamed.")


class SimilarVendor(BaseModel):
    id: int
    name: str
    probability: float | None = Field(None, description="The decision model's probability; null for an exact match.")


class SimilarVendorResponse(BaseModel):
    exact: SimilarVendor | None = Field(None, description="A vendor with the same name, ignoring case and punctuation.")
    suggestion: SimilarVendor | None = Field(
        None,
        description="A vendor the decision model thinks is the same company. Only with the duplicate check on.",
    )
    source: Literal["exact", "model"] | None = Field(None, description="Which check produced the hint.")


@router.post(
    "/similar",
    name="Find a similar vendor",
    description=(
        "Check whether a vendor name duplicates an existing vendor, before creating it. An exact match "
        "(ignoring case, spacing and punctuation) is always checked. With the duplicate-check AI feature "
        "on and a decision model configured, the model is also asked whether the name is an existing "
        "vendor written differently; that sends the name and the existing vendor names to the decision "
        "endpoint. Never creates anything, and a failing model gives no suggestion rather than an error."
    ),
)
async def similar(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: SimilarVendorRequest,
) -> SimilarVendorResponse:
    result = await duplicates.similar_vendor(db, body.name, exclude_id=body.exclude_id)

    def _out(match: duplicates.Match | None) -> SimilarVendor | None:
        return None if match is None else SimilarVendor(id=match.id, name=match.name, probability=match.probability)

    return SimilarVendorResponse(exact=_out(result.exact), suggestion=_out(result.suggestion), source=result.source)


@router.patch(
    "/{vendor_id}",
    name="Update vendor",
    description=(
        "Update any attribute of a vendor. Only fields specified in the request will be affected. "
        "Extra fields merge per key: keys in the request are set, a null value removes the key, and "
        "keys not mentioned are left unchanged."
    ),
    response_model_exclude_none=True,
    response_model=Vendor,
    responses={
        400: {"model": Message},
        404: {"model": Message},
    },
)
async def update(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    vendor_id: int,
    body: VendorUpdateParameters,
):
    patch_data = body.model_dump(exclude_unset=True)

    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.vendor) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    db_item = await vendor.update(
        db=db,
        vendor_id=vendor_id,
        data=patch_data,
    )

    return Vendor.from_db(db_item)


@router.delete(
    "/{vendor_id}",
    name="Delete vendor",
    description=(
        "Delete a vendor. The vendor attribute of any filaments who refer to the deleted vendor will be cleared."
    ),
    responses={404: {"model": Message}},
)
async def delete(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    vendor_id: int,
) -> Message:
    await vendor.delete(db, vendor_id)
    return Message(message="Success!")
