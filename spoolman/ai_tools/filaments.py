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
from spoolman.exceptions import ItemCreateError, ItemDeleteError, ItemNotFoundError

logger = logging.getLogger(__name__)

# --- Read tools --------------------------------------------------------------------


async def _run_find_filaments(ctx: ToolContext, args: dict) -> dict:
    """List filaments with rolled-up remaining weight, low-stock status, and on-order signal."""
    limit = arg_limit(args)
    low_stock_only = arg_bool(args, "low_stock_only")

    items, total = await filament_db.find(
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
    # count is the TRUE total, returned is how many of them are in this page -- the contract every
    # sibling find_* tool follows (tests/integration/test_ai_chat_endpoints.py pins it across all of
    # them). Reporting len(rows) as the count made "how many filament types do I have?" answer with
    # the page size, confidently and with no signal that anything was truncated. With low_stock_only
    # the fetch is unlimited and the filtering happens here, so rows IS the complete match set and
    # its length is the true total; otherwise the database's own total counts the rows past the cap.
    count = len(rows) if low_stock_only else total
    return {"count": count, "returned": min(len(rows), limit), "filaments": rows[:limit]}


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

#: Column name -> tool argument name, so an undo descriptor can be expressed in tool arguments.
_COLUMN_TO_ARG = {column: arg for arg, (column, _kind) in _CURATED.items()}
_COLUMN_TO_ARG.update({"density": "density", "diameter": "diameter", "color_hex": "color_hex"})


#: RRGGBB or RRGGBBAA -- the exact band the rest of the codebase uses: the API model declares
#: min_length=6, max_length=8 ("Supports alpha channel at the end") and _normalize_stored_color_hex
#: accepts len(clr) in (6, 8). Accepting only 6 here broke two live paths, not a hypothetical one:
#: update_filament's undo descriptor is built from the *stored* before-value, so a filament stored
#: with an alpha colour produced an undo that raised on replay (a 422 from /ai/chat/action -- Undo
#: simply did not work), and find_filaments hands the model raw stored colours, so echoing one back
#: failed the whole call.
_HEX_COLOR_LENGTHS = (6, 8)


def _color_hex(args: dict) -> str | None:
    """Normalise a colour argument to a bare 6- or 8-digit hex, or raise."""
    raw = clean_str(args.get("color_hex"))
    if raw is None:
        return None
    candidate = raw.lstrip("#").upper()
    if len(candidate) not in _HEX_COLOR_LENGTHS or any(char not in "0123456789ABCDEF" for char in candidate):
        raise ToolError(
            "The 'color_hex' argument must be a 6-digit hex colour, or 8 digits with an alpha "
            f"channel, got {args['color_hex']!r}.",
        )
    return candidate


def _coerce_curated_entry(args: dict, arg_name: str, kind: str) -> tuple[bool, object]:
    """Coerce one already-present curated argument; returns (should_set, coerced_value).

    ``should_set`` is False only for a blank string, which (unlike an explicit None) means
    "nothing was really provided" rather than "clear this field" -- matching the long-standing
    ``clean_str`` behaviour for every other string field in this tool layer.
    """
    value = args[arg_name]
    if value is None:
        return True, None
    if kind == "str":
        cleaned = clean_str(value)
        return cleaned is not None, cleaned
    if kind == "float":
        return True, arg_float(args, arg_name)
    return True, arg_int(args, arg_name)


def _apply_color_hex(args: dict, fields: dict) -> None:
    """Set or clear ``fields['color_hex']`` from ``args``, if the key was provided at all."""
    if "color_hex" not in args:
        return
    if args["color_hex"] is None:
        fields["color_hex"] = None
        return
    color = _color_hex(args)
    if color is not None:
        fields["color_hex"] = color


def curated_fields(args: dict, *, require_physics: bool = True) -> dict:
    """Map tool arguments onto filament.create/update kwargs, keeping only the curated subset.

    ``density`` and ``diameter`` are required on create and are never defaulted: they are exactly
    the fields a model will confidently fabricate, and a wrong density silently corrupts every
    weight calculation for that filament forever. The model is told to call catalog_lookup or ask.

    Change-detection is by *key presence*, not truthiness: most curated columns are nullable, and
    an update's undo descriptor carries the prior value verbatim, None included. Treating an
    explicit None the same as "not provided" would make that value un-undoable -- restoring a
    field to None would either be silently dropped (if other fields also changed) or look like an
    empty change set (if it was the only one). A key absent from ``args`` is left alone; a key
    present with value None clears that column.
    """
    fields: dict = {}
    if require_physics or "density" in args:
        fields["density"] = arg_float(args, "density")
    if require_physics or "diameter" in args:
        fields["diameter"] = arg_float(args, "diameter")

    for arg_name, (column, kind) in _CURATED.items():
        if arg_name not in args:
            continue
        should_set, value = _coerce_curated_entry(args, arg_name, kind)
        if should_set:
            fields[column] = value

    _apply_color_hex(args, fields)
    return fields


def changes_for_update(args: dict) -> dict:
    """Return the curated fields the caller actually provided, for an update; error when empty."""
    changes = curated_fields(args, require_physics=False)
    if not changes:
        raise ToolError("No changes were provided to update.")
    return changes


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
    except (ItemNotFoundError, ItemCreateError) as exc:
        # These two carry messages written for a person (e.g. "No vendor with ID 7 found."), so
        # they pass through verbatim -- the model can act on them.
        await _cleanup_orphaned_vendor(ctx, created_vendor_id)
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # Any failure here must not leave an orphaned vendor behind.
        # ToolError's message is shown to the user, fed back to the model, and (via mcp_server,
        # whose _call_tool docstring promises no internal detail crosses the MCP boundary) returned
        # to an arbitrary MCP client. A raw SQLAlchemy IntegrityError string is none of those
        # things: it embeds the failing SQL with table and column names. Log the real one, hand out
        # a curated one -- the same split aichat's _TOOL_FAILED already makes.
        await _cleanup_orphaned_vendor(ctx, created_vendor_id)
        logger.exception("create_filament failed while creating a filament with fields %r.", sorted(fields))
        raise ToolError("Could not create the filament. Check the values and try again.") from exc
    summary = f"Created filament #{created.id}."
    # only_if_empty is never in delete_filament's model-facing schema -- it exists purely so this
    # undo descriptor can refuse to cascade. Between this create and a click on the resulting
    # Undo button, the user may have added spools to the filament; a bare delete_filament call
    # would destroy them (and their usage history) with no count and no confirmation, the exact
    # silent-cascade-via-undo failure this flag exists to close off. The normal, previewed
    # delete_filament path (the model calling it directly, or a confirmed chat write) never
    # sets this flag, so it still discloses and cascades exactly as before.
    undo_args: dict = {"filament_id": created.id, "only_if_empty": True}
    if created_vendor_id is not None:
        summary = f"{summary} Also created the vendor '{vendor_to_create}'."
        # ...and undoing this creation must also take that vendor back out, or Undo would leave
        # behind a registry entry the user never asked for. /ai/chat/action runs exactly one tool
        # per call, so this cannot be a second action: delete_filament carries the id and removes
        # the vendor itself, after the filament and only while the vendor has no other filaments.
        # Like only_if_empty, this argument is absent from delete_filament's schema and is only
        # ever set here, on a vendor id this very call brought into existence.
        undo_args["also_delete_vendor_id"] = created_vendor_id
    return ExecutionResult(
        summary=summary,
        data={"filament_id": created.id, "vendor_id": vendor_id},
        undo={"tool": "delete_filament", "args": undo_args},
    )


def _filament_view(item: object, keys: list[str]) -> dict:
    """Return the current values of the named columns, for a before/after card."""
    return {key: getattr(item, key) for key in keys}


async def _get_filament(ctx: ToolContext, filament_id: int) -> object:
    """Fetch a filament by ID, or raise a model-facing ToolError if it doesn't exist."""
    try:
        return await filament_db.get_by_id(ctx.db, filament_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No filament with ID {filament_id} exists.") from exc


async def _preview_update_filament(ctx: ToolContext, args: dict) -> ConfirmCard:
    item = await _get_filament(ctx, arg_int(args, "filament_id"))
    changes = changes_for_update(args)
    before = _filament_view(item, list(changes))
    return ConfirmCard(
        tool="update_filament",
        title=f"Update filament #{item.id} ({item.name or item.material or 'unnamed'})",
        summary=", ".join(f"{key}: {before[key]!r} -> {changes[key]!r}" for key in changes),
        before=before,
        after=dict(changes),
    )


async def _execute_update_filament(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    filament_id = arg_int(args, "filament_id")
    item = await _get_filament(ctx, filament_id)
    changes = changes_for_update(args)
    before = _filament_view(item, list(changes))
    await filament_db.update(db=ctx.db, filament_id=filament_id, data=dict(changes))
    # The undo descriptor speaks the tool's argument names, not the column names.
    reverse = {_COLUMN_TO_ARG[column]: value for column, value in before.items()}
    return ExecutionResult(
        summary=f"Updated filament #{filament_id}: " + ", ".join(f"{k} -> {v!r}" for k, v in changes.items()),
        data={"filament_id": filament_id, "changed": list(changes)},
        undo={"tool": "update_filament", "args": {"filament_id": filament_id, **reverse}},
    )


async def _preview_delete_filament(ctx: ToolContext, args: dict) -> ConfirmCard:
    filament_id = arg_int(args, "filament_id")
    item = await _get_filament(ctx, filament_id)
    line_count = await filament_db.count_order_line_references(ctx.db, filament_id)
    if line_count:
        # filament_db.delete would raise ItemDeleteError in that case -- refuse before the user
        # confirms a delete that then fails, the worst possible sequence for a destructive change.
        raise ToolError(
            f"Cannot delete filament {filament_id}: {line_count} order line(s) reference it. "
            "Delete or amend those orders first.",
        )
    # The true blast radius, not just the active-inventory rollup: an archived spool is destroyed
    # by the cascade exactly like an active one, so it must count here too. filament_db.get_aggregates
    # deliberately excludes archived spools (it answers "what's in stock"), the wrong lens for a
    # destructive, no-undo preview.
    spool_count = await filament_db.count_spools(ctx.db, filament_id)
    return ConfirmCard(
        tool="delete_filament",
        title=f"Delete filament #{filament_id} ({item.name or item.material or 'unnamed'})",
        summary=(
            f"This permanently deletes the filament and its {spool_count} spool(s), including their "
            "usage history. It cannot be undone."
        ),
        before={"name": item.name, "material": item.material, "spool_count": spool_count},
        after={},
        destructive=True,
    )


async def _delete_vendor_created_with_the_filament(ctx: ToolContext, vendor_id: int) -> str | None:
    """Delete the vendor create_filament auto-created, now that its filament is gone. Returns its name.

    Reached only through ``also_delete_vendor_id``, which is absent from delete_filament's
    model-facing schema and is set only by create_filament's own undo descriptor -- so the vendor
    named here is always one that same call brought into existence, never one the user already had.
    It is still checked, not trusted: if the vendor has gained other filaments since (the user could
    have filed more under it before clicking Undo), deleting it would silently unlink them, and undo
    must restore the previous state rather than go further than it. Returns None in that case.

    Never raises. The filament delete has already committed by the time this runs, so a failure here
    would otherwise turn a successful undo into an error about something the user cannot act on; a
    leftover vendor row is the strictly better failure. Logged so it is not invisible.
    """
    try:
        vendor = await vendor_db.get_by_id(ctx.db, vendor_id)
    except ItemNotFoundError:
        return None  # Already gone (a double-undo, or deleted elsewhere) -- nothing to do.
    name = vendor.name
    filament_count, _spool_count = (await vendor_db.get_aggregates(ctx.db, [vendor_id])).get(vendor_id, (0, 0))
    if filament_count:
        return None
    try:
        await vendor_db.delete(ctx.db, vendor_id)
    except Exception:  # Best-effort: the filament delete already committed and must stand.
        logger.exception("Failed to delete vendor %s alongside the filament whose creation added it.", vendor_id)
        return None
    return name


async def _execute_delete_filament(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    filament_id = arg_int(args, "filament_id")
    await _get_filament(ctx, filament_id)
    if arg_bool(args, "only_if_empty"):
        # Set only by create_filament's own undo descriptor (never by the model -- this argument
        # is deliberately absent from the tool's JSON schema). /ai/chat/action reaches execute()
        # directly with no preview and no confirm-card, so this is the only guard standing between
        # "Undo" on a creation card and a silent cascading delete of every spool added since.
        spool_count = await filament_db.count_spools(ctx.db, filament_id)
        if spool_count:
            raise ToolError(
                f"Cannot undo: filament {filament_id} now has {spool_count} spool(s) that would be "
                "permanently destroyed, including their usage history. Delete it explicitly (not "
                "via Undo) if that is really what you want.",
            )
    # Read before the delete so a junk value is a ToolError *before* anything is destroyed, and
    # absent/None means "no vendor to take back" -- fail-safe in the same direction as only_if_empty.
    vendor_to_delete = args.get("also_delete_vendor_id")
    if vendor_to_delete is not None:
        vendor_to_delete = arg_int(args, "also_delete_vendor_id")
    try:
        await filament_db.delete(ctx.db, filament_id)
    except ItemDeleteError as exc:
        raise ToolError(str(exc)) from exc
    summary = f"Deleted filament #{filament_id}."
    data = {"filament_id": filament_id}
    if vendor_to_delete is not None:
        deleted_vendor = await _delete_vendor_created_with_the_filament(ctx, vendor_to_delete)
        if deleted_vendor is not None:
            summary = f"{summary} Also deleted the vendor '{deleted_vendor}'."
            data["deleted_vendor_id"] = vendor_to_delete
    return ExecutionResult(summary=summary, data=data, undo=None)


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
                "color_hex": {"type": "string", "description": "6-digit hex without '#' (8 with an alpha channel)."},
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
    "update_filament": WriteTool(
        name="update_filament",
        description=(
            "Update fields of an existing filament type. Omit any field you don't want to change; pass "
            "null only to clear that field (density and diameter are the exception: they cannot be "
            "null, so give a real number or omit them). Requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filament_id": {"type": "integer", "description": "The filament to update."},
                "name": {"type": "string", "description": "Product name, e.g. 'PLA Meta'."},
                "material": {"type": "string", "description": "e.g. PLA, PETG, ASA."},
                "density": {"type": "number", "description": "g/cm3."},
                "diameter": {"type": "number", "description": "mm, e.g. 1.75."},
                "weight_g": {"type": "number", "description": "Net filament weight of a full spool."},
                "spool_weight_g": {"type": "number", "description": "Weight of the empty spool."},
                "color_hex": {"type": "string", "description": "6-digit hex without '#' (8 with an alpha channel)."},
                "price": {"type": "number"},
                "extruder_temp": {"type": "integer"},
                "bed_temp": {"type": "integer"},
                "article_number": {"type": "string"},
                "low_stock_threshold_g": {"type": "number"},
                "comment": {"type": "string"},
            },
            "required": ["filament_id"],
        },
        preview=_preview_update_filament,
        execute=_execute_update_filament,
    ),
    "delete_filament": WriteTool(
        name="delete_filament",
        description=(
            "Permanently delete a filament type and all its spools, including usage history. "
            "Destructive and cannot be undone. Refused while any order references it. Only do this "
            "when clearly asked. Requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {"filament_id": {"type": "integer"}},
            "required": ["filament_id"],
        },
        preview=_preview_delete_filament,
        execute=_execute_delete_filament,
        destructive=True,
    ),
}
