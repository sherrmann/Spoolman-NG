"""Shared primitives for the curated agent tool layer (#362).

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import models
from spoolman.database import spool as spool_db
from spoolman.exceptions import ItemNotFoundError
from spoolman.settings import SETTINGS

#: Bounds on how much a single read tool may return, so a chatty query can't pull the
#: whole database into the model's context (or the response).
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

#: Colour-similarity threshold used when a query filters spools by colour, matching the
#: spool list's default (spoolman/api/v1/spool.py).
COLOR_SIMILARITY_THRESHOLD = 20.0


class ToolError(Exception):
    """A tool could not run; the message is safe to show the user and feed back to the model."""


# --- Argument coercion -------------------------------------------------------------
#
# Tool arguments arrive from a language model, so they are untrusted in shape as well as
# in value: a required key can be missing, a number can arrive as "12" or as "the black
# one", and a small local model will do both. Every coercion below raises ToolError, which
# callers already feed back to the model so it can correct itself — a bare int()/args[key]
# would raise ValueError/KeyError instead and abort the whole turn.


def arg_int(args: dict, key: str, *, default: int | None = None) -> int:
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


def arg_float(args: dict, key: str) -> float:
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


def optional_float(args: dict, key: str) -> float | None:
    """Coerce an optional args[key] to a float; absent stays absent, junk still errors."""
    if args.get(key) is None:
        return None
    return arg_float(args, key)


def arg_limit(args: dict) -> int:
    """Coerce the shared 'limit' argument into the [1, MAX_LIMIT] band."""
    return min(max(arg_int(args, "limit", default=DEFAULT_LIMIT), 1), MAX_LIMIT)


def arg_bool(args: dict, key: str, *, default: bool = False) -> bool:
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
    #: False for undo-only primitives (set_spool_used_weight, delete_location, delete_vendor,
    #: delete_filament_and_vendor): they exist so a create can be reversed, but the model must
    #: never reach for them. Hiding a tool is only safe when the model has no *request* it
    #: answers -- delete_order was hidden and the model substituted delete_spool for "delete the
    #: order", so it is model-facing now (see orders.py).
    model_facing: bool = True
    #: This tool's confirm-card is always destructive and it carries no undo. Set on every
    #: delete plus arrive_order (the one non-delete write with no undo). MCP has no confirm-card
    #: of its own, so this is what its destructiveHint annotation reports to the client.
    destructive: bool = False


# --- Shared helpers ----------------------------------------------------------------


def combined_name(spool: models.Spool) -> str:
    """Human name for a spool's filament: 'Vendor - Name', tolerant of missing pieces."""
    fil = spool.filament
    if fil is None:
        return f"Spool #{spool.id}"
    vendor = fil.vendor.name if fil.vendor is not None else None
    parts = [part for part in (vendor, fil.name) if part]
    return " - ".join(parts) if parts else (fil.material or f"Filament #{fil.id}")


def initial_weight(spool: models.Spool) -> float | None:
    """Return the spool's initial net weight, falling back to the filament's nominal weight."""
    if spool.initial_weight is not None:
        return spool.initial_weight
    if spool.filament is not None:
        return spool.filament.weight
    return None


def remaining_weight(spool: models.Spool) -> float | None:
    """Remaining net weight, computed exactly as the API model does (never negative)."""
    initial = initial_weight(spool)
    if initial is None:
        return None
    return round(max(initial - spool.used_weight, 0.0), 1)


def spool_brief(spool: models.Spool) -> dict:
    """Build a compact, model-friendly view of a spool (no nested objects, no nulls of note)."""
    fil = spool.filament
    return {
        "id": spool.id,
        "filament": combined_name(spool),
        "material": fil.material if fil is not None else None,
        "color_hex": fil.color_hex if fil is not None else None,
        "remaining_weight_g": remaining_weight(spool),
        "location": spool.location,
        "lot_nr": spool.lot_nr,
        "archived": bool(spool.archived),
    }


async def get_spool(ctx: ToolContext, spool_id: int) -> models.Spool:
    """Fetch a spool by ID, or raise a model-facing ToolError if it doesn't exist."""
    try:
        return await spool_db.get_by_id(ctx.db, spool_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No spool with ID {spool_id} exists.") from exc


def require_write(ctx: ToolContext) -> None:
    """Raise a ToolError if this context's principal may not write."""
    if not ctx.can_write:
        raise ToolError("This account is read-only and cannot make changes.")


async def low_stock_fallback_g(db: AsyncSession) -> float:
    """Return the global fallback low-stock threshold (grams) for filaments without their own."""
    definition = SETTINGS["low_stock_fallback_g"]
    row = await db.get(models.Setting, "low_stock_fallback_g")
    raw = row.value if row is not None else definition.default
    try:
        return float(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 200.0


def clean_str(value: object) -> str | None:
    """Normalise a tool argument to a non-empty stripped string, or None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def echo_spool_filters(args: dict) -> dict:
    """Return the subset of spool filters that were actually set, for the client's deep-link."""
    keys = ("material", "vendor", "location", "lot_nr", "color_hex", "query")
    echoed = {key: clean_str(args.get(key)) for key in keys}
    echoed = {key: value for key, value in echoed.items() if value is not None}
    if args.get("include_archived"):
        echoed["include_archived"] = True
    return echoed
