"""Curated AI tool layer (#360).

One tool surface, two consumers: the built-in MCP server (spoolman/mcp.py) exposes
these to external assistants, and the in-app chat agent (spoolman/aichat.py, #362)
calls the same implementations. Deliberately curated rather than 1:1 CRUD: each tool
is a
task-shaped operation with a compact, model-readable result, and carries a
``read_only`` flag that callers use for role gating — a readonly principal must
never even see the mutating tools.

All handlers reuse the same database helpers as the REST API (``spoolman.database``),
so behavior — usage events, websocket notifications, weight math — is identical to
the web UI performing the same action.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import filament, models, spool
from spoolman.exceptions import ItemCreateError, ItemNotFoundError, SpoolMeasureError
from spoolman.settings import SETTINGS

#: Hard cap for list results — tools feed model context windows, not tables.
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20

ROLE_READONLY = "readonly"


class ToolError(Exception):
    """A user-visible tool failure (bad arguments, missing entity). Safe to show verbatim."""


class ToolNotFoundError(Exception):
    """The tool does not exist for this caller (unknown, or hidden by role gating)."""


@dataclass(frozen=True)
class Tool:
    """A curated tool: metadata for listing plus the executable handler."""

    name: str
    description: str
    input_schema: dict
    read_only: bool
    handler: Callable[[AsyncSession, dict], Awaitable[dict]]


# --- Argument helpers --------------------------------------------------------------


def _check_known_keys(args: dict, schema: dict) -> None:
    known = set(schema.get("properties", {}).keys())
    unknown = sorted(set(args.keys()) - known)
    if unknown:
        raise ToolError(f"Unknown argument(s): {', '.join(unknown)}. Known: {', '.join(sorted(known))}.")


def _opt_str(args: dict, key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"Argument '{key}' must be a string.")
    return value.strip() or None


def _opt_bool(args: dict, key: str, default: bool) -> bool:  # noqa: FBT001
    value = args.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ToolError(f"Argument '{key}' must be a boolean.")
    return value


def _opt_number(args: dict, key: str) -> float | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(f"Argument '{key}' must be a number.")
    return float(value)


def _req_int(args: dict, key: str) -> int:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"Argument '{key}' is required and must be an integer.")
    return value


def _limit(args: dict) -> int:
    value = args.get("limit", _DEFAULT_LIMIT)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("Argument 'limit' must be a positive integer.")
    return min(value, _MAX_LIMIT)


async def _setting_number(db: AsyncSession, key: str) -> float:
    definition = SETTINGS[key]
    row = await db.get(models.Setting, definition.key)
    raw = row.value if row is not None else definition.default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return 0.0
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


# --- Compact serializers -----------------------------------------------------------


def _initial_weight(item: models.Spool) -> float | None:
    if item.initial_weight is not None:
        return item.initial_weight
    return item.filament.weight if item.filament is not None else None


def _remaining_weight(item: models.Spool) -> float | None:
    initial = _initial_weight(item)
    if initial is None:
        return None
    return round(max(initial - item.used_weight, 0), 1)


def spool_brief(item: models.Spool) -> dict:
    """Compact spool representation for model consumption."""
    fil = item.filament
    return {
        "id": item.id,
        "filament_id": item.filament_id,
        "filament": fil.name if fil is not None else None,
        "vendor": fil.vendor.name if fil is not None and fil.vendor is not None else None,
        "material": fil.material if fil is not None else None,
        "color_hex": getattr(fil, "color_hex", None) if fil is not None else None,
        "remaining_weight_g": _remaining_weight(item),
        "used_weight_g": round(item.used_weight, 1),
        "location": item.location,
        "lot_nr": item.lot_nr,
        "price": item.price,
        "archived": bool(item.archived),
        "comment": item.comment,
    }


def _filament_brief(item: models.Filament, aggregate: tuple[int, float] | None) -> dict:
    spool_count, remaining = aggregate if aggregate is not None else (0, 0.0)
    return {
        "id": item.id,
        "name": item.name,
        "vendor": item.vendor.name if item.vendor is not None else None,
        "material": item.material,
        "color_hex": getattr(item, "color_hex", None),
        "diameter_mm": item.diameter,
        "price": item.price,
        "low_stock_threshold_g": item.low_stock_threshold,
        "active_spool_count": spool_count,
        "remaining_weight_g": round(remaining, 1),
    }


# --- Read tools --------------------------------------------------------------------


_FIND_SPOOLS_SCHEMA = {
    "type": "object",
    "properties": {
        "search": {"type": "string", "description": "Free-text search over filament/vendor/material/location/lot."},
        "material": {"type": "string", "description": "Filter by material, e.g. PLA or PETG."},
        "vendor": {"type": "string", "description": "Filter by vendor name."},
        "filament_name": {"type": "string", "description": "Filter by filament name."},
        "location": {"type": "string", "description": "Filter by storage location."},
        "lot_nr": {"type": "string", "description": "Filter by lot number."},
        "include_archived": {"type": "boolean", "description": "Include archived spools. Default false."},
        "limit": {"type": "integer", "description": "Maximum results, default 20, max 100."},
    },
    "additionalProperties": False,
}


async def _find_spools(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _FIND_SPOOLS_SCHEMA)
    items, total = await spool.find(
        db=db,
        search=_opt_str(args, "search"),
        filament_material=_opt_str(args, "material"),
        vendor_name=_opt_str(args, "vendor"),
        filament_name=_opt_str(args, "filament_name"),
        location=_opt_str(args, "location"),
        lot_nr=_opt_str(args, "lot_nr"),
        allow_archived=_opt_bool(args, "include_archived", default=False),
        limit=_limit(args),
    )
    return {"total_matching": total, "returned": len(items), "spools": [spool_brief(item) for item in items]}


_FIND_FILAMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "search": {"type": "string", "description": "Free-text search over name/vendor/material/article number."},
        "material": {"type": "string", "description": "Filter by material, e.g. PLA or PETG."},
        "vendor": {"type": "string", "description": "Filter by vendor name."},
        "name": {"type": "string", "description": "Filter by filament name."},
        "article_number": {"type": "string", "description": "Filter by article number."},
        "limit": {"type": "integer", "description": "Maximum results, default 20, max 100."},
    },
    "additionalProperties": False,
}


async def _find_filaments(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _FIND_FILAMENTS_SCHEMA)
    items, total = await filament.find(
        db=db,
        search=_opt_str(args, "search"),
        material=_opt_str(args, "material"),
        vendor_name=_opt_str(args, "vendor"),
        name=_opt_str(args, "name"),
        article_number=_opt_str(args, "article_number"),
        limit=_limit(args),
    )
    aggregates = await filament.get_aggregates(db, [item.id for item in items])
    return {
        "total_matching": total,
        "returned": len(items),
        "filaments": [_filament_brief(item, aggregates.get(item.id)) for item in items],
    }


_NO_ARGS_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


async def _get_inventory_stats(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _NO_ARGS_SCHEMA)
    rows = (
        await db.execute(
            sqlalchemy.select(
                models.Spool.initial_weight,
                models.Filament.weight,
                models.Spool.used_weight,
                models.Filament.material,
                models.Spool.location,
            )
            .join(models.Filament, models.Spool.filament_id == models.Filament.id)
            .where(sqlalchemy.or_(models.Spool.archived.is_(False), models.Spool.archived.is_(None))),
        )
    ).all()

    total_remaining = 0.0
    materials: dict[str, dict] = {}
    locations: dict[str, dict] = {}
    for initial, filament_weight, used, material, location in rows:
        base = initial if initial is not None else filament_weight
        remaining = max(base - used, 0) if base is not None else 0.0
        total_remaining += remaining
        material_key = material or "unknown"
        material_stats = materials.setdefault(
            material_key,
            {"material": material_key, "spools": 0, "remaining_weight_g": 0.0},
        )
        material_stats["spools"] += 1
        material_stats["remaining_weight_g"] = round(material_stats["remaining_weight_g"] + remaining, 1)
        location_key = location or "unspecified"
        location_stats = locations.setdefault(location_key, {"location": location_key, "spools": 0})
        location_stats["spools"] += 1

    filament_count = (await db.execute(sqlalchemy.select(sqlalchemy.func.count(models.Filament.id)))).scalar() or 0
    vendor_count = (await db.execute(sqlalchemy.select(sqlalchemy.func.count(models.Vendor.id)))).scalar() or 0

    return {
        "active_spools": len(rows),
        "filaments": filament_count,
        "vendors": vendor_count,
        "total_remaining_weight_g": round(total_remaining, 1),
        "by_material": sorted(materials.values(), key=lambda entry: -entry["remaining_weight_g"]),
        "by_location": sorted(locations.values(), key=lambda entry: -entry["spools"]),
    }


async def _get_low_stock(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _NO_ARGS_SCHEMA)
    fallback = await _setting_number(db, "low_stock_fallback_g")
    items, _ = await filament.find(db=db)
    aggregates = await filament.get_aggregates(db, [item.id for item in items])

    flagged = []
    for item in items:
        spool_count, remaining = aggregates.get(item.id, (0, 0.0))
        threshold = item.low_stock_threshold
        if threshold is None:
            threshold = fallback if fallback > 0 else None
            # The fallback only applies to filaments that actually have stock history.
            if spool_count == 0:
                threshold = None
        if threshold is None or remaining > threshold:
            continue
        entry = _filament_brief(item, (spool_count, remaining))
        entry["threshold_g"] = threshold
        flagged.append(entry)

    flagged.sort(key=lambda entry: entry["remaining_weight_g"])
    return {"fallback_threshold_g": fallback, "low_stock_count": len(flagged), "filaments": flagged}


# --- Write tools -------------------------------------------------------------------


_USE_SCHEMA = {
    "type": "object",
    "properties": {
        "spool_id": {"type": "integer", "description": "The spool to consume from."},
        "use_weight_g": {"type": "number", "description": "Filament weight to consume, in grams."},
        "use_length_mm": {"type": "number", "description": "Filament length to consume, in millimeters."},
        "comment": {"type": "string", "description": "Optional note stored on the usage event."},
    },
    "required": ["spool_id"],
    "additionalProperties": False,
}


async def _use_spool_filament(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _USE_SCHEMA)
    spool_id = _req_int(args, "spool_id")
    weight = _opt_number(args, "use_weight_g")
    length = _opt_number(args, "use_length_mm")
    comment = _opt_str(args, "comment")
    if (weight is None) == (length is None):
        raise ToolError("Provide exactly one of 'use_weight_g' or 'use_length_mm'.")
    try:
        if weight is not None:
            item = await spool.use_weight(db, spool_id, weight, comment=comment)
        else:
            item = await spool.use_length(db, spool_id, length, comment=comment)  # type: ignore[arg-type]
    except ItemNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    return {"spool": spool_brief(item)}


_MEASURE_SCHEMA = {
    "type": "object",
    "properties": {
        "spool_id": {"type": "integer", "description": "The spool that was weighed."},
        "gross_weight_g": {"type": "number", "description": "Current gross weight (spool + filament), in grams."},
        "comment": {"type": "string", "description": "Optional note stored on the usage event."},
    },
    "required": ["spool_id", "gross_weight_g"],
    "additionalProperties": False,
}


async def _measure_spool(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _MEASURE_SCHEMA)
    spool_id = _req_int(args, "spool_id")
    weight = _opt_number(args, "gross_weight_g")
    if weight is None:
        raise ToolError("Argument 'gross_weight_g' is required and must be a number.")
    try:
        item = await spool.measure(db, spool_id, weight, comment=_opt_str(args, "comment"))
    except (ItemNotFoundError, SpoolMeasureError) as exc:
        raise ToolError(str(exc)) from exc
    return {"spool": spool_brief(item)}


_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "filament_id": {"type": "integer", "description": "The filament this spool is made of (see find_filaments)."},
        "initial_weight_g": {
            "type": "number",
            "description": "Net filament weight when full, in grams. Omit to use the filament's default.",
        },
        "price": {"type": "number", "description": "Purchase price of this spool."},
        "location": {"type": "string", "description": "Storage location."},
        "lot_nr": {"type": "string", "description": "Vendor lot number."},
        "comment": {"type": "string", "description": "Free-text note."},
    },
    "required": ["filament_id"],
    "additionalProperties": False,
}


async def _create_spool(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _CREATE_SCHEMA)
    try:
        item = await spool.create(
            db=db,
            filament_id=_req_int(args, "filament_id"),
            initial_weight=_opt_number(args, "initial_weight_g"),
            price=_opt_number(args, "price"),
            location=_opt_str(args, "location"),
            lot_nr=_opt_str(args, "lot_nr"),
            comment=_opt_str(args, "comment"),
        )
    except (ItemNotFoundError, ItemCreateError) as exc:
        raise ToolError(str(exc)) from exc
    return {"spool": spool_brief(item)}


_ARCHIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "spool_id": {"type": "integer", "description": "The spool to archive or unarchive."},
        "archived": {"type": "boolean", "description": "True to archive (default), false to unarchive."},
    },
    "required": ["spool_id"],
    "additionalProperties": False,
}


async def _archive_spool(db: AsyncSession, args: dict) -> dict:
    _check_known_keys(args, _ARCHIVE_SCHEMA)
    spool_id = _req_int(args, "spool_id")
    archived = _opt_bool(args, "archived", default=True)
    try:
        item = await spool.update(db=db, spool_id=spool_id, data={"archived": archived})
    except ItemNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    return {"spool": spool_brief(item)}


# --- Registry ----------------------------------------------------------------------


TOOLS: list[Tool] = [
    Tool(
        name="find_spools",
        description=(
            "Search the spool inventory. Returns compact spools with remaining weight in grams. "
            "Filters combine with AND; matching behaves like the web UI's filters."
        ),
        input_schema=_FIND_SPOOLS_SCHEMA,
        read_only=True,
        handler=_find_spools,
    ),
    Tool(
        name="find_filaments",
        description=(
            "Search the filament catalog (types, not physical spools). Returns compact filaments "
            "with active spool count and total remaining weight in grams."
        ),
        input_schema=_FIND_FILAMENTS_SCHEMA,
        read_only=True,
        handler=_find_filaments,
    ),
    Tool(
        name="get_inventory_stats",
        description="Inventory overview: active spools, total remaining weight, breakdown by material and location.",
        input_schema=_NO_ARGS_SCHEMA,
        read_only=True,
        handler=_get_inventory_stats,
    ),
    Tool(
        name="get_low_stock",
        description=(
            "Filaments at or below their low-stock threshold (per-filament threshold, or the "
            "global fallback for filaments that have stock history), sorted by remaining weight."
        ),
        input_schema=_NO_ARGS_SCHEMA,
        read_only=True,
        handler=_get_low_stock,
    ),
    Tool(
        name="use_spool_filament",
        description=(
            "Record filament consumption on a spool, by weight in grams or length in millimeters "
            "(exactly one). Records a usage event exactly like the web UI."
        ),
        input_schema=_USE_SCHEMA,
        read_only=False,
        handler=_use_spool_filament,
    ),
    Tool(
        name="measure_spool",
        description=(
            "Report a spool's current gross weight from a scale; Spoolman computes the usage since "
            "the last measurement. Fails when the spool lacks the tare data to do the math."
        ),
        input_schema=_MEASURE_SCHEMA,
        read_only=False,
        handler=_measure_spool,
    ),
    Tool(
        name="create_spool",
        description="Register a new physical spool of an existing filament (find the filament_id with find_filaments).",
        input_schema=_CREATE_SCHEMA,
        read_only=False,
        handler=_create_spool,
    ),
    Tool(
        name="archive_spool",
        description="Archive an empty or retired spool (or unarchive it). Archiving keeps history; nothing is deleted.",
        input_schema=_ARCHIVE_SCHEMA,
        read_only=False,
        handler=_archive_spool,
    ),
]

_TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def tools_for_role(role: str) -> list[Tool]:
    """Return the tools visible to a principal: readonly principals never see mutating tools."""
    if role == ROLE_READONLY:
        return [tool for tool in TOOLS if tool.read_only]
    return list(TOOLS)


def visible_tool(name: str, role: str) -> Tool | None:
    """Look up a tool as visible to this role: None when unknown *or* hidden by role gating."""
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None or (role == ROLE_READONLY and not tool.read_only):
        return None
    return tool


async def call_tool(db: AsyncSession, name: str, arguments: dict, role: str) -> dict:
    """Execute a tool for a principal.

    Raises ToolNotFoundError for tools that don't exist *or* are hidden from this role —
    a readonly caller must not be able to distinguish the two. Raises ToolError for
    argument/entity problems (safe to surface to the model verbatim).
    """
    tool = visible_tool(name, role)
    if tool is None:
        raise ToolNotFoundError(f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ToolError("Tool arguments must be an object.")
    return await tool.handler(db, arguments)
