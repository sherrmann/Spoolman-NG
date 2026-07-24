"""The curated agent tool layer (#362).

One tool surface, meant for two consumers: the in-app chat agent (spoolman.aichat)
today, and the MCP server (#360) when it lands. Each tool is a thin, *curated* wrapper
over the same database functions the REST API uses — never raw SQL, never a field the
UI wouldn't let a user touch — so the agent can only do things a person could do in the
web client.

The layer draws a hard line between **read tools** (always offered) and **write tools**
(offered only to a principal that may write — an admin, or the anonymous admin of a
no-auth install). A read-only caller is handed the read tools alone and literally has no
vocabulary for a mutation: the model cannot call what it was never given. Writes are
further gated at execution time by :class:`ToolContext.can_write`, so a forged tool call
can't slip a mutation through either.

Write tools separate *preview* from *execute*: the chat loop previews a mutation into a
confirm-card (before/after values) and only executes after the user confirms, and each
executed write returns an ``undo`` descriptor — another curated tool call that reverses
it — so the UI can offer a one-click undo. Deletes are the honest exception: they report
``destructive=True`` and carry no undo.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import filament as filament_db
from spoolman.database import models
from spoolman.database import spool as spool_db
from spoolman.database.utils import SortOrder
from spoolman.exceptions import ItemCreateError, ItemNotFoundError
from spoolman.settings import SETTINGS

logger = logging.getLogger(__name__)

#: Bounds on how much a single read tool may return, so a chatty query can't pull the
#: whole database into the model's context (or the response).
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100

#: Colour-similarity threshold used when a query filters spools by colour, matching the
#: spool list's default (spoolman/api/v1/spool.py).
_COLOR_SIMILARITY_THRESHOLD = 20.0


class ToolError(Exception):
    """A tool could not run; the message is safe to show the user and feed back to the model."""


# --- Argument coercion -------------------------------------------------------------
#
# Tool arguments arrive from a language model, so they are untrusted in shape as well as
# in value: a required key can be missing, a number can arrive as "12" or as "the black
# one", and a small local model will do both. Every coercion below raises ToolError, which
# callers already feed back to the model so it can correct itself — a bare int()/args[key]
# would raise ValueError/KeyError instead and abort the whole turn.


def _arg_int(args: dict, key: str, *, default: int | None = None) -> int:
    """Coerce args[key] to an int. Missing/blank falls back to default, or errors if none."""
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is not None:
            return default
        raise ToolError(f"The '{key}' argument is required.")
    if isinstance(value, bool):
        raise ToolError(f"The '{key}' argument must be a number.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"The '{key}' argument must be a number, got {value!r}.") from exc


def _arg_float(args: dict, key: str) -> float:
    """Coerce a required args[key] to a float, erroring with a model-readable message."""
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(f"The '{key}' argument is required.")
    if isinstance(value, bool):
        raise ToolError(f"The '{key}' argument must be a number.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"The '{key}' argument must be a number, got {value!r}.") from exc


def _optional_float(args: dict, key: str) -> float | None:
    """Coerce an optional args[key] to a float; absent stays absent, junk still errors."""
    if args.get(key) is None:
        return None
    return _arg_float(args, key)


def _arg_limit(args: dict) -> int:
    """Coerce the shared 'limit' argument into the [1, _MAX_LIMIT] band."""
    return min(max(_arg_int(args, "limit", default=_DEFAULT_LIMIT), 1), _MAX_LIMIT)


def _arg_bool(args: dict, key: str, *, default: bool = False) -> bool:
    """Coerce args[key] to a bool, accepting the JSON-ish strings models like to emit."""
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0", ""):
            return False
    raise ToolError(f"The '{key}' argument must be true or false, got {value!r}.")


@dataclass
class ToolContext:
    """Everything a tool needs to run: a DB session and whether writes are permitted."""

    db: AsyncSession
    can_write: bool


@dataclass
class ConfirmCard:
    """The before/after preview of a pending mutation, rendered as a confirm-card."""

    tool: str
    title: str
    summary: str
    before: dict
    after: dict
    destructive: bool = False


@dataclass
class ExecutionResult:
    """The outcome of an executed write: a human summary, structured data, and an optional undo."""

    summary: str
    data: dict = field(default_factory=dict)
    #: A curated ``{"tool": name, "args": {...}}`` call that reverses this one, or None
    #: when the change cannot be cleanly undone (deletes).
    undo: dict | None = None


@dataclass
class ReadTool:
    """A non-mutating tool. Always offered, to every principal."""

    name: str
    description: str
    parameters: dict
    run: Callable[[ToolContext, dict], Awaitable[dict]]
    mutating: bool = False


@dataclass
class WriteTool:
    """A mutating tool. Offered only to a principal that may write; previews before executing."""

    name: str
    description: str
    parameters: dict
    preview: Callable[[ToolContext, dict], Awaitable[ConfirmCard]]
    execute: Callable[[ToolContext, dict], Awaitable[ExecutionResult]]
    mutating: bool = True


# --- Shared helpers ----------------------------------------------------------------


def _combined_name(spool: models.Spool) -> str:
    """Human name for a spool's filament: 'Vendor - Name', tolerant of missing pieces."""
    fil = spool.filament
    if fil is None:
        return f"Spool #{spool.id}"
    vendor = fil.vendor.name if fil.vendor is not None else None
    parts = [part for part in (vendor, fil.name) if part]
    return " - ".join(parts) if parts else (fil.material or f"Filament #{fil.id}")


def _initial_weight(spool: models.Spool) -> float | None:
    """Return the spool's initial net weight, falling back to the filament's nominal weight."""
    if spool.initial_weight is not None:
        return spool.initial_weight
    if spool.filament is not None:
        return spool.filament.weight
    return None


def _remaining_weight(spool: models.Spool) -> float | None:
    """Remaining net weight, computed exactly as the API model does (never negative)."""
    initial = _initial_weight(spool)
    if initial is None:
        return None
    return round(max(initial - spool.used_weight, 0.0), 1)


def _spool_brief(spool: models.Spool) -> dict:
    """Build a compact, model-friendly view of a spool (no nested objects, no nulls of note)."""
    fil = spool.filament
    return {
        "id": spool.id,
        "filament": _combined_name(spool),
        "material": fil.material if fil is not None else None,
        "color_hex": fil.color_hex if fil is not None else None,
        "remaining_weight_g": _remaining_weight(spool),
        "location": spool.location,
        "lot_nr": spool.lot_nr,
        "archived": bool(spool.archived),
    }


async def _get_spool(ctx: ToolContext, spool_id: int) -> models.Spool:
    try:
        return await spool_db.get_by_id(ctx.db, spool_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No spool with ID {spool_id} exists.") from exc


def _require_write(ctx: ToolContext) -> None:
    if not ctx.can_write:
        raise ToolError("This account is read-only and cannot make changes.")


async def _low_stock_fallback_g(db: AsyncSession) -> float:
    """Return the global fallback low-stock threshold (grams) for filaments without their own."""
    definition = SETTINGS["low_stock_fallback_g"]
    row = await db.get(models.Setting, "low_stock_fallback_g")
    raw = row.value if row is not None else definition.default
    try:
        return float(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 200.0


# --- Read tools --------------------------------------------------------------------


async def _run_find_spools(ctx: ToolContext, args: dict) -> dict:
    """Search spools by the same fields the spool list exposes; sum their remaining weight."""
    limit = _arg_limit(args)
    include_archived = _arg_bool(args, "include_archived")

    filament_ids: list[int] | None = None
    color_hex = args.get("color_hex")
    if isinstance(color_hex, str) and color_hex.strip():
        matched = await filament_db.find_by_color(
            db=ctx.db,
            color_query_hex=color_hex.strip().lstrip("#"),
            similarity_threshold=_COLOR_SIMILARITY_THRESHOLD,
        )
        filament_ids = [fil.id for fil in matched]
        if not filament_ids:
            # A colour with no matching filament means no spools — short-circuit before querying.
            return {"count": 0, "returned": 0, "total_remaining_weight_g": 0.0, "spools": [], "filters": _echo(args)}

    items, total = await spool_db.find(
        db=ctx.db,
        search=_clean(args.get("query")),
        filament_id=filament_ids,
        filament_material=_clean(args.get("material")),
        vendor_name=_clean(args.get("vendor")),
        location=_clean(args.get("location")),
        lot_nr=_clean(args.get("lot_nr")),
        allow_archived=include_archived,
        sort_by={"remaining_weight": SortOrder.DESC},
        limit=limit,
    )
    briefs = [_spool_brief(item) for item in items]
    total_remaining = round(sum(b["remaining_weight_g"] or 0.0 for b in briefs), 1)
    return {
        "count": total,
        "returned": len(briefs),
        "total_remaining_weight_g": total_remaining,
        "spools": briefs,
        "filters": _echo(args),
    }


async def _run_find_filaments(ctx: ToolContext, args: dict) -> dict:
    """List filaments with rolled-up remaining weight, low-stock status, and on-order signal."""
    limit = _arg_limit(args)
    low_stock_only = _arg_bool(args, "low_stock_only")

    items, _ = await filament_db.find(
        db=ctx.db,
        search=_clean(args.get("query")),
        material=_clean(args.get("material")),
        vendor_name=_clean(args.get("vendor")),
        limit=None if low_stock_only else limit,
    )
    ids = [item.id for item in items]
    aggregates = await filament_db.get_aggregates(ctx.db, ids)
    on_order = await filament_db.get_on_order(ctx.db, ids)
    fallback = await _low_stock_fallback_g(ctx.db)

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


def _clean(value: object) -> str | None:
    """Normalise a tool argument to a non-empty stripped string, or None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _echo(args: dict) -> dict:
    """Return the subset of spool filters that were actually set, for the client's deep-link."""
    keys = ("material", "vendor", "location", "lot_nr", "color_hex", "query")
    echoed = {key: _clean(args.get(key)) for key in keys}
    echoed = {key: value for key, value in echoed.items() if value is not None}
    if args.get("include_archived"):
        echoed["include_archived"] = True
    return echoed


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
        changes["price"] = _arg_float(args, "price")
    if "archived" in changes:
        changes["archived"] = _arg_bool(args, "archived")
    return changes


async def _preview_update_spool(ctx: ToolContext, args: dict) -> ConfirmCard:
    spool = await _get_spool(ctx, _arg_int(args, "spool_id"))
    before = _spool_update_view(spool)
    changes = _requested_changes(args)
    if not changes:
        raise ToolError("No changes were provided to update.")
    after = {**before, **changes}
    summary = ", ".join(f"{key}: {before[key]!r} -> {after[key]!r}" for key in changes)
    return ConfirmCard(
        tool="update_spool",
        title=f"Update spool #{spool.id} ({_combined_name(spool)})",
        summary=summary,
        before={key: before[key] for key in changes},
        after={key: after[key] for key in changes},
    )


async def _execute_update_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    _require_write(ctx)
    spool_id = _arg_int(args, "spool_id")
    spool = await _get_spool(ctx, spool_id)
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
    spool = await _get_spool(ctx, _arg_int(args, "spool_id"))
    delta = _arg_float(args, "use_weight_g")
    remaining = _remaining_weight(spool)
    after_remaining = None if remaining is None else round(max(remaining - delta, 0.0), 1)
    verb = "Consume" if delta >= 0 else "Add back"
    return ConfirmCard(
        tool="consume_spool",
        title=f"{verb} {abs(delta):g} g on spool #{spool.id} ({_combined_name(spool)})",
        summary=f"remaining_weight_g: {remaining!r} -> {after_remaining!r}",
        before={"remaining_weight_g": remaining},
        after={"remaining_weight_g": after_remaining},
    )


async def _execute_consume_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    _require_write(ctx)
    spool_id = _arg_int(args, "spool_id")
    delta = _arg_float(args, "use_weight_g")
    spool = await _get_spool(ctx, spool_id)
    used_before = spool.used_weight
    new_used = max(used_before + delta, 0.0)
    initial = _initial_weight(spool)
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
    spool = await _get_spool(ctx, _arg_int(args, "spool_id"))
    return ConfirmCard(
        tool="set_spool_used_weight",
        title=f"Restore usage on spool #{spool.id}",
        summary=f"used_weight_g -> {_arg_float(args, 'used_weight_g'):g}",
        before={"used_weight_g": round(spool.used_weight, 1)},
        after={"used_weight_g": _arg_float(args, "used_weight_g")},
    )


async def _execute_set_used_weight(ctx: ToolContext, args: dict) -> ExecutionResult:
    _require_write(ctx)
    spool_id = _arg_int(args, "spool_id")
    spool = await _get_spool(ctx, spool_id)
    used_before = spool.used_weight
    new_used = max(_arg_float(args, "used_weight_g"), 0.0)
    await spool_db.update(db=ctx.db, spool_id=spool_id, data={"used_weight": new_used})
    return ExecutionResult(
        summary=f"Set spool #{spool_id} used weight to {new_used:g} g.",
        data={"spool_id": spool_id, "used_weight_g": round(new_used, 1)},
        undo={"tool": "set_spool_used_weight", "args": {"spool_id": spool_id, "used_weight_g": round(used_before, 1)}},
    )


async def _preview_create_spool(ctx: ToolContext, args: dict) -> ConfirmCard:
    filament_id = _arg_int(args, "filament_id")
    try:
        fil = await filament_db.get_by_id(ctx.db, filament_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No filament with ID {filament_id} exists.") from exc
    after = {
        "filament": " - ".join(p for p in (fil.vendor.name if fil.vendor else None, fil.name) if p) or fil.material,
        "location": _clean(args.get("location")),
        "lot_nr": _clean(args.get("lot_nr")),
        "initial_weight_g": _optional_float(args, "initial_weight_g"),
        "price": _optional_float(args, "price"),
    }
    return ConfirmCard(
        tool="create_spool",
        title=f"Create a new spool of {after['filament']}",
        summary=", ".join(f"{key}: {value!r}" for key, value in after.items() if value is not None),
        before={},
        after={key: value for key, value in after.items() if value is not None},
    )


async def _execute_create_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    _require_write(ctx)
    filament_id = _arg_int(args, "filament_id")
    try:
        created = await spool_db.create(
            db=ctx.db,
            filament_id=filament_id,
            location=_clean(args.get("location")),
            lot_nr=_clean(args.get("lot_nr")),
            initial_weight=_optional_float(args, "initial_weight_g"),
            price=_optional_float(args, "price"),
        )
    except (ItemNotFoundError, ItemCreateError) as exc:
        raise ToolError(str(exc)) from exc
    return ExecutionResult(
        summary=f"Created spool #{created.id}.",
        data={"spool_id": created.id},
        undo={"tool": "delete_spool", "args": {"spool_id": created.id}},
    )


async def _preview_delete_spool(ctx: ToolContext, args: dict) -> ConfirmCard:
    spool = await _get_spool(ctx, _arg_int(args, "spool_id"))
    return ConfirmCard(
        tool="delete_spool",
        title=f"Delete spool #{spool.id} ({_combined_name(spool)})",
        summary="This permanently deletes the spool and its usage history. It cannot be undone.",
        before=_spool_brief(spool),
        after={},
        destructive=True,
    )


async def _execute_delete_spool(ctx: ToolContext, args: dict) -> ExecutionResult:
    _require_write(ctx)
    spool_id = _arg_int(args, "spool_id")
    await _get_spool(ctx, spool_id)  # 404s as a clean ToolError before deleting
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
                "limit": {"type": "integer", "description": f"Max spools to return (default {_DEFAULT_LIMIT})."},
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
                "limit": {"type": "integer", "description": f"Max filaments to return (default {_DEFAULT_LIMIT})."},
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

#: Write tools the model is actually told about. set_spool_used_weight is deliberately
#: excluded — it is an undo-only primitive, not something the agent should reach for.
_MODEL_WRITE_TOOLS = ("update_spool", "consume_spool", "create_spool", "delete_spool")


def is_write_tool(name: str) -> bool:
    """Whether a tool name refers to a mutating tool."""
    return name in WRITE_TOOLS


def get_tool(name: str) -> ReadTool | WriteTool | None:
    """Look a tool up by name across both registries, or None if unknown."""
    return READ_TOOLS.get(name) or WRITE_TOOLS.get(name)


def _openai_schema(tool: ReadTool | WriteTool) -> dict:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
    }


def tool_schemas(*, can_write: bool) -> list[dict]:
    """Return the OpenAI ``tools`` array offered to the model for this principal.

    Read tools always; the model-facing write tools only when the principal may write. A
    read-only caller therefore never even sees a mutation exists.
    """
    schemas = [_openai_schema(tool) for tool in READ_TOOLS.values()]
    if can_write:
        schemas.extend(_openai_schema(WRITE_TOOLS[name]) for name in _MODEL_WRITE_TOOLS)
    return schemas
