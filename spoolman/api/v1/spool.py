"""Spool related endpoints."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import MAX_SAFE_INTEGER, Message, Spool, SpoolEvent, SpoolTag, TagConflictMessage
from spoolman.api.v1.models import SpoolUsageEvent as SpoolUsageEventModel
from spoolman.database import filament, spool

# Aliased: `tag` is taken by the find endpoint's query parameter, whose name is API surface.
from spoolman.database import tag as tag_db
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.exceptions import ItemCreateError, SpoolMeasureError, TagConflictError
from spoolman.extra_fields import (
    EXTRA_FIELD_PREFIX,
    EntityType,
    get_extra_fields,
    inherit_filament_extra_fields,
    validate_extra_field_dict,
)
from spoolman.tags import FORMAT_MAX_LENGTH, KNOWN_FORMATS, UID_MAX_LENGTH
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/spool",
    tags=["spool"],
)

# ruff: noqa: D103


class SpoolParameters(BaseModel):
    # Infinity/NaN are not valid JSON, but Starlette reads bodies with json.loads, which
    # accepts the bare literals; pydantic would then take them because allow_inf_nan defaults
    # to True. A stored non-finite weight makes json.dumps(allow_nan=False) raise on the way
    # back out, 500ing every response that contains the spool until the row is repaired (#377).
    model_config = ConfigDict(allow_inf_nan=False)

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
        le=MAX_SAFE_INTEGER,
        description="The initial weight of the filament on the spool, in grams. (net weight)",
        examples=[200],
    )
    spool_weight: float | None = Field(
        None,
        ge=0,
        le=MAX_SAFE_INTEGER,
        description="The weight of an empty spool, in grams. (tare weight)",
        examples=[200],
    )
    remaining_weight: float | None = Field(
        None,
        ge=0,
        le=MAX_SAFE_INTEGER,
        description=(
            "Remaining weight of filament on the spool. Can only be used if the filament type has a weight set."
        ),
        examples=[800],
    )
    used_weight: float | None = Field(
        None,
        ge=0,
        le=MAX_SAFE_INTEGER,
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
    extra: dict[str, str] | None = Field(
        None,
        description="Extra fields for this spool.",
    )


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
    # Infinity/NaN are not valid JSON, but Starlette reads bodies with json.loads, which
    # accepts the bare literals; pydantic would then take them because allow_inf_nan defaults
    # to True. A stored non-finite weight makes json.dumps(allow_nan=False) raise on the way
    # back out, 500ing every response that contains the spool until the row is repaired (#377).
    model_config = ConfigDict(allow_inf_nan=False)

    use_length: float | None = Field(
        None,
        ge=-MAX_SAFE_INTEGER,
        le=MAX_SAFE_INTEGER,
        description="Length of filament to reduce by, in mm.",
        examples=[2.2],
    )
    use_weight: float | None = Field(
        None,
        ge=-MAX_SAFE_INTEGER,
        le=MAX_SAFE_INTEGER,
        description="Filament weight to reduce by, in g.",
        examples=[5.3],
    )
    comment: str | None = Field(None, description="Optional comment recorded with the usage event.")


class SpoolMeasureParameters(BaseModel):
    # Infinity/NaN are not valid JSON, but Starlette reads bodies with json.loads, which
    # accepts the bare literals; pydantic would then take them because allow_inf_nan defaults
    # to True. A stored non-finite weight makes json.dumps(allow_nan=False) raise on the way
    # back out, 500ing every response that contains the spool until the row is repaired (#377).
    model_config = ConfigDict(allow_inf_nan=False)

    weight: float = Field(
        ge=-MAX_SAFE_INTEGER,
        le=MAX_SAFE_INTEGER,
        description="Current gross weight of the spool, in g.",
        examples=[200],
    )
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
    tag: Annotated[
        str | None,
        Query(
            title="Tag UID",
            description=(
                "Match the spool that an NFC/RFID tag with this UID is linked to. Exact match on the "
                "normalized UID: separators are ignored and case does not matter, so 04:A2:B3:C4, "
                "04-A2-B3-C4 and 04a2b3c4 all find the same spool. A tag is linked to at most one "
                "spool, so this returns at most one result."
            ),
            examples=["04A2B3C4D5E6F7"],
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
            tag=tag,
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


class SpoolTagParameters(BaseModel):
    uid: str = Field(
        min_length=1,
        max_length=UID_MAX_LENGTH * 2,  # room for separators; the normalized UID is what must fit
        description=(
            "The tag's hardware UID, in whatever shape the reader reports it. Separators (:, -, _, "
            "spaces) are stripped and the result is uppercased before storing, so every spelling of "
            "one physical tag resolves to the same tag."
        ),
        examples=["04:a2:b3:c4:d5:e6:f7", "04A2B3C4D5E6F7"],
    )
    format: str | None = Field(
        None,
        max_length=FORMAT_MAX_LENGTH,
        description=(
            "What kind of tag this is. Informational; not validated against a fixed list, because new "
            f"tag types appear faster than releases do. Commonly one of: {', '.join(KNOWN_FORMATS)}."
        ),
        examples=["ntag"],
    )


@router.post(
    "/{spool_id}/tag",
    name="Link a tag to a spool",
    description=(
        "Link a physical NFC/RFID tag to this spool, so that the tag's UID identifies it. "
        "A tag belongs to exactly one spool; linking a UID that another spool already holds "
        "returns 409 with that spool's id, so a client can offer to move it instead. "
        "Re-linking a tag to the spool that already holds it succeeds and changes nothing, "
        "except that a format sent now refines one recorded earlier.\n\n"
        "This is a separate mechanism from this instance's existing NFC/RFID tag support "
        "(POST /nfc/write and friends, which bind a tag via the spool's nfc_tag_uid extra "
        "field): the two do not interact."
    ),
    status_code=201,
    response_model_exclude_none=True,
    response_model=SpoolTag,
    responses={
        400: {"model": Message},
        404: {"model": Message},
        409: {"model": TagConflictMessage},
    },
)
async def link_tag(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
    body: SpoolTagParameters,
):
    try:
        db_item = await tag_db.link(db=db, spool_id=spool_id, uid=body.uid, tag_format=body.format)
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).dict())
    except TagConflictError as e:
        return JSONResponse(
            status_code=409,
            content=TagConflictMessage(message=str(e), spool_id=e.spool_id).dict(),
        )
    return SpoolTag.from_db(db_item)


@router.delete(
    "/{spool_id}/tag/{uid}",
    name="Unlink a tag from a spool",
    description=(
        "Unlink a physical NFC/RFID tag from this spool. The UID is matched the same way it is "
        "stored: separators are ignored and case does not matter. Deleting a spool unlinks its "
        "tags on its own, so this is only for taking one tag off a spool that keeps existing."
    ),
    status_code=204,
    responses={400: {"model": Message}, 404: {"model": Message}},
)
async def unlink_tag(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    spool_id: int,
    uid: Annotated[
        str,
        Path(
            title="Tag UID",
            description="The tag's UID, in any shape. Normalized before matching.",
            examples=["04A2B3C4D5E6F7"],
        ),
    ],
) -> Response:
    try:
        await tag_db.unlink(db=db, spool_id=spool_id, uid=uid)
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).dict())
    return Response(status_code=204)
