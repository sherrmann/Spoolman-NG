"""Pydantic data models for typing the FastAPI request/responses."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

from spoolman.database import models
from spoolman.math import length_from_weight
from spoolman.settings import SettingDefinition, SettingType


def datetime_to_str(dt: datetime) -> str:
    """Convert a datetime object to a string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


SpoolmanDateTime = Annotated[datetime, PlainSerializer(datetime_to_str)]


def _normalize_stored_color_hex(value: str | None) -> str | None:
    """Defensively normalize a stored color_hex when serializing out of the DB.

    The write-side validators keep new values clean, but a row poisoned by an older
    build (a value stored with a leading '#', e.g. '#FF000000') would otherwise fail
    the output model's max_length=8 and 500 every read of the list — including the
    websocket broadcast (see issue #45). Strip '#'/whitespace and uppercase; if the
    result still is not a valid 6/8-char hex, drop the colour (render colourless)
    rather than break the whole response.
    """
    if not value:
        return None
    clr = value.strip().upper().removeprefix("#")
    if len(clr) not in (6, 8) or any(c not in "0123456789ABCDEF" for c in clr):
        return None
    return clr


def _normalize_stored_multi_color_hexes(value: str | None) -> str | None:
    """Defensively normalize a stored multi_color_hexes value (see _normalize_stored_color_hex)."""
    if not value:
        return None
    normalized = [clr for part in value.split(",") if (clr := _normalize_stored_color_hex(part)) is not None]
    return ",".join(normalized) if normalized else None


class Message(BaseModel):
    message: str = Field()


class SettingResponse(BaseModel):
    value: str = Field(description="Setting value.")
    is_set: bool = Field(description="Whether the setting has been set. If false, 'value' contains the default value.")
    type: SettingType = Field(description="Setting type. This corresponds with JSON types.")


class SettingKV(BaseModel):
    key: str = Field(description="Setting key.")
    setting: SettingResponse = Field(description="Setting value.")

    @staticmethod
    def from_db(definition: SettingDefinition, set_value: str | None) -> "SettingKV":
        """Create a new Pydantic vendor object from a database vendor object."""
        return SettingKV(
            key=definition.key,
            setting=SettingResponse(
                value=set_value if set_value is not None else definition.default,
                is_set=set_value is not None,
                type=definition.type,
            ),
        )


class Vendor(BaseModel):
    id: int = Field(description="Unique internal ID of this vendor.")
    registered: SpoolmanDateTime = Field(description="When the vendor was registered in the database. UTC Timezone.")
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
        description="The empty spool weight, in grams.",
        examples=[140],
    )
    external_id: str | None = Field(
        None,
        max_length=256,
        description=(
            "Set if this vendor comes from an external database. This contains the ID in the external database."
        ),
        examples=["eSun"],
    )
    filament_count: int | None = Field(
        None,
        description=(
            "Aggregate: number of filament types from this vendor. "
            "Only populated on the vendor list and detail endpoints; null in nested/websocket payloads."
        ),
        examples=[4],
    )
    spool_count: int | None = Field(
        None,
        description=(
            "Aggregate: number of non-archived spools across this vendor's filaments. "
            "Only populated on the vendor list and detail endpoints; null in nested/websocket payloads."
        ),
        examples=[9],
    )
    extra: dict[str, str] = Field(
        description=(
            "Extra fields for this vendor. All values are JSON-encoded data. "
            "Query the /fields endpoint for more details about the fields."
        ),
    )

    @staticmethod
    def from_db(
        item: models.Vendor,
        *,
        filament_count: int | None = None,
        spool_count: int | None = None,
    ) -> "Vendor":
        """Create a new Pydantic vendor object from a database vendor object.

        The optional filament_count/spool_count aggregates are supplied by the vendor list and detail
        endpoints; they are left null in nested (filament.vendor) and websocket payloads.
        """
        return Vendor(
            id=item.id,
            registered=item.registered,
            name=item.name,
            comment=item.comment,
            empty_spool_weight=item.empty_spool_weight,
            external_id=item.external_id,
            filament_count=filament_count,
            spool_count=spool_count,
            extra={field.key: field.value for field in item.extra},
        )


class Location(BaseModel):
    id: int = Field(description="Unique internal ID of this location.")
    registered: SpoolmanDateTime = Field(description="When the location was registered in the database. UTC Timezone.")
    name: str = Field(max_length=64, description="Location name.", examples=["Dry Box 1"])
    comment: str | None = Field(
        None,
        max_length=1024,
        description="Free text comment about this location.",
        examples=[""],
    )
    spool_count: int | None = Field(
        None,
        description=(
            "Aggregate: number of non-archived spools currently stored at this location (matched by "
            "name against Spool.location). Only populated on the location list and detail endpoints; "
            "null in websocket payloads."
        ),
        examples=[3],
    )
    extra: dict[str, str] = Field(
        description=(
            "Extra fields for this location. All values are JSON-encoded data. "
            "Query the /fields endpoint for more details about the fields."
        ),
    )

    @staticmethod
    def from_db(item: models.Location, *, spool_count: int | None = None) -> "Location":
        """Create a Pydantic location object from a database location object.

        The optional spool_count aggregate is supplied by the location list and detail endpoints; it
        is left null in websocket payloads.
        """
        return Location(
            id=item.id,
            registered=item.registered,
            name=item.name,
            comment=item.comment,
            spool_count=spool_count,
            extra={field.key: field.value for field in item.extra},
        )


class MultiColorDirection(Enum):
    """Enum for multi-color direction."""

    COAXIAL = "coaxial"
    LONGITUDINAL = "longitudinal"


class Filament(BaseModel):
    id: int = Field(description="Unique internal ID of this filament type.")
    registered: SpoolmanDateTime = Field(description="When the filament was registered in the database. UTC Timezone.")
    name: str | None = Field(
        None,
        max_length=64,
        description=(
            "Filament name, to distinguish this filament type among others from the same vendor."
            "Should contain its color for example."
        ),
        examples=["PolyTerra™ Charcoal Black"],
    )
    vendor: Vendor | None = Field(None, description="The vendor of this filament type.")
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
        description="The weight of the filament in a full spool, in grams.",
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
    color_hex: str | None = Field(
        None,
        min_length=6,
        max_length=8,
        description=(
            "Hexadecimal color code of the filament, e.g. FF0000 for red. Supports alpha channel at the end. "
            "If it's a multi-color filament, the multi_color_hexes field is used instead."
        ),
        examples=["FF0000"],
    )
    multi_color_hexes: str | None = Field(
        None,
        min_length=6,
        description=(
            "Hexadecimal color code of the filament, e.g. FF0000 for red. Supports alpha channel at the end. "
            "Specifying multiple colors separated by commas. "
            "Also set the multi_color_direction field if you specify multiple colors."
        ),
        examples=["FF0000,00FF00,0000FF"],
    )
    multi_color_direction: MultiColorDirection | None = Field(
        None,
        description=("Type of multi-color filament. Only set if the multi_color_hexes field is set."),
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
    label_printed_at: SpoolmanDateTime | None = Field(
        None,
        description="When a label was last printed for this filament type. Null means never printed. UTC Timezone.",
    )
    spool_count: int | None = Field(
        None,
        description=(
            "Aggregate: number of non-archived spools of this filament type. "
            "Only populated on the filament list and detail endpoints; null in nested/websocket payloads."
        ),
        examples=[3],
    )
    remaining_weight: float | None = Field(
        None,
        description=(
            "Aggregate: total estimated remaining weight, in grams, across all non-archived spools of this "
            "filament type. Only populated on the filament list and detail endpoints; null in nested/websocket "
            "payloads."
        ),
        examples=[2500.0],
    )
    extra: dict[str, str] = Field(
        description=(
            "Extra fields for this filament. All values are JSON-encoded data. "
            "Query the /fields endpoint for more details about the fields."
        ),
    )

    @staticmethod
    def from_db(
        item: models.Filament,
        *,
        spool_count: int | None = None,
        remaining_weight: float | None = None,
    ) -> "Filament":
        """Create a new Pydantic filament object from a database filament object.

        The optional spool_count/remaining_weight aggregates are passed in by the list and detail
        endpoints; they are left null everywhere else (nested spool.filament, websocket events) so
        the read path stays free of an N+1 aggregate query.
        """
        return Filament(
            id=item.id,
            registered=item.registered,
            name=item.name,
            vendor=Vendor.from_db(item.vendor) if item.vendor is not None else None,
            material=item.material,
            price=item.price,
            density=item.density,
            diameter=item.diameter,
            weight=item.weight,
            spool_weight=item.spool_weight,
            article_number=item.article_number,
            comment=item.comment,
            settings_extruder_temp=item.settings_extruder_temp,
            settings_bed_temp=item.settings_bed_temp,
            color_hex=_normalize_stored_color_hex(item.color_hex),
            multi_color_hexes=_normalize_stored_multi_color_hexes(item.multi_color_hexes),
            multi_color_direction=(
                MultiColorDirection(item.multi_color_direction) if item.multi_color_direction is not None else None
            ),
            external_id=item.external_id,
            low_stock_threshold=item.low_stock_threshold,
            reserve_count=item.reserve_count,
            label_printed_at=item.label_printed_at,
            spool_count=spool_count,
            remaining_weight=remaining_weight,
            extra={field.key: field.value for field in item.extra},
        )


class Spool(BaseModel):
    id: int = Field(description="Unique internal ID of this spool of filament.")
    registered: SpoolmanDateTime = Field(description="When the spool was registered in the database. UTC Timezone.")
    first_used: SpoolmanDateTime | None = Field(
        None,
        description="First logged occurence of spool usage. UTC Timezone.",
    )
    last_used: SpoolmanDateTime | None = Field(
        None,
        description="Last logged occurence of spool usage. UTC Timezone.",
    )
    filament: Filament = Field(description="The filament type of this spool.")
    price: float | None = Field(
        None,
        ge=0,
        description="The price of this spool in the system configured currency.",
        examples=[20.0],
    )
    remaining_weight: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Estimated remaining weight of filament on the spool in grams. "
            "Only set if the filament type has a weight set."
        ),
        examples=[500.6],
    )
    initial_weight: float | None = Field(
        default=None,
        ge=0,
        description=("The initial weight, in grams, of the filament on the spool (net weight)."),
        examples=[1246],
    )
    spool_weight: float | None = Field(
        default=None,
        ge=0,
        description=("Weight of an empty spool (tare weight)."),
        examples=[246],
    )
    used_weight: float = Field(
        ge=0,
        description="Consumed weight of filament from the spool in grams.",
        examples=[500.3],
    )
    remaining_length: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Estimated remaining length of filament on the spool in millimeters."
            " Only set if the filament type has a weight set."
        ),
        examples=[5612.4],
    )
    used_length: float = Field(
        ge=0,
        description="Consumed length of filament from the spool in millimeters.",
        examples=[50.7],
    )
    diameter: float | None = Field(
        None,
        gt=0,
        description=(
            "Measured per-spool filament diameter in mm, overriding the filament's nominal diameter in "
            "length calculations (#101). Null means the filament's diameter is used. This is the raw "
            "override value, not the effective diameter."
        ),
        examples=[1.73],
    )
    location: str | None = Field(
        None,
        max_length=64,
        description="Where this spool can be found.",
        examples=["Shelf A"],
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
    archived: bool = Field(description="Whether this spool is archived and should not be used anymore.")
    label_printed_at: SpoolmanDateTime | None = Field(
        None,
        description="When a label was last printed for this spool. Null means never printed. UTC Timezone.",
    )
    extra: dict[str, str] = Field(
        description=(
            "Extra fields for this spool. All values are JSON-encoded data. "
            "Query the /fields endpoint for more details about the fields."
        ),
    )

    @staticmethod
    def from_db(item: models.Spool) -> "Spool":
        """Create a new Pydantic spool object from a database spool object."""
        filament = Filament.from_db(item.filament)

        # #101: length math uses the per-spool diameter override when set, else the filament's. The
        # raw override (item.diameter, possibly null) is emitted separately so the value round-trips.
        effective_diameter = item.diameter if item.diameter is not None else filament.diameter

        remaining_weight: float | None = None
        remaining_length: float | None = None

        if item.initial_weight is not None:
            remaining_weight = max(item.initial_weight - item.used_weight, 0)
            remaining_length = length_from_weight(
                weight=remaining_weight,
                density=filament.density,
                diameter=effective_diameter,
            )
        elif filament.weight is not None:
            remaining_weight = max(filament.weight - item.used_weight, 0)
            remaining_length = length_from_weight(
                weight=remaining_weight,
                density=filament.density,
                diameter=effective_diameter,
            )

        used_length = length_from_weight(
            weight=item.used_weight,
            density=filament.density,
            diameter=effective_diameter,
        )

        return Spool(
            id=item.id,
            registered=item.registered,
            first_used=item.first_used,
            last_used=item.last_used,
            filament=filament,
            price=item.price,
            initial_weight=item.initial_weight,
            spool_weight=item.spool_weight,
            used_weight=item.used_weight,
            used_length=used_length,
            diameter=item.diameter,
            remaining_weight=remaining_weight,
            remaining_length=remaining_length,
            location=item.location,
            lot_nr=item.lot_nr,
            comment=item.comment,
            archived=item.archived if item.archived is not None else False,
            label_printed_at=item.label_printed_at,
            extra={field.key: field.value for field in item.extra},
        )


class SpoolUsageEvent(BaseModel):
    id: int = Field(description="Unique internal ID of this usage event.")
    spool_id: int = Field(description="The spool this event belongs to.")
    time: SpoolmanDateTime = Field(description="When the event was recorded. UTC Timezone.")
    event_type: str = Field(description="One of: use, measure, update.", examples=["use"])
    delta: float = Field(
        description="Change applied to used_weight in grams (sign: consumed positive, refilled negative).",
        examples=[5.3],
    )
    measured_weight: float | None = Field(
        None,
        description="Raw gross weight for measure events, in grams.",
        examples=[850.0],
    )
    comment: str | None = Field(None, description="Optional comment recorded with the event.")

    @staticmethod
    def from_db(item: models.SpoolUsageEvent) -> "SpoolUsageEvent":
        """Create a Pydantic usage-event object from a database object."""
        return SpoolUsageEvent(
            id=item.id,
            spool_id=item.spool_id,
            time=item.time,
            event_type=item.event_type,
            delta=item.delta,
            measured_weight=item.measured_weight,
            comment=item.comment,
        )


class Info(BaseModel):
    version: str = Field(examples=["0.7.0"])
    debug_mode: bool = Field(examples=[False])
    automatic_backups: bool = Field(examples=[True])
    data_dir: str = Field(examples=["/home/app/.local/share/spoolman"])
    logs_dir: str = Field(examples=["/home/app/.local/share/spoolman"])
    backups_dir: str = Field(examples=["/home/app/.local/share/spoolman/backups"])
    db_type: str = Field(examples=["sqlite"])
    git_commit: str | None = Field(None, examples=["a1b2c3d"])
    build_date: SpoolmanDateTime | None = Field(None, examples=["2021-01-01T00:00:00Z"])


class HealthCheck(BaseModel):
    status: str = Field(examples=["healthy"])


class BackupResponse(BaseModel):
    path: str = Field(
        default=None,
        description="Path to the created backup file.",
        examples=["/home/app/.local/share/spoolman/backups/spoolman.db"],
    )


class EventType(str, Enum):
    """Event types."""

    ADDED = "added"
    UPDATED = "updated"
    DELETED = "deleted"


class Event(BaseModel):
    """Event."""

    type: EventType = Field(description="Event type.")
    resource: str = Field(description="Resource type.")
    date: SpoolmanDateTime = Field(description="When the event occured. UTC Timezone.")
    payload: BaseModel


class SpoolEvent(Event):
    """Event."""

    payload: Spool = Field(description="Updated spool.")
    resource: Literal["spool"] = Field(description="Resource type.")
    payload_extras: dict[str, float] | None = Field(
        default=None, description="Payload extra fields outside of core Spool model"
    )


class FilamentEvent(Event):
    """Event."""

    payload: Filament = Field(description="Updated filament.")
    resource: Literal["filament"] = Field(description="Resource type.")


class VendorEvent(Event):
    """Event."""

    payload: Vendor = Field(description="Updated vendor.")
    resource: Literal["vendor"] = Field(description="Resource type.")


class LocationEvent(Event):
    """Event."""

    payload: Location = Field(description="Updated location.")
    resource: Literal["location"] = Field(description="Resource type.")


class SettingEvent(Event):
    """Event."""

    payload: SettingKV = Field(description="Updated setting.")
    resource: Literal["setting"] = Field(description="Resource type.")
