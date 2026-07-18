"""Spool related endpoints."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import Message, MultiColorDirection, Spool, SpoolEvent
from spoolman.api.v1.models import SpoolUsageEvent as SpoolUsageEventModel
from spoolman.database import filament, spool
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.exceptions import ItemCreateError, SpoolMeasureError
from spoolman.extra_fields import (
    EXTRA_FIELD_PREFIX,
    EntityType,
    get_extra_fields,
    inherit_filament_extra_fields,
    validate_extra_field_dict,
)
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/spool",
    tags=["spool"],
)

# ruff: noqa: D103


class SpoolParameters(BaseModel):
    first_used: datetime | None = Field(None, description="First logged occurence of spool usage.")
    last_used: datetime | None = Field(None, description="Last logged occurence of spool usage.")
    filament_id: int = Field(description="The ID of the filament type of this spool.")
    price: float | None = Field(
        None,
        ge=0,
        description="The price of this filament in the system configured currency.",
        examples=[20.0],
    )
    initial_weight: float | None = Field(
        None,
        ge=0,
        description="The initial weight of the filament on the spool, in grams. (net weight)",
        examples=[200],
    )
    spool_weight: float | None = Field(
        None,
        ge=0,
        description="The weight of an empty spool, in grams. (tare weight)",
        examples=[200],
    )
    remaining_weight: float | None = Field(
        None,
        ge=0,
        description=(
            "Remaining weight of filament on the spool. Can only be used if the filament type has a weight set."
        ),
        examples=[800],
    )
    used_weight: float | None = Field(
        None,
        ge=0,
        description="Used weight of filament on the spool.",
        examples=[200],
    )
    location: str | None = Field(
        None,
        max_length=64,
        description="Where this spool can be found.",
        examples=["Shelf A"],
    )
    printer_id: int | None = Field(
        None,
        description="The ID of the printer this spool is assigned to (#75). Null to leave it unassigned.",
        examples=[1],
    )
    lot_nr: str | None = Field(
        None,
        max_length=64,
        description="Vendor manufacturing lot/batch number of the spool.",
        examples=["52342"],
    )
    comment: str | None = Field(
        None,
        max_length=1024,
        description="Free text comment about this specific spool.",
        examples=[""],
    )
    archived: bool = Field(default=False, description="Whether this spool is archived and should not be used anymore.")
    diameter: float | None = Field(
        None,
        gt=0,
        description=(
            "Measured per-spool filament diameter in mm, overriding the filament's nominal diameter in "
            "length calculations (#101). Leave unset to use the filament's diameter."
        ),
        examples=[1.73],
    )
    color_hex: str | None = Field(
        None,
        description=(
            "Per-spool color override in hexadecimal RGBA (#74), overriding the filament's color. Supports an "
            "alpha channel at the end. Leave unset to use the filament's color. For a multi-color override use "
            "multi_color_hexes instead."
        ),
        examples=["FF0000"],
    )
    multi_color_hexes: str | None = Field(
        None,
        description=(
            "Per-spool multi-color override: hexadecimal RGBA colors separated by commas (#74). Also set "
            "multi_color_direction. Leave unset to use the filament's color."
        ),
        examples=["FF0000,00FF00,0000FF"],
    )
    multi_color_direction: MultiColorDirection | None = Field(
        None,
        description="Type of multi-color override. Only set if multi_color_hexes contains multiple colors.",
        examples=["coaxial", "longitudinal"],
    )
    extra: dict[str, str] | None = Field(
        None,
        description="Extra fields for this spool.",
    )

    @field_validator("color_hex")
    @classmethod
    def color_hex_validator(cls, v: str | None) -> str | None:
        """Normalize and validate the color override (mirrors the filament validator, incl. #45 guard)."""
        if not v:
            return None
        clr = v.upper().removeprefix("#")
        for c in clr:
            if c not in "0123456789ABCDEF":
                raise ValueError("Invalid character in color code.")
        if len(clr) not in (6, 8):
            raise ValueError("Color code must be 6 or 8 characters long.")
        # Return the normalized (uppercased, '#'-stripped) value so a '#FF000000' can't overflow the
        # String(8) column and 500 every read (see filament color_hex_validator / issue #45).
        return clr

    @field_validator("multi_color_hexes")
    @classmethod
    def multi_color_hexes_validator(cls, v: str | None) -> str | None:
        """Normalize and validate the multi-color override (mirrors the filament validator)."""
        if not v:
            return None
        normalized: list[str] = []
        for clr_raw in v.split(","):
            clr = clr_raw.upper().removeprefix("#")
            for c in clr:
                if c not in "0123456789ABCDEF":
                    raise ValueError("Invalid character in color code.")
            if len(clr) not in (6, 8):
                raise ValueError("Color code must be 6 or 8 characters long.")
            normalized.append(clr)
        return ",".join(normalized)

    @model_validator(mode="after")
    def validate_color_override(self) -> "SpoolParameters":
        """Enforce the same color invariants as the filament (single vs multi, direction)."""
        if self.color_hex and self.multi_color_hexes:
            raise ValueError("Cannot specify both color_hex and multi_color_hexes.")
        if self.multi_color_hexes and len(self.multi_color_hexes.split(",")) < 2:  # noqa: PLR2004
            raise ValueError("Must specify at least two colors in multi_color_hexes.")
        if self.multi_color_hexes and not self.multi_color_direction:
            raise ValueError("Multi-color override must have multi_color_direction set.")
        if not self.multi_color_hexes and self.multi_color_direction:
            raise ValueError("Single-color override must not have multi_color_direction set.")
        return self


class SpoolUpdateParameters(SpoolParameters):
    filament_id: int | None = Field(None, description="The ID of the filament type of this spool.")
    extra: dict[str, str | None] | None = Field(  # type: ignore[assignment]  # None marks deletion (#233)
        None,
        description=(
            "Extra fields to change on this spool. Keys present are set to the given value, "
            "a null value removes the key, and keys not mentioned are left unchanged."
        ),
    )
    label_printed_at: datetime | None = Field(
        None,
        description=(
            "When a label was last printed for this spool. Set by the label-printing flow; "
            "pass null to clear the printed marker."
        ),
    )

    @field_validator("filament_id")
    @classmethod
    def prevent_none(cls: type["SpoolUpdateParameters"], v: int | None) -> int | None:
        """Prevent filament_id from being None."""
        if v is None:
            raise ValueError("Value must not be None.")
        return v


class SpoolUseParameters(BaseModel):
    use_length: float | None = Field(None, description="Length of filament to reduce by, in mm.", examples=[2.2])
    use_weight: float | None = Field(None, description="Filament weight to reduce by, in g.", examples=[5.3])
    comment: str | None = Field(None, description="Optional comment recorded with the usage event.")


class SpoolMeasureParameters(BaseModel):
    weight: float = Field(description="Current gross weight of the spool, in g.", examples=[200])
    comment: str | None = Field(None, description="Optional comment recorded with the usage event.")


@router.get(
    "",
    name="Find spool",
    description=(
        "Get a list of spools that matches the search query. "
        "A websocket is served on the same path to listen for updates to any spool, or added or deleted spools. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={
        200: {"model": list[Spool]},
        299: {"model": SpoolEvent, "description": "Websocket message"},
    },
)
async def find(
    *,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    search: Annotated[
        str | None,
        Query(
            title="Search",
            description=(
                "Partial case-insensitive search term applied across spool ID, comment, lot number, location and "
                "the linked filament's vendor name, name, material and article number. Separate multiple terms with "
                "a comma. Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    filament_name_old: Annotated[
        str | None,
        Query(alias="filament_name", title="Filament Name", description="See filament.name.", deprecated=True),
    ] = None,
    filament_id_old: Annotated[
        str | None,
        Query(
            alias="filament_id",
            title="Filament ID",
            description="See filament.id.",
            deprecated=True,
            pattern=r"^-?\d+(,-?\d+)*$",
        ),
    ] = None,
    filament_material_old: Annotated[
        str | None,
        Query(
            alias="filament_material",
            title="Filament Material",
            description="See filament.material.",
            deprecated=True,
        ),
    ] = None,
    vendor_name_old: Annotated[
        str | None,
        Query(alias="vendor_name", title="Vendor Name", description="See filament.vendor.name.", deprecated=True),
    ] = None,
    vendor_id_old: Annotated[
        str | None,
        Query(
            alias="vendor_id",
            title="Vendor ID",
            description="See filament.vendor.id.",
            deprecated=True,
            pattern=r"^-?\d+(,-?\d+)*$",
        ),
    ] = None,
    filament_name: Annotated[
        str | None,
        Query(
            alias="filament.name",
            title="Filament Name",
            description=(
                "Partial case-insensitive search term for the filament name. Separate multiple terms with a comma. "
                "Specify an empty string to match spools with no filament name. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    filament_id: Annotated[
        str | None,
        Query(
            alias="filament.id",
            title="Filament ID",
            description="Match an exact filament ID. Separate multiple IDs with a comma.",
            examples=["1", "1,2"],
            pattern=r"^-?\d+(,-?\d+)*$",
        ),
    ] = None,
    filament_material: Annotated[
        str | None,
        Query(
            alias="filament.material",
            title="Filament Material",
            description=(
                "Partial case-insensitive search term for the filament material. Separate multiple terms with a comma. "
                "Specify an empty string to match spools with no filament material. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    filament_vendor_name: Annotated[
        str | None,
        Query(
            alias="filament.vendor.name",
            title="Vendor Name",
            description=(
                "Partial case-insensitive search term for the filament vendor name. "
                "Separate multiple terms with a comma. "
                "Specify an empty string to match spools with no vendor name. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    filament_vendor_id: Annotated[
        str | None,
        Query(
            alias="filament.vendor.id",
            title="Vendor ID",
            description=(
                "Match an exact vendor ID. Separate multiple IDs with a comma. "
                "Set it to -1 to match spools with filaments with no vendor."
            ),
            examples=["1", "1,2"],
            pattern=r"^-?\d+(,-?\d+)*$",
        ),
    ] = None,
    location: Annotated[
        str | None,
        Query(
            title="Location",
            description=(
                "Partial case-insensitive search term for the spool location. Separate multiple terms with a comma. "
                "Specify an empty string to match spools with no location. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    lot_nr: Annotated[
        str | None,
        Query(
            title="Lot/Batch Number",
            description=(
                "Partial case-insensitive search term for the spool lot number. Separate multiple terms with a comma. "
                "Specify an empty string to match spools with no lot nr. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    allow_archived: Annotated[
        bool,
        Query(title="Allow Archived", description="Whether to include archived spools in the search results."),
    ] = False,
    archived: Annotated[
        bool | None,
        Query(
            title="Archived",
            description=(
                "Filter by archived state: true returns only archived spools, false only active ones. "
                "Takes precedence over allow_archived. Omit to keep the allow_archived behavior."
            ),
        ),
    ] = None,
    color_hex: Annotated[
        str | None,
        Query(
            title="Filament Color",
            description="Match spools whose filament has a similar color. Slow operation!",
        ),
    ] = None,
    color_similarity_threshold: Annotated[
        float,
        Query(
            description=(
                "The similarity threshold for color matching. "
                "A value between 0.0-100.0, where 0 means match only exactly the same color."
            ),
            examples=[20.0],
        ),
    ] = 20.0,
    sort: Annotated[
        str | None,
        Query(
            title="Sort",
            description=(
                'Sort the results by the given field. Should be a comma-separate string with "field:direction" items.'
            ),
            examples=["filament.name:asc,filament.vendor.id:asc,location:desc"],
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(title="Limit", description="Maximum number of items in the response."),
    ] = None,
    offset: Annotated[int, Query(title="Offset", description="Offset in the full result set if a limit is set.")] = 0,
) -> JSONResponse:
    filament_id = filament_id if filament_id is not None else filament_id_old
    if filament_id is not None:
        filament_ids = [int(filament_id_item) for filament_id_item in filament_id.split(",")]
    else:
        filament_ids = None

    filament_vendor_id = filament_vendor_id if filament_vendor_id is not None else vendor_id_old
    if filament_vendor_id is not None:
        filament_vendor_ids = [int(vendor_id_item) for vendor_id_item in filament_vendor_id.split(",")]
    else:
        filament_vendor_ids = None

    # Color-similarity filter (#46): resolve the filaments whose colour is close to the query,
    # then narrow the spool search to their IDs. Intersect with any explicit filament filter so
    # the two combine with AND; an empty intersection correctly yields no spools.
    if color_hex is not None:
        color_matched_ids = {
            f.id
            for f in await filament.find_by_color(
                db=db,
                color_query_hex=color_hex,
                similarity_threshold=color_similarity_threshold,
            )
        }
        if filament_ids is None:
            filament_ids = list(color_matched_ids)
        else:
            filament_ids = [fid for fid in filament_ids if fid in color_matched_ids]

    # Extract custom field filters from query parameters
    extra_field_filters = {}
    query_params = request.query_params
    for key, value in query_params.items():
        if key.startswith(EXTRA_FIELD_PREFIX):
            field_key = key[len(EXTRA_FIELD_PREFIX) :]  # Remove "extra." prefix
            extra_field_filters[field_key] = value

    try:
        sort_by = parse_sort(sort)
        db_items, total_count = await spool.find(
            db=db,
            search=search,
            filament_name=filament_name if filament_name is not None else filament_name_old,
            filament_id=filament_ids,
            filament_material=filament_material if filament_material is not None else filament_material_old,
            vendor_name=filament_vendor_name if filament_vendor_name is not None else vendor_name_old,
            vendor_id=filament_vendor_ids,
            location=location,
            lot_nr=lot_nr,
            allow_archived=allow_archived,
            archived=archived,
            extra_field_filters=extra_field_filters if extra_field_filters else None,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    # Set x-total-count header for pagination
    return JSONResponse(
        content=jsonable_encoder(
            (Spool.from_db(db_item) for db_item in db_items),
            exclude_none=True,
        ),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket(
    "",
    name="Listen to spool changes",
)
async def notify_any(
    websocket: WebSocket,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("spool",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("spool",), websocket)


@router.get(
    "/{spool_id}",
    name="Get spool",
    description=(
        "Get a specific spool. A websocket is served on the same path to listen for changes to the spool. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": SpoolEvent, "description": "Websocket message"}},
)
async def get(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
) -> Spool:
    db_item = await spool.get_by_id(db, spool_id)
    return Spool.from_db(db_item)


@router.websocket(
    "/{spool_id}",
    name="Listen to spool changes",
)
async def notify(
    websocket: WebSocket,
    spool_id: int,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("spool", str(spool_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("spool", str(spool_id)), websocket)


@router.post(
    "",
    name="Add spool",
    description=(
        "Add a new spool to the database. "
        "Only specify either remaining_weight or used_weight. "
        "If no weight is set, the spool will be assumed to be full."
    ),
    response_model_exclude_none=True,
    response_model=Spool,
    responses={
        400: {"model": Message},
    },
)
async def create(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: SpoolParameters,
):
    if body.remaining_weight is not None and body.used_weight is not None:
        return JSONResponse(
            status_code=400,
            content={"message": "Only specify either remaining_weight or used_weight."},
        )

    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.spool) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    # Inherit any linked filament extra fields the spool didn't supply itself (#118). Each inherited
    # value is validated against its spool field inside the helper, so the merged dict stays valid.
    extra = await inherit_filament_extra_fields(db, filament_id=body.filament_id, extra=body.extra)

    try:
        db_item = await spool.create(
            db=db,
            filament_id=body.filament_id,
            price=body.price,
            initial_weight=body.initial_weight,
            spool_weight=body.spool_weight,
            remaining_weight=body.remaining_weight,
            used_weight=body.used_weight,
            first_used=body.first_used,
            last_used=body.last_used,
            location=body.location,
            printer_id=body.printer_id,
            lot_nr=body.lot_nr,
            comment=body.comment,
            archived=body.archived,
            diameter=body.diameter,
            color_hex=body.color_hex,
            multi_color_hexes=body.multi_color_hexes,
            multi_color_direction=body.multi_color_direction,
            extra=extra,
        )
        return Spool.from_db(db_item)
    except ItemCreateError:
        logger.exception("Failed to create spool.")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to create spool, see server logs for more information."},
        )


@router.patch(
    "/{spool_id}",
    name="Update spool",
    description=(
        "Update any attribute of a spool. "
        "Only fields specified in the request will be affected. "
        "remaining_weight and used_weight can't be set at the same time. "
        "If extra is set, its keys are merged into the spool's existing extra fields: each key "
        "present is set to its value, a null value removes the key, and keys not mentioned are "
        "left unchanged. (Deliberately unlike the other entities, which replace the whole set: "
        "concurrent writers - e.g. the NFC flow and a user edit - must not clobber each other.)"
    ),
    response_model_exclude_none=True,
    response_model=Spool,
    responses={
        400: {"model": Message},
        404: {"model": Message},
    },
)
async def update(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
    body: SpoolUpdateParameters,
):
    patch_data = body.model_dump(exclude_unset=True)

    if body.remaining_weight is not None and body.used_weight is not None:
        return JSONResponse(
            status_code=400,
            content={"message": "Only specify either remaining_weight or used_weight."},
        )

    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.spool) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    try:
        db_item = await spool.update(
            db=db,
            spool_id=spool_id,
            data=patch_data,
        )
    except ItemCreateError:
        logger.exception("Failed to update spool.")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to update spool, see server logs for more information."},
        )

    return Spool.from_db(db_item)


@router.delete(
    "/{spool_id}",
    name="Delete spool",
    description="Delete a spool.",
    responses={404: {"model": Message}},
)
async def delete(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
) -> Message:
    await spool.delete(db, spool_id)
    return Message(message="Success!")


@router.put(
    "/{spool_id}/use",
    name="Use spool filament",
    description=(
        "Use some length or weight of filament from the spool. Specify either a length or a weight, not both."
    ),
    response_model_exclude_none=True,
    response_model=Spool,
    responses={
        400: {"model": Message},
        404: {"model": Message},
    },
)
async def use(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
    body: SpoolUseParameters,
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Optional client-supplied key making this call safe to retry (#60). A repeat with the "
                "same key returns the current spool without applying the change again."
            ),
        ),
    ] = None,
):
    if body.use_weight is not None and body.use_length is not None:
        return JSONResponse(
            status_code=400,
            content={"message": "Only specify either use_weight or use_length."},
        )
    if body.use_weight is None and body.use_length is None:
        return JSONResponse(
            status_code=400,
            content={"message": "Either use_weight or use_length must be specified."},
        )

    # Idempotency (#60): a key already recorded for this spool means this request was applied before;
    # return the current spool unchanged. Absent key ⇒ exact previous behaviour (Moonraker untouched).
    if idempotency_key is not None and await spool.find_usage_event_by_key(db, spool_id, idempotency_key):
        response.headers["Idempotency-Replayed"] = "true"
        return Spool.from_db(await spool.get_by_id(db, spool_id))

    try:
        if body.use_weight is not None:
            db_item = await spool.use_weight(
                db,
                spool_id,
                body.use_weight,
                comment=body.comment,
                idempotency_key=idempotency_key,
            )
        else:
            db_item = await spool.use_length(
                db,
                spool_id,
                body.use_length,
                comment=body.comment,
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # A concurrent request applied this key first; treat as a replay rather than double-count.
        await db.rollback()
        response.headers["Idempotency-Replayed"] = "true"
        return Spool.from_db(await spool.get_by_id(db, spool_id))

    logger.info(
        "Spool #%s use: requested weight=%s length=%s → used_weight=%sg",
        spool_id,
        body.use_weight,
        body.use_length,
        db_item.used_weight,
    )
    return Spool.from_db(db_item)


@router.put(
    "/{spool_id}/measure",
    name="Use spool filament based on the current weight measurement",
    description=("Use some weight of filament from the spool. Specify the current gross weight of the spool."),
    response_model_exclude_none=True,
    response_model=Spool,
    responses={
        400: {"model": Message},
        404: {"model": Message},
    },
)
async def measure(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
    body: SpoolMeasureParameters,
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Optional client-supplied key making this call safe to retry (#60). A repeat with the "
                "same key returns the current spool without applying the change again."
            ),
        ),
    ] = None,
):
    if idempotency_key is not None and await spool.find_usage_event_by_key(db, spool_id, idempotency_key):
        response.headers["Idempotency-Replayed"] = "true"
        return Spool.from_db(await spool.get_by_id(db, spool_id))

    try:
        db_item = await spool.measure(
            db,
            spool_id,
            body.weight,
            comment=body.comment,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        await db.rollback()
        response.headers["Idempotency-Replayed"] = "true"
        return Spool.from_db(await spool.get_by_id(db, spool_id))
    except SpoolMeasureError as e:
        logger.exception("Failed to update spool measurement.")
        return JSONResponse(
            status_code=400,
            content={"message": e.args[0]},
        )
    logger.info(
        "Spool #%s measure: gross=%sg → used_weight=%sg",
        spool_id,
        body.weight,
        db_item.used_weight,
    )
    return Spool.from_db(db_item)


@router.get(
    "/{spool_id}/events",
    name="Get spool usage events",
    description="Get the timestamped usage/adjustment events recorded for a spool, most recent first.",
    response_model_exclude_none=True,
    response_model=list[SpoolUsageEventModel],
    responses={404: {"model": Message}},
)
async def usage_events(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
    limit: Annotated[int | None, Query(description="Maximum number of events in the response.")] = None,
    offset: Annotated[int, Query(description="Offset in the full result set if a limit is set.")] = 0,
):
    await spool.get_by_id(db, spool_id)  # Raises 404 if the spool doesn't exist.
    events, total_count = await spool.get_usage_events(db, spool_id, limit=limit, offset=offset)
    return JSONResponse(
        content=jsonable_encoder(
            [SpoolUsageEventModel.from_db(event) for event in events],
            exclude_none=True,
        ),
        headers={"x-total-count": str(total_count)},
    )
