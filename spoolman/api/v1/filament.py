"""Filament related endpoints."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import (
    Filament,
    FilamentEvent,
    Finish,
    Message,
    MultiColorDirection,
    Pattern,
    SpoolType,
)
from spoolman.database import filament
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.exceptions import ItemDeleteError
from spoolman.extra_fields import EXTRA_FIELD_PREFIX, EntityType, get_extra_fields, validate_extra_field_dict
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/filament",
    tags=["filament"],
)

# ruff: noqa: D103


class FilamentParameters(BaseModel):
    name: str | None = Field(
        None,
        max_length=64,
        description=(
            "Filament name, to distinguish this filament type among others from the same vendor."
            "Should contain its color for example."
        ),
        examples=["PolyTerra™ Charcoal Black"],
    )
    vendor_id: int | None = Field(None, description="The ID of the vendor of this filament type.")
    material: str | None = Field(
        None,
        max_length=64,
        description="The material of this filament, e.g. PLA.",
        examples=["PLA"],
    )
    price: float | None = Field(
        None,
        ge=0,
        description="The price of this filament in the system configured currency.",
        examples=[20.0],
    )
    density: float = Field(gt=0, description="The density of this filament in g/cm3.", examples=[1.24])
    diameter: float = Field(gt=0, description="The diameter of this filament in mm.", examples=[1.75])
    weight: float | None = Field(
        None,
        gt=0,
        description="The weight of the filament in a full spool, in grams. (net weight)",
        examples=[1000],
    )
    spool_weight: float | None = Field(None, ge=0, description="The empty spool weight, in grams.", examples=[140])
    article_number: str | None = Field(
        None,
        max_length=64,
        description="Vendor article number, e.g. EAN, QR code, etc.",
        examples=["PM70820"],
    )
    comment: str | None = Field(
        None,
        max_length=1024,
        description="Free text comment about this filament type.",
        examples=[""],
    )
    settings_extruder_temp: int | None = Field(
        None,
        ge=0,
        description="Overridden extruder temperature, in °C.",
        examples=[210],
    )
    settings_bed_temp: int | None = Field(
        None,
        ge=0,
        description="Overridden bed temperature, in °C.",
        examples=[60],
    )
    settings_extruder_temp_min: int | None = Field(
        None,
        ge=0,
        description="Low end of the recommended extruder temperature range, in °C.",
        examples=[205],
    )
    settings_extruder_temp_max: int | None = Field(
        None,
        ge=0,
        description="High end of the recommended extruder temperature range, in °C.",
        examples=[225],
    )
    settings_bed_temp_min: int | None = Field(
        None,
        ge=0,
        description="Low end of the recommended bed temperature range, in °C.",
        examples=[50],
    )
    settings_bed_temp_max: int | None = Field(
        None,
        ge=0,
        description="High end of the recommended bed temperature range, in °C.",
        examples=[60],
    )
    spool_type: SpoolType | None = Field(
        None,
        description="The type of spool this filament ships on.",
        examples=["plastic"],
    )
    finish: Finish | None = Field(
        None,
        description="The surface finish of the filament.",
        examples=["matte"],
    )
    pattern: Pattern | None = Field(
        None,
        description="The visual pattern of the filament.",
        examples=["marble"],
    )
    translucent: bool | None = Field(
        None,
        description="Whether the filament is translucent.",
        examples=[False],
    )
    glow: bool | None = Field(
        None,
        description="Whether the filament glows in the dark.",
        examples=[False],
    )
    color_hex: str | None = Field(
        None,
        description=(
            "Hexadecimal color code of the filament, e.g. FF0000 for red. Supports alpha channel at the end. "
            "If it's a multi-color filament, the multi_color_hexes field is used instead."
        ),
        examples=["FF0000"],
    )
    multi_color_hexes: str | None = Field(
        None,
        description=(
            "Hexadecimal color code of the filament, e.g. FF0000 for red. Supports alpha channel at the end. "
            "Specifying multiple colors separated by commas. "
            "Also set the multi_color_direction field if you specify multiple colors."
        ),
        examples=["FF0000,00FF00,0000FF"],
    )
    multi_color_direction: MultiColorDirection | None = Field(
        None,
        description=("Type of multi-color filament. Only set if the color_hex field contains multiple colors. "),
        examples=["coaxial", "longitudinal"],
    )
    external_id: str | None = Field(
        None,
        max_length=256,
        description=(
            "Set if this filament comes from an external database. This contains the ID in the external database."
        ),
        examples=["polymaker_pla_polysonicblack_1000_175"],
    )
    low_stock_threshold: float | None = Field(
        None,
        ge=0,
        description=(
            "Optional low-stock alert threshold, in grams. When the total remaining weight across all "
            "non-archived spools of this filament drops below this value, the filament is flagged as low stock."
        ),
        examples=[500],
    )
    reserve_count: int | None = Field(
        None,
        ge=0,
        description=(
            "Number of unopened spare spools of this filament kept in reserve, tracked without needing a "
            "separate Spool row for each unit."
        ),
        examples=[2],
    )
    extra: dict[str, str] | None = Field(
        None,
        description="Extra fields for this filament.",
    )

    @field_validator("color_hex")
    @classmethod
    def color_hex_validator(cls, v: str | None) -> str | None:
        """Validate the color_hex field."""
        if not v:
            return None

        clr = v.upper()
        clr = clr.removeprefix("#")

        for c in clr:
            if c not in "0123456789ABCDEF":
                raise ValueError("Invalid character in color code.")

        if len(clr) not in (6, 8):
            raise ValueError("Color code must be 6 or 8 characters long.")

        # Return the normalized value (uppercased, '#' stripped) rather than the raw input:
        # a value like '#FF000000' passes the length check above but, returned verbatim, is a
        # 9-character string that SQLite stores unchecked into the String(8) column and then
        # 500s every read of the row (its output model caps color_hex at 8). See issue #45.
        return clr

    @field_validator("multi_color_hexes")
    @classmethod
    def multi_color_hexes_validator(cls, v: str | None) -> str | None:
        """Validate the multi_color_hexes field."""
        if not v:
            return None
        normalized: list[str] = []
        for clr_raw in v.split(","):
            clr = clr_raw.upper()
            clr = clr.removeprefix("#")

            for c in clr:
                if c not in "0123456789ABCDEF":
                    raise ValueError("Invalid character in color code.")

            if len(clr) not in (6, 8):
                raise ValueError("Color code must be 6 or 8 characters long.")

            normalized.append(clr)

        # Return the normalized, '#'-stripped colors (see color_hex_validator above).
        return ",".join(normalized)

    @model_validator(mode="after")  # type: ignore[]
    def validate(self) -> "FilamentParameters":
        """Validate the model."""
        if self.color_hex and self.multi_color_hexes:
            raise ValueError("Cannot specify both color_hex and multi_color_hexes.")
        if self.multi_color_hexes and len(self.multi_color_hexes.split(",")) < 2:  # noqa: PLR2004
            raise ValueError("Must specify at least two colors in multi_color_hexes.")
        if self.multi_color_hexes and not self.multi_color_direction:
            raise ValueError("Multi-color filament must have multi_color_direction set.")
        if not self.multi_color_hexes and self.multi_color_direction:
            raise ValueError("Single-color filament must not have multi_color_direction set.")

        return self


class FilamentUpdateParameters(FilamentParameters):
    density: float | None = Field(None, gt=0, description="The density of this filament in g/cm3.", examples=[1.24])
    diameter: float | None = Field(None, gt=0, description="The diameter of this filament in mm.", examples=[1.75])
    label_printed_at: datetime | None = Field(
        None,
        description=(
            "When a label was last printed for this filament type. Set by the label-printing flow; "
            "pass null to clear the printed marker."
        ),
    )

    @field_validator("density", "diameter")
    @classmethod
    def prevent_none(cls: type["FilamentUpdateParameters"], v: float | None) -> float | None:
        """Prevent density and diameter from being None."""
        if v is None:
            raise ValueError("Value must not be None.")
        return v


@router.get(
    "",
    name="Find filaments",
    description=(
        "Get a list of filaments that matches the search query. "
        "A websocket is served on the same path to listen for updates to any filament, or added or deleted filaments. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={
        200: {"model": list[Filament]},
        299: {"model": FilamentEvent, "description": "Websocket message"},
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
                "Partial case-insensitive search term applied across filament ID, vendor name, name, material, and "
                "article number. Separate multiple terms with a comma. Surround a term with quotes to search for "
                "the exact term."
            ),
        ),
    ] = None,
    vendor_name_old: Annotated[
        str | None,
        Query(alias="vendor_name", title="Vendor Name", description="See vendor.name.", deprecated=True),
    ] = None,
    vendor_id_old: Annotated[
        str | None,
        Query(
            alias="vendor_id",
            title="Vendor ID",
            description="See vendor.id.",
            deprecated=True,
            pattern=r"^-?\d+(,-?\d+)*$",
        ),
    ] = None,
    vendor_name: Annotated[
        str | None,
        Query(
            alias="vendor.name",
            title="Vendor Name",
            description=(
                "Partial case-insensitive search term for the filament vendor name. "
                "Separate multiple terms with a comma. Specify an empty string to match filaments with no vendor name. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    vendor_id: Annotated[
        str | None,
        Query(
            alias="vendor.id",
            title="Vendor ID",
            description=(
                "Match an exact vendor ID. Separate multiple IDs with a comma. "
                "Specify -1 to match filaments with no vendor."
            ),
            pattern=r"^-?\d+(,-?\d+)*$",
            examples=["1", "1,2"],
        ),
    ] = None,
    name: Annotated[
        str | None,
        Query(
            title="Filament Name",
            description=(
                "Partial case-insensitive search term for the filament name. Separate multiple terms with a comma. "
                "Specify an empty string to match filaments with no name. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    material: Annotated[
        str | None,
        Query(
            title="Filament Material",
            description=(
                "Partial case-insensitive search term for the filament material. Separate multiple terms with a comma. "
                "Specify an empty string to match filaments with no material. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    article_number: Annotated[
        str | None,
        Query(
            title="Filament Article Number",
            description=(
                "Partial case-insensitive search term for the filament article number. "
                "Separate multiple terms with a comma. "
                "Specify an empty string to match filaments with no article number. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    color_hex: Annotated[
        str | None,
        Query(
            title="Filament Color",
            description="Match filament by similar color. Slow operation!",
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
    external_id: Annotated[
        str | None,
        Query(
            description=(
                "Find filaments imported by the given external ID. "
                "Separate multiple IDs with a comma. "
                "Specify empty string to match filaments with no external ID. "
                "Surround a term with quotes to search for the exact term."
            ),
            examples=["polymaker_pla_polysonicblack_1000_175"],
        ),
    ] = None,
    sort: Annotated[
        str | None,
        Query(
            title="Sort",
            description=(
                'Sort the results by the given field. Should be a comma-separate string with "field:direction" items.'
            ),
            examples=["vendor.name:asc,spool_weight:desc"],
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(title="Limit", description="Maximum number of items in the response."),
    ] = None,
    offset: Annotated[int, Query(title="Offset", description="Offset in the full result set if a limit is set.")] = 0,
) -> JSONResponse:
    vendor_id = vendor_id if vendor_id is not None else vendor_id_old
    if vendor_id is not None:
        vendor_ids = [int(vendor_id_item) for vendor_id_item in vendor_id.split(",")]
    else:
        vendor_ids = None

    if color_hex is not None:
        matched_filaments = await filament.find_by_color(
            db=db,
            color_query_hex=color_hex,
            similarity_threshold=color_similarity_threshold,
        )
        filter_by_ids = [db_filament.id for db_filament in matched_filaments]
    else:
        filter_by_ids = None

    # Extract custom field filters from query parameters
    extra_field_filters = {}
    query_params = request.query_params
    for key, value in query_params.items():
        if key.startswith(EXTRA_FIELD_PREFIX):
            field_key = key[len(EXTRA_FIELD_PREFIX) :]  # Remove "extra." prefix
            extra_field_filters[field_key] = value

    try:
        sort_by = parse_sort(sort)
        db_items, total_count = await filament.find(
            db=db,
            ids=filter_by_ids,
            search=search,
            vendor_name=vendor_name if vendor_name is not None else vendor_name_old,
            vendor_id=vendor_ids,
            name=name,
            material=material,
            article_number=article_number,
            external_id=external_id,
            extra_field_filters=extra_field_filters if extra_field_filters else None,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    # Populate the per-filament spool_count / remaining_weight aggregates (issues #49 / #53) for the
    # returned page in a single grouped query, then attach them to each response object.
    aggregates = await filament.get_aggregates(db, [db_item.id for db_item in db_items])
    on_order_map = await filament.get_on_order(db, [db_item.id for db_item in db_items])
    filaments_out = [
        Filament.from_db(
            db_item,
            spool_count=aggregates.get(db_item.id, (None, None))[0],
            remaining_weight=aggregates.get(db_item.id, (None, None))[1],
            on_order=on_order_map.get(db_item.id),
        )
        for db_item in db_items
    ]

    # Set x-total-count header for pagination
    return JSONResponse(
        content=jsonable_encoder(filaments_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket(
    "",
    name="Listen to filament changes",
)
async def notify_any(
    websocket: WebSocket,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("filament",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("filament",), websocket)


@router.get(
    "/{filament_id}",
    name="Get filament",
    description=(
        "Get a specific filament. A websocket is served on the same path to listen for changes to the filament. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": FilamentEvent, "description": "Websocket message"}},
)
async def get(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filament_id: int,
) -> Filament:
    db_item = await filament.get_by_id(db, filament_id)
    spool_count, remaining_weight = (await filament.get_aggregates(db, [filament_id])).get(filament_id, (0, 0.0))
    on_order = (await filament.get_on_order(db, [filament_id])).get(filament_id)
    return Filament.from_db(db_item, spool_count=spool_count, remaining_weight=remaining_weight, on_order=on_order)


@router.websocket(
    "/{filament_id}",
    name="Listen to filament changes",
)
async def notify(
    websocket: WebSocket,
    filament_id: int,
) -> None:
    await websocket.accept()
    websocket_manager.connect(("filament", str(filament_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("filament", str(filament_id)), websocket)


@router.post(
    "",
    name="Add filament",
    description="Add a new filament to the database.",
    response_model_exclude_none=True,
    response_model=Filament,
    responses={400: {"model": Message}},
)
async def create(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: FilamentParameters,
):
    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.filament) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    db_item = await filament.create(
        db=db,
        density=body.density,
        diameter=body.diameter,
        name=body.name,
        vendor_id=body.vendor_id,
        material=body.material,
        price=body.price,
        weight=body.weight,
        spool_weight=body.spool_weight,
        article_number=body.article_number,
        comment=body.comment,
        settings_extruder_temp=body.settings_extruder_temp,
        settings_bed_temp=body.settings_bed_temp,
        settings_extruder_temp_min=body.settings_extruder_temp_min,
        settings_extruder_temp_max=body.settings_extruder_temp_max,
        settings_bed_temp_min=body.settings_bed_temp_min,
        settings_bed_temp_max=body.settings_bed_temp_max,
        spool_type=body.spool_type,
        finish=body.finish,
        pattern=body.pattern,
        translucent=body.translucent,
        glow=body.glow,
        color_hex=body.color_hex,
        multi_color_hexes=body.multi_color_hexes,
        multi_color_direction=body.multi_color_direction,
        external_id=body.external_id,
        low_stock_threshold=body.low_stock_threshold,
        reserve_count=body.reserve_count,
        extra=body.extra,
    )

    # The stock aggregates are a read-time view; POST returns the stored resource unchanged so the
    # create response shape stays identical to before this feature (integrations POSTing are unaffected).
    return Filament.from_db(db_item)


@router.patch(
    "/{filament_id}",
    name="Update filament",
    description=(
        "Update any attribute of a filament. Only fields specified in the request will be affected. "
        "If extra is set, all existing extra fields will be removed and replaced with the new ones."
    ),
    response_model_exclude_none=True,
    response_model=Filament,
    responses={
        400: {"model": Message},
        404: {"model": Message},
    },
)
async def update(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filament_id: int,
    body: FilamentUpdateParameters,
):
    patch_data = body.model_dump(exclude_unset=True)

    # Fetch extra field definitions once at endpoint entry
    all_fields = await get_extra_fields(db, EntityType.filament) if body.extra else None
    if body.extra and all_fields:
        try:
            validate_extra_field_dict(all_fields, body.extra)
        except ValueError as e:
            return JSONResponse(status_code=400, content=Message(message=str(e)).dict())

    db_item = await filament.update(
        db=db,
        filament_id=filament_id,
        data=patch_data,
    )

    return Filament.from_db(db_item)


@router.delete(
    "/{filament_id}",
    name="Delete filament",
    description="Delete a filament.",
    response_model=Message,
    responses={
        403: {"model": Message},
        404: {"model": Message},
    },
)
async def delete(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filament_id: int,
):
    try:
        await filament.delete(db, filament_id)
    except ItemDeleteError:
        logger.exception("Failed to delete filament.")
        return JSONResponse(
            status_code=403,
            content={"message": "Failed to delete filament, see server logs for more information."},
        )
    return Message(message="Success!")


# Reference photos (#88). Raw request/response bodies on purpose: no multipart dependency and no
# server-side image processing (Pillow ships no 32-bit ARM wheels) — the client downscales before
# uploading, and the server only enforces the type allowlist and the size cap.
IMAGE_MAX_BYTES = 2 * 1024 * 1024
IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


@router.get(
    "/{filament_id}/image",
    name="Get filament image",
    description=(
        "Get the reference photo of a filament as a raw image body. "
        "Supports conditional requests via ETag / If-None-Match."
    ),
    response_class=Response,
    responses={
        200: {"content": {"image/*": {}}, "description": "The image bytes."},
        304: {"description": "Not modified."},
        404: {"model": Message},
    },
)
async def get_image(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filament_id: int,
) -> Response:
    db_image = await filament.get_image(db, filament_id)
    # private: photos must not land in shared proxy caches on auth-enabled instances; no-cache: the
    # browser revalidates with If-None-Match on every use, so a replaced photo shows up without a
    # reload while unchanged ones cost only a 304.
    headers = {"ETag": f'"{db_image.etag}"', "Cache-Control": "private, no-cache"}
    if_none_match = request.headers.get("if-none-match") or ""
    if if_none_match.strip() == "*" or db_image.etag in if_none_match:
        return Response(status_code=304, headers=headers)
    return Response(content=db_image.data, media_type=db_image.content_type, headers=headers)


@router.put(
    "/{filament_id}/image",
    name="Set filament image",
    description=(
        "Attach a reference photo to a filament, replacing any existing one. Send the raw image bytes "
        "as the request body with a matching Content-Type header (image/jpeg, image/png or image/webp). "
        f"Bodies over {IMAGE_MAX_BYTES // (1024 * 1024)} MB are rejected — downscale before uploading. "
        "Returns the updated filament."
    ),
    response_model_exclude_none=True,
    response_model=Filament,
    responses={
        400: {"model": Message},
        404: {"model": Message},
        413: {"model": Message},
        415: {"model": Message},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {ct: {"schema": {"type": "string", "format": "binary"}} for ct in sorted(IMAGE_CONTENT_TYPES)},
        },
    },
)
async def set_image(  # noqa: ANN201
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filament_id: int,
):
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in IMAGE_CONTENT_TYPES:
        allowed = ", ".join(sorted(IMAGE_CONTENT_TYPES))
        return JSONResponse(
            status_code=415,
            content=Message(message=f"Unsupported image type '{content_type}'; use one of: {allowed}.").dict(),
        )
    too_large = JSONResponse(
        status_code=413,
        content=Message(message=f"Image is larger than the {IMAGE_MAX_BYTES // (1024 * 1024)} MB limit.").dict(),
    )
    # Reject by the declared length first so an oversized upload fails without buffering the body...
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit() and int(content_length) > IMAGE_MAX_BYTES:
        return too_large
    body = await request.body()
    # ...and re-check the real length, since the header is client-supplied.
    if len(body) > IMAGE_MAX_BYTES:
        return too_large
    if len(body) == 0:
        return JSONResponse(status_code=400, content=Message(message="Request body is empty.").dict())
    db_item = await filament.set_image(db, filament_id, data=body, content_type=content_type)
    return Filament.from_db(db_item)


@router.delete(
    "/{filament_id}/image",
    name="Delete filament image",
    description="Remove the reference photo of a filament.",
    status_code=204,
    responses={404: {"model": Message}},
)
async def delete_image(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filament_id: int,
) -> Response:
    await filament.delete_image(db, filament_id)
    return Response(status_code=204)
