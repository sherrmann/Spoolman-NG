"""Spool and filament tools: search, update, consume, create, delete.

Thin wrappers over :mod:`spoolman.database.spool` and :mod:`spoolman.database.filament` —
see :mod:`spoolman.ai_tools` for the guardrails these tools operate under.
"""

from spoolman.ai_tools.base import (
    COLOR_SIMILARITY_THRESHOLD,
    DEFAULT_LIMIT,
    ConfirmCard,
    ExecutionResult,
    ReadTool,
    ToolContext,
    ToolError,
    WriteTool,
    arg_bool,
    arg_float,
    arg_int,
    arg_limit,
    clean_str,
    combined_name,
    echo_spool_filters,
    get_spool,
    initial_weight,
    low_stock_fallback_g,
    optional_float,
    remaining_weight,
    require_write,
    spool_brief,
)
from spoolman.database import filament as filament_db
from spoolman.database import models
from spoolman.database import spool as spool_db
from spoolman.database.utils import SortOrder
from spoolman.exceptions import ItemCreateError, ItemNotFoundError

# --- Read tools --------------------------------------------------------------------


async def _run_find_spools(ctx: ToolContext, args: dict) -> dict:
    """Search spools by the same fields the spool list exposes; sum their remaining weight."""
    limit = arg_limit(args)
    include_archived = arg_bool(args, "include_archived")

    filament_ids: list[int] | None = None
    color_hex = args.get("color_hex")
    if isinstance(color_hex, str) and color_hex.strip():
        matched = await filament_db.find_by_color(
            db=ctx.db,
            color_query_hex=color_hex.strip().lstrip("#"),
            similarity_threshold=COLOR_SIMILARITY_THRESHOLD,
        )
        filament_ids = [fil.id for fil in matched]
        if not filament_ids:
            # A colour with no matching filament means no spools — short-circuit before querying.
            return {
                "count": 0,
                "returned": 0,
                "total_remaining_weight_g": 0.0,
                "spools": [],
                "filters": echo_spool_filters(args),
            }

    items, total = await spool_db.find(
        db=ctx.db,
        search=clean_str(args.get("query")),
        filament_id=filament_ids,
        filament_material=clean_str(args.get("material")),
        vendor_name=clean_str(args.get("vendor")),
        location=clean_str(args.get("location")),
        lot_nr=clean_str(args.get("lot_nr")),
        allow_archived=include_archived,
        sort_by={"remaining_weight": SortOrder.DESC},
        limit=limit,
    )
    briefs = [spool_brief(item) for item in items]
    total_remaining = round(sum(b["remaining_weight_g"] or 0.0 for b in briefs), 1)
    return {
        "count": total,
        "returned": len(briefs),
        "total_remaining_weight_g": total_remaining,
        "spools": briefs,
        "filters": echo_spool_filters(args),
    }


async def _run_find_filaments(ctx: ToolContext, args: dict) -> dict:
    """List filaments with rolled-up remaining weight, low-stock status, and on-order signal."""
    limit = arg_limit(args)
    low_stock_only = arg_bool(args, "low_stock_only")

    items, _ = await filament_db.find(
        db=ctx.db,
        search=clean_str(args.get("query")),
        material=clean_str(args.get("material")),
        vendor_name=clean_str(args.get("vendor")),
        limit=None if low_stock_only else limit,
    )
    ids = [item.id for item in items]
    aggregates = await filament_db.get_aggregates(ctx.db, ids)
    on_order = await filament_db.get_on_order(ctx.db, ids)
    fallback = await low_stock_fallback_g(ctx.db)

    rows = []
    for item in items:
        spool_count, remaining = aggregates.get(item.id, (0, 0.0))
        threshold = item.low_stock_threshold or fallback
        is_low = threshold is not None and threshold > 0 and remaining <= threshold
        if low_stock_only and not is_low:
            continue
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "vendor": item.vendor.name if item.vendor is not None else None,
                "material": item.material,
                "color_hex": item.color_hex,
                "total_remaining_weight_g": round(remaining, 1),
                "active_spool_count": spool_count,
                "low_stock": is_low,
                "low_stock_threshold_g": round(threshold, 1) if threshold else None,
                "reserve_count": item.reserve_count,
                "on_order": item.id in on_order,
            },
        )
    rows.sort(key=lambda row: row["total_remaining_weight_g"])
    return {"count": len(rows), "filaments": rows[:limit]}


# --- Write tools -------------------------------------------------------------------

_UPDATABLE_FIELDS = ("location", "lot_nr", "comment", "archived", "price")


def _spool_update_view(spool: models.Spool) -> dict:
    """Return the editable fields of a spool, for a before/after confirm-card."""
    return {
        "location": spool.location,
        "lot_nr": spool.lot_nr,
        "comment": spool.comment,
        "archived": bool(spool.archived),
        "price": spool.price,
    }


def _requested_changes(args: dict) -> dict:
    """Return the subset of updatable fields the caller actually provided, typed.

    ``price`` and ``archived`` are coerced here rather than handed to the database layer
    as whatever the model emitted ("12,50", "yes"), so a bad value is a ToolError the
    model can correct instead of a failure deeper down.
    """
    changes = {key: args[key] for key in _UPDATABLE_FIELDS if key in args and args[key] is not None}
    if "price" in changes:
        changes["price"] = arg_float(args, "price")
    if "archived" in changes:
        changes["archived"] = arg_bool(args, "archived")
    return changes


async def _preview_update_spool(ctx: ToolContext, args: dict) -> ConfirmCard:
    spool = await get_spool(ctx, arg_int(args, "spool_id"))
    before = _spool_update_view(spool)
    changes = _requested_changes(args)
    if not changes:
        raise ToolError("No changes were provided to update.")
    after = {**before, **changes}
    summary = ", ".join(f"{key}: {before[key]!r} -> {after[key]!r}" for key in changes)
    return ConfirmCard(
        tool="update_spool",
        title=f"Update spool #{spool.id} ({combined_name(spool)})",
        summary=summary,
        before={key: before[key] for key in changes},
        after={key: after[key] for key in changes},
    )


async def _execute_update_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    spool_id = arg_int(args, "spool_id")
    spool = await get_spool(ctx, spool_id)
    before = _spool_update_view(spool)
    changes = _requested_changes(args)
    if not changes:
        raise ToolError("No changes were provided to update.")
    await spool_db.update(db=ctx.db, spool_id=spool_id, data=dict(changes))
    undo_args = {"spool_id": spool_id, **{key: before[key] for key in changes}}
    return ExecutionResult(
        summary=f"Updated spool #{spool_id}: " + ", ".join(f"{key} -> {changes[key]!r}" for key in changes),
        data={"spool_id": spool_id, "changed": list(changes)},
        undo={"tool": "update_spool", "args": undo_args},
    )


async def _preview_consume_spool(ctx: ToolContext, args: dict) -> ConfirmCard:
    spool = await get_spool(ctx, arg_int(args, "spool_id"))
    delta = arg_float(args, "use_weight_g")
    remaining = remaining_weight(spool)
    after_remaining = None if remaining is None else round(max(remaining - delta, 0.0), 1)
    verb = "Consume" if delta >= 0 else "Add back"
    return ConfirmCard(
        tool="consume_spool",
        title=f"{verb} {abs(delta):g} g on spool #{spool.id} ({combined_name(spool)})",
        summary=f"remaining_weight_g: {remaining!r} -> {after_remaining!r}",
        before={"remaining_weight_g": remaining},
        after={"remaining_weight_g": after_remaining},
    )


async def _execute_consume_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    spool_id = arg_int(args, "spool_id")
    delta = arg_float(args, "use_weight_g")
    spool = await get_spool(ctx, spool_id)
    used_before = spool.used_weight
    new_used = max(used_before + delta, 0.0)
    initial = initial_weight(spool)
    if initial is not None:
        new_used = min(new_used, initial)
    await spool_db.update(db=ctx.db, spool_id=spool_id, data={"used_weight": new_used})
    return ExecutionResult(
        summary=f"Adjusted spool #{spool_id} usage by {delta:g} g.",
        data={"spool_id": spool_id, "used_weight_g": round(new_used, 1)},
        undo={"tool": "set_spool_used_weight", "args": {"spool_id": spool_id, "used_weight_g": round(used_before, 1)}},
    )


async def _preview_set_used_weight(ctx: ToolContext, args: dict) -> ConfirmCard:
    """Preview the undo counterpart of consume_spool: setting used_weight to an exact value."""
    spool = await get_spool(ctx, arg_int(args, "spool_id"))
    return ConfirmCard(
        tool="set_spool_used_weight",
        title=f"Restore usage on spool #{spool.id}",
        summary=f"used_weight_g -> {arg_float(args, 'used_weight_g'):g}",
        before={"used_weight_g": round(spool.used_weight, 1)},
        after={"used_weight_g": arg_float(args, "used_weight_g")},
    )


async def _execute_set_used_weight(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    spool_id = arg_int(args, "spool_id")
    spool = await get_spool(ctx, spool_id)
    used_before = spool.used_weight
    new_used = max(arg_float(args, "used_weight_g"), 0.0)
    await spool_db.update(db=ctx.db, spool_id=spool_id, data={"used_weight": new_used})
    return ExecutionResult(
        summary=f"Set spool #{spool_id} used weight to {new_used:g} g.",
        data={"spool_id": spool_id, "used_weight_g": round(new_used, 1)},
        undo={"tool": "set_spool_used_weight", "args": {"spool_id": spool_id, "used_weight_g": round(used_before, 1)}},
    )


async def _preview_create_spool(ctx: ToolContext, args: dict) -> ConfirmCard:
    filament_id = arg_int(args, "filament_id")
    try:
        fil = await filament_db.get_by_id(ctx.db, filament_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No filament with ID {filament_id} exists.") from exc
    after = {
        "filament": " - ".join(p for p in (fil.vendor.name if fil.vendor else None, fil.name) if p) or fil.material,
        "location": clean_str(args.get("location")),
        "lot_nr": clean_str(args.get("lot_nr")),
        "initial_weight_g": optional_float(args, "initial_weight_g"),
        "price": optional_float(args, "price"),
    }
    return ConfirmCard(
        tool="create_spool",
        title=f"Create a new spool of {after['filament']}",
        summary=", ".join(f"{key}: {value!r}" for key, value in after.items() if value is not None),
        before={},
        after={key: value for key, value in after.items() if value is not None},
    )


async def _execute_create_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    filament_id = arg_int(args, "filament_id")
    try:
        created = await spool_db.create(
            db=ctx.db,
            filament_id=filament_id,
            location=clean_str(args.get("location")),
            lot_nr=clean_str(args.get("lot_nr")),
            initial_weight=optional_float(args, "initial_weight_g"),
            price=optional_float(args, "price"),
        )
    except (ItemNotFoundError, ItemCreateError) as exc:
        raise ToolError(str(exc)) from exc
    return ExecutionResult(
        summary=f"Created spool #{created.id}.",
        data={"spool_id": created.id},
        undo={"tool": "delete_spool", "args": {"spool_id": created.id}},
    )


async def _preview_delete_spool(ctx: ToolContext, args: dict) -> ConfirmCard:
    spool = await get_spool(ctx, arg_int(args, "spool_id"))
    return ConfirmCard(
        tool="delete_spool",
        title=f"Delete spool #{spool.id} ({combined_name(spool)})",
        summary="This permanently deletes the spool and its usage history. It cannot be undone.",
        before=spool_brief(spool),
        after={},
        destructive=True,
    )


async def _execute_delete_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    spool_id = arg_int(args, "spool_id")
    await get_spool(ctx, spool_id)  # 404s as a clean ToolError before deleting
    await spool_db.delete(ctx.db, spool_id)
    return ExecutionResult(summary=f"Deleted spool #{spool_id}.", data={"spool_id": spool_id}, undo=None)


# --- Registry ----------------------------------------------------------------------

READ_TOOLS: dict[str, ReadTool] = {
    "find_spools": ReadTool(
        name="find_spools",
        description=(
            "Search the user's spools by filament material, vendor, colour (as a 6-digit hex, no #), "
            "location, lot number, and/or a free-text query. Returns each matching spool with its "
            "remaining weight in grams and the summed total. Use this to answer 'how much X do I have'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "material": {"type": "string", "description": "Filament material, e.g. PLA, PETG, ASA."},
                "vendor": {"type": "string", "description": "Vendor/manufacturer name."},
                "color_hex": {"type": "string", "description": "Colour as a 6-digit hex without '#', e.g. 000000."},
                "location": {"type": "string", "description": "Storage location, e.g. 'Shelf B'."},
                "lot_nr": {"type": "string", "description": "Lot/batch number."},
                "query": {"type": "string", "description": "Free-text search across spool and filament fields."},
                "include_archived": {"type": "boolean", "description": "Include archived spools (default false)."},
                "limit": {"type": "integer", "description": f"Max spools to return (default {DEFAULT_LIMIT})."},
            },
        },
        run=_run_find_spools,
    ),
    "find_filaments": ReadTool(
        name="find_filaments",
        description=(
            "List the user's filament types with total remaining weight across their spools, low-stock "
            "status, spare-spool reserve, and whether more is on order. Set low_stock_only to answer "
            "'what should I reorder?'. Use the returned materials to reason about suitability "
            "(e.g. which resist UV/outdoors)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "material": {"type": "string", "description": "Filter by material."},
                "vendor": {"type": "string", "description": "Filter by vendor name."},
                "query": {"type": "string", "description": "Free-text search across filament fields."},
                "low_stock_only": {"type": "boolean", "description": "Return only filaments at or below threshold."},
                "limit": {"type": "integer", "description": f"Max filaments to return (default {DEFAULT_LIMIT})."},
            },
        },
        run=_run_find_filaments,
    ),
}

WRITE_TOOLS: dict[str, WriteTool] = {
    "update_spool": WriteTool(
        name="update_spool",
        description=(
            "Change a spool's location, lot number, comment, price, or archived flag. Only the fields "
            "you pass are changed. Requires user confirmation before it runs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "spool_id": {"type": "integer", "description": "The spool to update."},
                "location": {"type": "string"},
                "lot_nr": {"type": "string"},
                "comment": {"type": "string"},
                "archived": {"type": "boolean"},
                "price": {"type": "number"},
            },
            "required": ["spool_id"],
        },
        preview=_preview_update_spool,
        execute=_execute_update_spool,
    ),
    "consume_spool": WriteTool(
        name="consume_spool",
        description=(
            "Record filament used from a spool: a positive use_weight_g consumes that many grams, a "
            "negative value adds filament back. Requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "spool_id": {"type": "integer"},
                "use_weight_g": {"type": "number", "description": "Grams to consume (negative to add back)."},
            },
            "required": ["spool_id", "use_weight_g"],
        },
        preview=_preview_consume_spool,
        execute=_execute_consume_spool,
    ),
    # Not offered to the model (kept out of the schema list); exists only so consume_spool's
    # undo can restore an exact prior used_weight.
    "set_spool_used_weight": WriteTool(
        name="set_spool_used_weight",
        description="Set a spool's used weight to an exact value (internal undo helper).",
        parameters={
            "type": "object",
            "properties": {
                "spool_id": {"type": "integer"},
                "used_weight_g": {"type": "number"},
            },
            "required": ["spool_id", "used_weight_g"],
        },
        preview=_preview_set_used_weight,
        execute=_execute_set_used_weight,
        model_facing=False,
    ),
    "create_spool": WriteTool(
        name="create_spool",
        description=(
            "Create a new spool of an existing filament (by filament_id). Optionally set location, lot "
            "number, initial weight, and price. Requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filament_id": {"type": "integer", "description": "The filament this spool holds."},
                "location": {"type": "string"},
                "lot_nr": {"type": "string"},
                "initial_weight_g": {"type": "number", "description": "Net filament weight in grams."},
                "price": {"type": "number"},
            },
            "required": ["filament_id"],
        },
        preview=_preview_create_spool,
        execute=_execute_create_spool,
    ),
    "delete_spool": WriteTool(
        name="delete_spool",
        description="Permanently delete a spool. Destructive and cannot be undone. Requires user confirmation.",
        parameters={
            "type": "object",
            "properties": {"spool_id": {"type": "integer"}},
            "required": ["spool_id"],
        },
        preview=_preview_delete_spool,
        execute=_execute_delete_spool,
    ),
}
