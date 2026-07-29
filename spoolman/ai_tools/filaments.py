"""Filament tools: search, and create a brand-new filament type.

Thin wrappers over :mod:`spoolman.database.filament` and :mod:`spoolman.database.vendor` —
see :mod:`spoolman.ai_tools` for the guardrails these tools operate under.
"""

import logging

from spoolman.ai_tools import inventory
from spoolman.ai_tools.base import (
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
    low_stock_fallback_g,
    require_write,
)
from spoolman.database import filament as filament_db
from spoolman.database import vendor as vendor_db

logger = logging.getLogger(__name__)

# --- Read tools --------------------------------------------------------------------


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

#: The only filament fields the agent may set. filament.create accepts ~25; the rest are either
#: derived, integration-owned (external_id), or belong to forms the user should use directly.
_CURATED = {
    "name": ("name", "str"),
    "material": ("material", "str"),
    "weight_g": ("weight", "float"),
    "spool_weight_g": ("spool_weight", "float"),
    "price": ("price", "float"),
    "article_number": ("article_number", "str"),
    "extruder_temp": ("settings_extruder_temp", "int"),
    "bed_temp": ("settings_bed_temp", "int"),
    "low_stock_threshold_g": ("low_stock_threshold", "float"),
    "comment": ("comment", "str"),
}


_HEX_COLOR_LENGTH = 6


def _color_hex(args: dict) -> str | None:
    """Normalise a colour argument to a bare 6-digit hex, or raise."""
    raw = clean_str(args.get("color_hex"))
    if raw is None:
        return None
    candidate = raw.lstrip("#").upper()
    if len(candidate) != _HEX_COLOR_LENGTH or any(char not in "0123456789ABCDEF" for char in candidate):
        raise ToolError(f"The 'color_hex' argument must be a 6-digit hex colour, got {args['color_hex']!r}.")
    return candidate


def curated_fields(args: dict, *, require_physics: bool = True) -> dict:
    """Map tool arguments onto filament.create/update kwargs, keeping only the curated subset.

    ``density`` and ``diameter`` are required on create and are never defaulted: they are exactly
    the fields a model will confidently fabricate, and a wrong density silently corrupts every
    weight calculation for that filament forever. The model is told to call catalog_lookup or ask.
    """
    fields: dict = {}
    if require_physics or args.get("density") is not None:
        fields["density"] = arg_float(args, "density")
    if require_physics or args.get("diameter") is not None:
        fields["diameter"] = arg_float(args, "diameter")

    for arg_name, (column, kind) in _CURATED.items():
        if args.get(arg_name) is None:
            continue
        if kind == "str":
            value = clean_str(args.get(arg_name))
            if value is not None:
                fields[column] = value
        elif kind == "float":
            fields[column] = arg_float(args, arg_name)
        else:
            fields[column] = arg_int(args, arg_name)

    color = _color_hex(args)
    if color is not None:
        fields["color_hex"] = color
    return fields


async def _resolve_vendor(ctx: ToolContext, args: dict) -> tuple[object | None, str | None]:
    """Return (existing vendor or None, vendor name to create or None)."""
    name = clean_str(args.get("vendor_name"))
    if name is None:
        return None, None
    existing = await inventory.resolve_vendor_by_name(ctx, name)
    return (existing, None) if existing is not None else (None, name)


async def _preview_create_filament(ctx: ToolContext, args: dict) -> ConfirmCard:
    fields = curated_fields(args)
    existing_vendor, vendor_to_create = await _resolve_vendor(ctx, args)
    after = {key: value for key, value in fields.items() if value is not None}
    if existing_vendor is not None:
        after["vendor"] = existing_vendor.name
    summary = ", ".join(f"{key}: {value!r}" for key, value in after.items())
    if vendor_to_create is not None:
        # Creating a vendor as a side effect is a change the user never asked for unless we say so.
        after["vendor"] = vendor_to_create
        summary = f"{summary}. This also creates the vendor '{vendor_to_create}'."
    return ConfirmCard(
        tool="create_filament",
        title=f"Create the filament {after.get('name') or after.get('material') or 'entry'}",
        summary=summary,
        before={},
        after=after,
    )


async def _cleanup_orphaned_vendor(ctx: ToolContext, created_vendor_id: int | None) -> None:
    """Delete a vendor this same call just created, after the following filament create failed.

    ``vendor_db.create`` commits immediately and durably; if ``filament_db.create`` then raises
    for any reason (a raw ``IntegrityError`` included -- ``filament.create`` has no try/except of
    its own around its commit), leaving that vendor in place would be the exact silent vendor
    creation this tool exists to prevent, reached through the error path instead of the happy one.

    Never called with a vendor this call did not create: ``created_vendor_id`` is None whenever
    ``vendor_name`` resolved to an existing vendor, and this function's only caller respects that.
    A failed commit leaves the session needing a rollback before it can be reused, so that happens
    here too. Any failure during cleanup itself is logged, never raised -- it must not mask the
    original error the caller is about to report.
    """
    if created_vendor_id is None:
        return
    try:
        await ctx.db.rollback()
        await vendor_db.delete(ctx.db, created_vendor_id)
    except Exception:  # Cleanup is best-effort; the original error still gets raised by the caller.
        logger.exception("Failed to clean up orphaned vendor %s after a failed filament create.", created_vendor_id)


async def _execute_create_filament(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    fields = curated_fields(args)
    existing_vendor, vendor_to_create = await _resolve_vendor(ctx, args)
    vendor_id = existing_vendor.id if existing_vendor is not None else None
    created_vendor_id = None
    if vendor_to_create is not None:
        created_vendor = await vendor_db.create(db=ctx.db, name=vendor_to_create)
        vendor_id = created_vendor.id
        created_vendor_id = created_vendor.id
    try:
        created = await filament_db.create(db=ctx.db, vendor_id=vendor_id, **fields)
    except Exception as exc:  # Any failure here must not leave an orphaned vendor behind.
        await _cleanup_orphaned_vendor(ctx, created_vendor_id)
        raise ToolError(str(exc)) from exc
    summary = f"Created filament #{created.id}."
    if created_vendor_id is not None:
        summary = f"{summary} Also created the vendor '{vendor_to_create}'."
    return ExecutionResult(
        summary=summary,
        data={"filament_id": created.id, "vendor_id": vendor_id},
        undo={"tool": "delete_filament", "args": {"filament_id": created.id}},
    )


# --- Registry ----------------------------------------------------------------------

READ_TOOLS: dict[str, ReadTool] = {
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
    "create_filament": WriteTool(
        name="create_filament",
        description=(
            "Create a new filament type. density (g/cm3) and diameter (mm) are required and must be "
            "real: call catalog_lookup first or ask the user, never guess them. vendor_name creates "
            "the vendor if it does not exist. Requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Product name, e.g. 'PLA Meta'."},
                "vendor_name": {"type": "string", "description": "Manufacturer name; created if unknown."},
                "material": {"type": "string", "description": "e.g. PLA, PETG, ASA."},
                "density": {"type": "number", "description": "g/cm3. Required. Never guess."},
                "diameter": {"type": "number", "description": "mm, e.g. 1.75. Required. Never guess."},
                "weight_g": {"type": "number", "description": "Net filament weight of a full spool."},
                "spool_weight_g": {"type": "number", "description": "Weight of the empty spool."},
                "color_hex": {"type": "string", "description": "6-digit hex without '#'."},
                "price": {"type": "number"},
                "extruder_temp": {"type": "integer"},
                "bed_temp": {"type": "integer"},
                "article_number": {"type": "string"},
                "low_stock_threshold_g": {"type": "number"},
                "comment": {"type": "string"},
            },
            "required": ["density", "diameter"],
        },
        preview=_preview_create_filament,
        execute=_execute_create_filament,
    ),
}
