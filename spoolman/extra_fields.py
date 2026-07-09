"""Custom/extra fields for spoolman entities."""

import json
import logging

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import filament as db_filament
from spoolman.database import location as db_location
from spoolman.database import setting as db_setting
from spoolman.database import spool as db_spool
from spoolman.database import vendor as db_vendor
from spoolman.exceptions import ItemNotFoundError
from spoolman.extra_field_registry import (
    EXTRA_FIELD_PREFIX,
    EntityType,
    ExtraField,
    ExtraFieldParameters,
    ExtraFieldType,
    add_or_update_extra_field,
    extra_field_cache,
    get_extra_fields,
    validate_extra_field,
    validate_extra_field_dict,
    validate_extra_field_value,
)
from spoolman.settings import parse_setting

logger = logging.getLogger(__name__)

__all__ = [
    "EXTRA_FIELD_PREFIX",
    "EntityType",
    "ExtraField",
    "ExtraFieldParameters",
    "ExtraFieldType",
    "add_or_update_extra_field",
    "delete_extra_field",
    "extra_field_cache",
    "get_extra_fields",
    "inherit_filament_extra_fields",
    "populate_with_defaults",
    "validate_extra_field",
    "validate_extra_field_dict",
    "validate_extra_field_value",
]


async def delete_extra_field(db: AsyncSession, entity_type: EntityType, key: str) -> None:
    """Delete an extra field for a specific entity type."""
    extra_fields = await get_extra_fields(db, entity_type)

    # Check if the field exists
    if not any(field.key == key for field in extra_fields):
        raise ItemNotFoundError(f"Extra field with key {key} does not exist.")

    extra_fields = [field for field in extra_fields if field.key != key]

    setting_def = parse_setting(f"extra_fields_{entity_type.name}")
    await db_setting.update(db=db, definition=setting_def, value=json.dumps(jsonable_encoder(extra_fields)))

    # Update cache
    extra_field_cache[entity_type] = extra_fields

    logger.info("Deleted extra field %r for entity type %r.", key, entity_type.name)

    if entity_type == EntityType.vendor:
        await db_vendor.clear_extra_field(db, key)
    elif entity_type == EntityType.filament:
        await db_filament.clear_extra_field(db, key)
    elif entity_type == EntityType.spool:
        await db_spool.clear_extra_field(db, key)
    elif entity_type == EntityType.location:
        await db_location.clear_extra_field(db, key)
    else:
        raise ValueError(f"Unknown entity type {entity_type.name}.")


async def populate_with_defaults(db: AsyncSession, entity_type: EntityType, existing: dict[str, str]) -> None:
    """Populate the given list of extra fields with defaults."""
    extra_fields = await get_extra_fields(db, entity_type)
    for extra_field in extra_fields:
        if extra_field.default_value is None:
            continue
        if extra_field.key in existing:
            continue
        existing[extra_field.key] = extra_field.default_value


async def inherit_filament_extra_fields(
    db: AsyncSession,
    *,
    filament_id: int,
    extra: dict[str, str] | None,
) -> dict[str, str] | None:
    """Copy linked filament extra fields onto a new spool at creation time (#118).

    For each spool extra field marked ``copy_from_filament``, if the spool doesn't already provide a
    value and the parent filament has one for the same key, inherit the filament's value. The input
    dict is not mutated; returns the (possibly augmented) extra dict, or None if it stays empty.

    The common path (no linked fields) does a single cached field-list lookup and returns unchanged,
    so spool creation from Moonraker/OctoPrint keeps its current cost.
    """
    spool_fields = await get_extra_fields(db, EntityType.spool)
    linked = [field for field in spool_fields if field.copy_from_filament]
    if not linked:
        return extra

    try:
        filament_obj = await db_filament.get_by_id(db, filament_id)
    except ItemNotFoundError:
        return extra

    filament_extra = {field.key: field.value for field in filament_obj.extra}
    result = dict(extra or {})
    for field in linked:
        if field.key in result or field.key not in filament_extra:
            continue
        value = filament_extra[field.key]
        try:
            validate_extra_field_value(field, value)
        except ValueError:
            logger.warning(
                "Not inheriting filament field %r onto the new spool: value invalid for the spool field type.",
                field.key,
            )
            continue
        result[field.key] = value
    return result or None
