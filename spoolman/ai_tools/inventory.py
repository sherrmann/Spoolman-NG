"""Locations and vendors: the registries a user organises their inventory by.

Reads answer "where do I keep things" and "who do I buy from"; the writes exist so the
assistant can create a location or vendor the user names in passing, instead of dead-ending
a filament creation on a vendor that doesn't exist yet.
"""

from spoolman.ai_tools.base import (
    ConfirmCard,
    ExecutionResult,
    ReadTool,
    ToolContext,
    ToolError,
    WriteTool,
    arg_int,
    arg_limit,
    clean_str,
    require_write,
)
from spoolman.database import location as location_db
from spoolman.database import models
from spoolman.database import vendor as vendor_db
from spoolman.exceptions import ItemNotFoundError


def location_row(location: object, *, spool_count: int, remaining_g: float) -> dict:
    """Shape one location plus its occupancy for the model."""
    return {
        "id": location.id,
        "name": location.name,
        "comment": location.comment,
        "spool_count": spool_count,
        "remaining_weight_g": remaining_g,
    }


async def _run_find_locations(ctx: ToolContext, args: dict) -> dict:
    """List storage locations with how many spools and how much filament each holds.

    Occupancy is computed after the query, so ranking must happen before truncation — the
    registry is fetched unlimited, sorted by weight, and only then capped. Truncating first
    would let "which shelf has the most left" miss the actual answer. The same shape
    find_filaments uses for low_stock_only, and safe here because a location registry is
    inherently small (shelves and dry boxes, not inventory rows).
    """
    limit = arg_limit(args)
    items, total = await location_db.find(db=ctx.db, name=clean_str(args.get("query")))
    ids = [item.id for item in items]
    counts = await location_db.get_aggregates(ctx.db, ids)
    weights = await location_db.get_weight_aggregates(ctx.db, ids)
    rows = [
        location_row(item, spool_count=counts.get(item.id, 0), remaining_g=weights.get(item.id, 0.0)) for item in items
    ]
    rows.sort(key=lambda row: -row["remaining_weight_g"])
    return {"count": total, "returned": min(len(rows), limit), "locations": rows[:limit]}


def vendor_row(vendor: object, *, filament_count: int, spool_count: int) -> dict:
    """Shape one vendor plus its rolled-up counts for the model."""
    return {
        "id": vendor.id,
        "name": vendor.name,
        "comment": vendor.comment,
        "empty_spool_weight_g": vendor.empty_spool_weight,
        "filament_count": filament_count,
        "spool_count": spool_count,
    }


async def _run_find_vendors(ctx: ToolContext, args: dict) -> dict:
    """List vendors with how many filament types and spools the user has from each.

    Vendor rankings are computed after the query, so ranking must happen before truncation — the
    registry is fetched unlimited, sorted by spool count, and only then capped. Truncating first
    would let "who do I buy most from" miss the actual answer.
    """
    limit = arg_limit(args)
    items, total = await vendor_db.find(db=ctx.db, name=clean_str(args.get("query")))
    aggregates = await vendor_db.get_aggregates(ctx.db, [item.id for item in items])
    rows = []
    for item in items:
        counts = aggregates.get(item.id, (0, 0))
        rows.append(vendor_row(item, filament_count=counts[0], spool_count=counts[1]))
    rows.sort(key=lambda row: -row["spool_count"])
    return {"count": total, "returned": min(len(rows), limit), "vendors": rows[:limit]}


READ_TOOLS: dict[str, ReadTool] = {
    "find_locations": ReadTool(
        name="find_locations",
        description=(
            "List the user's storage locations with how many spools and how much filament each holds. "
            "Use for 'where do I keep things', 'which shelf has the most left', or to check a location "
            "name before moving a spool. For the contents of one location, use find_spools with its name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filter by location name."},
                "limit": {"type": "integer", "description": "Max locations to return (default 25)."},
            },
        },
        run=_run_find_locations,
    ),
    "find_vendors": ReadTool(
        name="find_vendors",
        description=(
            "List the manufacturers/vendors the user buys from, with how many filament types and "
            "spools they have from each. Use to check whether a vendor already exists before "
            "creating a filament, or for 'who do I buy most from'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filter by vendor name."},
                "limit": {"type": "integer", "description": "Max vendors to return (default 25)."},
            },
        },
        run=_run_find_vendors,
    ),
}

# --- Write tools -------------------------------------------------------------------


def _require_name(args: dict) -> str:
    name = clean_str(args.get("name"))
    if not name:
        raise ToolError("The 'name' argument is required.")
    return name


async def resolve_vendor_by_name(ctx: ToolContext, name: str) -> models.Vendor | None:
    """Find an existing vendor by name, case-insensitively. None when there is no match.

    Used both by create_vendor (to refuse a duplicate) and by create_filament (to decide
    whether the confirm-card must disclose that a vendor will also be created).
    """
    items, _ = await vendor_db.find(db=ctx.db, name=name)
    lowered = name.strip().lower()
    return next((item for item in items if (item.name or "").strip().lower() == lowered), None)


async def _preview_create_location(ctx: ToolContext, args: dict) -> ConfirmCard:  # noqa: ARG001
    name = _require_name(args)
    after = {"name": name, "comment": clean_str(args.get("comment"))}
    return ConfirmCard(
        tool="create_location",
        title=f"Create the location '{name}'",
        summary=", ".join(f"{key}: {value!r}" for key, value in after.items() if value is not None),
        before={},
        after={key: value for key, value in after.items() if value is not None},
    )


async def _execute_create_location(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    name = _require_name(args)
    created = await location_db.create(db=ctx.db, name=name, comment=clean_str(args.get("comment")))
    return ExecutionResult(
        summary=f"Created the location '{name}'.",
        data={"location_id": created.id, "name": name},
        undo={"tool": "delete_location", "args": {"location_id": created.id}},
    )


async def _preview_delete_location(ctx: ToolContext, args: dict) -> ConfirmCard:
    location_id = arg_int(args, "location_id")
    try:
        item = await location_db.get_by_id(ctx.db, location_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No location with ID {location_id} exists.") from exc
    return ConfirmCard(
        tool="delete_location",
        title=f"Delete the location '{item.name}'",
        summary="Spools stored there keep their location text; only the registry entry is removed.",
        before={"name": item.name},
        after={},
        destructive=True,
    )


async def _execute_delete_location(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    location_id = arg_int(args, "location_id")
    await location_db.delete(ctx.db, location_id)
    return ExecutionResult(summary=f"Deleted location #{location_id}.", data={"location_id": location_id}, undo=None)


async def _preview_create_vendor(ctx: ToolContext, args: dict) -> ConfirmCard:
    name = _require_name(args)
    if await resolve_vendor_by_name(ctx, name) is not None:
        raise ToolError(f"A vendor named '{name}' already exists.")
    after = {"name": name, "comment": clean_str(args.get("comment"))}
    return ConfirmCard(
        tool="create_vendor",
        title=f"Create the vendor '{name}'",
        summary=", ".join(f"{key}: {value!r}" for key, value in after.items() if value is not None),
        before={},
        after={key: value for key, value in after.items() if value is not None},
    )


async def _execute_create_vendor(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    name = _require_name(args)
    created = await vendor_db.create(db=ctx.db, name=name, comment=clean_str(args.get("comment")))
    return ExecutionResult(
        summary=f"Created the vendor '{name}'.",
        data={"vendor_id": created.id, "name": name},
        undo={"tool": "delete_vendor", "args": {"vendor_id": created.id}},
    )


async def _preview_delete_vendor(ctx: ToolContext, args: dict) -> ConfirmCard:
    vendor_id = arg_int(args, "vendor_id")
    try:
        item = await vendor_db.get_by_id(ctx.db, vendor_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No vendor with ID {vendor_id} exists.") from exc
    return ConfirmCard(
        tool="delete_vendor",
        title=f"Delete the vendor '{item.name}'",
        summary="Filaments from this vendor keep existing but lose their vendor link.",
        before={"name": item.name},
        after={},
        destructive=True,
    )


async def _execute_delete_vendor(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    vendor_id = arg_int(args, "vendor_id")
    await vendor_db.delete(ctx.db, vendor_id)
    return ExecutionResult(summary=f"Deleted vendor #{vendor_id}.", data={"vendor_id": vendor_id}, undo=None)


WRITE_TOOLS: dict[str, WriteTool] = {
    "create_location": WriteTool(
        name="create_location",
        description="Create a named storage location, e.g. 'Shelf B' or 'Dry box 1'. Requires user confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The location name."},
                "comment": {"type": "string"},
            },
            "required": ["name"],
        },
        preview=_preview_create_location,
        execute=_execute_create_location,
    ),
    "delete_location": WriteTool(
        name="delete_location",
        description="Delete a location registry entry (internal undo helper).",
        parameters={
            "type": "object",
            "properties": {"location_id": {"type": "integer"}},
            "required": ["location_id"],
        },
        preview=_preview_delete_location,
        execute=_execute_delete_location,
        model_facing=False,
    ),
    "create_vendor": WriteTool(
        name="create_vendor",
        description=(
            "Create a filament manufacturer/vendor by name. Requires user confirmation. Check "
            "find_vendors first: creating a duplicate is refused."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The vendor name."},
                "comment": {"type": "string"},
            },
            "required": ["name"],
        },
        preview=_preview_create_vendor,
        execute=_execute_create_vendor,
    ),
    "delete_vendor": WriteTool(
        name="delete_vendor",
        description="Delete a vendor (internal undo helper).",
        parameters={
            "type": "object",
            "properties": {"vendor_id": {"type": "integer"}},
            "required": ["vendor_id"],
        },
        preview=_preview_delete_vendor,
        execute=_execute_delete_vendor,
        model_facing=False,
    ),
}
