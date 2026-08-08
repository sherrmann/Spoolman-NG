"""Order tools: what is on the way, and turning an arrival into spools.

An order links to a Shop (not a Vendor), and its open/arrived state is DERIVED from its lines'
``arrived_at`` rather than stored — so status filtering happens here, over the rows the
database layer returns, because ``order.find`` filters only by shop.
"""

from datetime import datetime

from spoolman.ai_tools.base import (
    ConfirmCard,
    ExecutionResult,
    ReadTool,
    ToolContext,
    ToolError,
    WriteTool,
    arg_bool,
    arg_int,
    arg_limit,
    clean_str,
    optional_float,
    require_write,
)
from spoolman.ai_tools.stats import parse_date
from spoolman.database import filament as filament_db
from spoolman.database import location as location_db
from spoolman.database import order as order_db
from spoolman.database import shop as shop_db
from spoolman.exceptions import ItemNotFoundError

_STATUSES = ("open", "arrived", "all")


def parse_status(args: dict) -> str:
    """Coerce the 'status' argument to one of open/arrived/all, defaulting to open."""
    raw = args.get("status")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "open"
    value = str(raw).strip().lower()
    if value not in _STATUSES:
        raise ToolError(f"The 'status' argument must be open, arrived or all, got {raw!r}.")
    return value


def is_open(order: object) -> bool:
    """Whether any line is still outstanding. Order state is derived, never stored."""
    return any(line.arrived_at is None for line in order.lines)


def _line_row(line: object) -> dict:
    """Shape one order line, with its filament resolved to a 'Vendor - Name' label for the model."""
    filament = line.filament
    vendor = filament.vendor.name if filament is not None and filament.vendor is not None else None
    name = " - ".join(part for part in (vendor, filament.name if filament else None) if part)
    return {
        "line_id": line.id,
        "filament_id": line.filament_id,
        "filament": name or (filament.material if filament is not None else None),
        "quantity": line.quantity,
        "price_per_unit": line.price_per_unit,
        "arrived": line.arrived_at is not None,
    }


def _describe_line_row(line: dict) -> str:
    """Render one ``_line_row`` dict as the human line a confirm-card shows, e.g. '2 x Acme - PLA'."""
    name = line["filament"] or f"filament #{line['filament_id']}"
    return f"{line['quantity']} x {name}"


def order_row(order: object) -> dict:
    """Shape one order plus its derived status and outstanding unit count."""
    lines = [_line_row(line) for line in order.lines]
    return {
        "id": order.id,
        "shop": order.shop.name if order.shop is not None else None,
        "order_number": order.order_number,
        "ordered_at": order.ordered_at.isoformat() if order.ordered_at is not None else None,
        "status": "open" if is_open(order) else "arrived",
        "outstanding_units": sum(line.quantity for line in order.lines if line.arrived_at is None),
        "lines": lines,
    }


def _format_order_date(value: datetime | None) -> str | None:
    """Format an order date for a confirm-card: a bare date at midnight, else date and time.

    A confirm-card is read by a person deciding whether to click confirm, not machine-parsed --
    a raw ISO-8601 datetime like ``2026-01-15T00:00:00`` reads like a database dump, not a date
    someone placed an order on. An order date is date-granular in practice, so the midnight
    ``parse_date`` produces for a bare date like "2026-01-15" collapses to just the date; a real
    time component is kept, human-readable, rather than silently dropped. This is display-only --
    every write still passes ``parse_date``'s own ``datetime`` to the database layer, never this
    string, so ``create``/``arrive`` are untouched by this formatting.
    """
    if value is None:
        return None
    if value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0:
        return value.strftime("%Y-%m-%d")
    return value.strftime("%Y-%m-%d %H:%M")


async def _resolve_shop_id(ctx: ToolContext, name: str | None) -> tuple[int | None, str | None]:
    """Resolve a shop name to (id, canonical name), raising if it doesn't match any shop.

    Returning the canonical name too lets a confirm-card state the shop that will actually be
    used -- a user typing 'prusa' must see 'Prusa Research', the name the order actually links to,
    not an echo of whatever casing they happened to type (mirrors _resolve_location_id, below).
    """
    if name is None:
        return None, None
    items, _ = await shop_db.find(db=ctx.db, name=name)
    lowered = name.strip().lower()
    match = next((item for item in items if (item.name or "").strip().lower() == lowered), None)
    if match is None:
        raise ToolError(f"No shop named '{name}' exists.")
    return match.id, match.name


async def _run_find_orders(ctx: ToolContext, args: dict) -> dict:
    """List orders with their derived status and outstanding units."""
    limit = arg_limit(args)
    status = parse_status(args)
    shop_id, _resolved_shop = await _resolve_shop_id(ctx, clean_str(args.get("shop")))
    from_date, to_date = parse_date(args, "from_date"), parse_date(args, "to_date")

    # Status and date are post-filters (order.find only knows shop_id), so fetch unlimited and
    # window afterwards — the same shape find_filaments uses for low_stock_only.
    items, _total = await order_db.find(db=ctx.db, shop_id=shop_id, limit=None)
    rows = []
    for item in items:
        if status != "all" and (status == "open") != is_open(item):
            continue
        if from_date is not None and item.ordered_at is not None and item.ordered_at < from_date:
            continue
        if to_date is not None and item.ordered_at is not None and item.ordered_at >= to_date:
            continue
        rows.append(order_row(item))
    rows.sort(key=lambda row: row["ordered_at"] or "", reverse=True)
    return {"count": len(rows), "returned": min(len(rows), limit), "orders": rows[:limit]}


READ_TOOLS: dict[str, ReadTool] = {
    "find_orders": ReadTool(
        name="find_orders",
        description=(
            "List the user's filament orders with their lines, derived status (open while any line "
            "is outstanding) and outstanding unit count. Use for 'what is on order', 'did my order "
            "arrive', and to find the order_id before marking an arrival."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "arrived", "all"],
                    "description": "Default open.",
                },
                "shop": {"type": "string", "description": "Filter by shop name."},
                "from_date": {"type": "string", "description": "Only orders placed at or after this ISO date."},
                "to_date": {"type": "string", "description": "Only orders placed before this ISO date."},
                "limit": {"type": "integer", "description": "Max orders to return (default 25)."},
            },
        },
        run=_run_find_orders,
    ),
}

# --- Write tools -------------------------------------------------------------------


def parse_lines(args: dict) -> list[dict]:
    """Coerce the 'lines' argument into order-line dicts.

    This is the hardest argument shape in the tool set for a small model to fill: a list of
    objects. Every failure mode gets a message the model can act on, because the alternative is
    a lost turn.
    """
    raw = args.get("lines")
    if not isinstance(raw, list) or not raw:
        raise ToolError("The 'lines' argument must be a non-empty list of {filament_id, quantity} objects.")
    parsed = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ToolError(f"Line {index + 1} of 'lines' must be an object with a filament_id.")
        # arg_int/optional_float have no notion of "which line" -- they're shared by every tool
        # in the layer -- so a bad filament_id or quantity here raises a ToolError with no line
        # context. Re-raise with the index prefixed, or a model mid-multi-line-order gets e.g.
        # "the 'filament_id' argument is required" with no way to tell which of its lines to fix.
        try:
            filament_id = arg_int(entry, "filament_id")
            quantity = arg_int(entry, "quantity", default=1)
            price_per_unit = optional_float(entry, "price_per_unit")
        except ToolError as exc:
            raise ToolError(f"Line {index + 1}: {exc}") from exc
        if quantity < 1:
            raise ToolError(f"Line {index + 1}: 'quantity' must be at least 1, got {quantity}.")
        parsed.append({"filament_id": filament_id, "quantity": quantity, "price_per_unit": price_per_unit})
    return parsed


async def _describe_lines(ctx: ToolContext, lines: list[dict]) -> list[str]:
    """Human line descriptions for a confirm-card, validating each filament exists."""
    described = []
    for line in lines:
        try:
            filament = await filament_db.get_by_id(ctx.db, line["filament_id"])
        except ItemNotFoundError as exc:
            raise ToolError(f"No filament with ID {line['filament_id']} exists.") from exc
        vendor = filament.vendor.name if filament.vendor is not None else None
        name = " - ".join(part for part in (vendor, filament.name) if part) or filament.material
        described.append(f"{line['quantity']} x {name}")
    return described


async def _preview_create_order(ctx: ToolContext, args: dict) -> ConfirmCard:
    lines = parse_lines(args)
    described = await _describe_lines(ctx, lines)
    shop = clean_str(args.get("shop"))
    # Resolve everything execute() would need up front: a shop name that doesn't exist or an
    # unparseable ordered_at must fail HERE, before the user ever confirms a card that then blows
    # up -- the same guarantee arrive_order's preview already gives, and create_vendor's duplicate
    # check. _shop_id is discarded; it's resolved again in execute (matching arrive_order's own
    # _resolve_location_id pattern), this call exists purely to validate and to get the canonical
    # name for the card below.
    _shop_id, resolved_shop = await _resolve_shop_id(ctx, shop)
    ordered_at = parse_date(args, "ordered_at")
    after = {
        "shop": resolved_shop,
        "order_number": clean_str(args.get("order_number")),
        "ordered_at": _format_order_date(ordered_at),
        "lines": described,
        "units": sum(line["quantity"] for line in lines),
    }
    return ConfirmCard(
        tool="create_order",
        title=f"Create an order of {after['units']} spool(s)" + (f" from {resolved_shop}" if resolved_shop else ""),
        summary="; ".join(described),
        before={},
        after={key: value for key, value in after.items() if value is not None},
    )


async def _execute_create_order(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    lines = parse_lines(args)
    await _describe_lines(ctx, lines)
    shop_id, _resolved_shop = await _resolve_shop_id(ctx, clean_str(args.get("shop")))
    created = await order_db.create(
        db=ctx.db,
        shop_id=shop_id,
        ordered_at=parse_date(args, "ordered_at"),
        order_number=clean_str(args.get("order_number")),
        comment=clean_str(args.get("comment")),
        lines=lines,
    )
    return ExecutionResult(
        summary=f"Created order #{created.id} with {len(lines)} line(s).",
        data={"order_id": created.id},
        undo={"tool": "delete_order", "args": {"order_id": created.id}},
    )


async def _preview_delete_order(ctx: ToolContext, args: dict) -> ConfirmCard:
    order_id = arg_int(args, "order_id")
    try:
        item = await order_db.get_by_id(ctx.db, order_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No order with ID {order_id} exists.") from exc
    # order_row's ordered_at is the raw ISO string find_orders sorts by (see _run_find_orders) --
    # reformat it for this card the same way _preview_create_order's does, via the shared helper,
    # rather than changing order_row itself and breaking that sort.
    before = order_row(item)
    before["ordered_at"] = _format_order_date(item.ordered_at)
    # order_row's lines are dicts, shaped for the model; the confirm-card is rendered by a person
    # (chatDrawer renders each value with String(value), which turns a list of dicts into
    # "[object Object],[object Object]"). Same one-line-per-line wording create_order's card uses.
    before["lines"] = [_describe_line_row(line) for line in before["lines"]]
    return ConfirmCard(
        tool="delete_order",
        title=f"Delete order #{order_id}",
        summary="The order and its lines are removed. Spools already created from it are kept.",
        before=before,
        after={},
        destructive=True,
    )


async def _execute_delete_order(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    order_id = arg_int(args, "order_id")
    try:
        await order_db.get_by_id(ctx.db, order_id)  # 404s as a clean ToolError before deleting
    except ItemNotFoundError as exc:
        raise ToolError(f"No order with ID {order_id} exists.") from exc
    await order_db.delete(ctx.db, order_id)
    return ExecutionResult(summary=f"Deleted order #{order_id}.", data={"order_id": order_id}, undo=None)


async def _resolve_location_id(ctx: ToolContext, name: str | None) -> tuple[int | None, str | None]:
    """Resolve a location name to its (id, canonical name), raising if the name doesn't match.

    Returning the canonical name too lets the confirm-card state what will actually happen --
    a user typing 'shelf b' must see 'Shelf B', the name the spools are actually filed under,
    not an echo of whatever casing they happened to type.
    """
    if name is None:
        return None, None
    items, _ = await location_db.find(db=ctx.db, name=name)
    lowered = name.strip().lower()
    match = next((item for item in items if (item.name or "").strip().lower() == lowered), None)
    if match is None:
        raise ToolError(f"No location named '{name}' exists. Create it first or omit the location.")
    return match.id, match.name


async def _preview_arrive_order(ctx: ToolContext, args: dict) -> ConfirmCard:
    """Build the confirm-card for marking an order's outstanding lines arrived.

    Everything that would make ``execute`` fail is checked here first -- a non-existent order,
    an order with nothing outstanding, or a named location that doesn't exist -- because this
    write has no undo: the card is the user's only chance to catch a mistake before it happens.
    """
    order_id = arg_int(args, "order_id")
    try:
        item = await order_db.get_by_id(ctx.db, order_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No order with ID {order_id} exists.") from exc
    outstanding = [line for line in item.lines if line.arrived_at is None]
    if not outstanding:
        raise ToolError(f"Order #{order_id} has no outstanding lines; it already arrived.")

    create_spools = arg_bool(args, "create_spools", default=True)
    location = clean_str(args.get("location"))
    # Fail before the user confirms, not after -- and use the resolved canonical name in the
    # summary below, not the user's raw casing/spacing, since that's where the spools actually land.
    _location_id, resolved_location = await _resolve_location_id(ctx, location)
    units = sum(line.quantity for line in outstanding)
    described = await _describe_lines(
        ctx,
        [{"filament_id": line.filament_id, "quantity": line.quantity} for line in outstanding],
    )
    summary = f"Marks {len(outstanding)} line(s) arrived: " + "; ".join(described) + "."
    if create_spools:
        summary += f" Creates {units} spool(s)" + (f" in {resolved_location}." if resolved_location else ".")
    # There is no clean single call that reverses a partial arrival plus spool creation, so the
    # card is where the user gets to see the whole effect. Undo is honestly absent, and this is
    # the one irreversible non-delete write in the tool set -- the flag set below is what puts
    # the red "cannot be undone" styling on the confirm button, not just this sentence.
    summary += " This cannot be undone in one click."
    return ConfirmCard(
        tool="arrive_order",
        title=f"Mark order #{order_id} arrived",
        summary=summary,
        before={"status": "open", "outstanding_units": units},
        after={"status": "arrived", "spools_created": units if create_spools else 0},
        destructive=True,
    )


async def _execute_arrive_order(ctx: ToolContext, args: dict) -> ExecutionResult:
    """Mark every outstanding line of an order arrived, optionally creating one spool per unit.

    Mirrors preview's guards exactly: a non-existent order and an order with nothing outstanding
    both 404/422 as a clean ToolError here too, rather than a 500 (the order lookup) or a silent
    "Marked order #N arrived" false success (the outstanding check) -- this write has no undo, so
    a confirmed action that then quietly does nothing is exactly the failure mode to avoid.
    """
    require_write(ctx)
    order_id = arg_int(args, "order_id")
    try:
        item = await order_db.get_by_id(ctx.db, order_id)
    except ItemNotFoundError as exc:
        raise ToolError(f"No order with ID {order_id} exists.") from exc
    if not any(line.arrived_at is None for line in item.lines):
        raise ToolError(f"Order #{order_id} has no outstanding lines; it already arrived.")
    location_id, _resolved_location = await _resolve_location_id(ctx, clean_str(args.get("location")))
    try:
        spools = await order_db.arrive(
            db=ctx.db,
            order_id=order_id,
            lines=None,
            create_spools=arg_bool(args, "create_spools", default=True),
            location_id=location_id,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    spool_ids = [spool.id for spool in spools]
    summary = f"Marked order #{order_id} arrived."
    if spool_ids:
        summary += f" Created spool(s) {', '.join(f'#{spool_id}' for spool_id in spool_ids)}."
    return ExecutionResult(summary=summary, data={"order_id": order_id, "spool_ids": spool_ids}, undo=None)


WRITE_TOOLS: dict[str, WriteTool] = {
    "create_order": WriteTool(
        name="create_order",
        description=(
            "Record a filament order the user has placed. 'lines' is a list of "
            "{filament_id, quantity, price_per_unit} objects; every filament must already exist "
            "(use create_filament first). Requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lines": {
                    "type": "array",
                    "description": "The ordered filaments.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filament_id": {"type": "integer"},
                            "quantity": {"type": "integer", "description": "Spools ordered (default 1)."},
                            "price_per_unit": {"type": "number"},
                        },
                        "required": ["filament_id"],
                    },
                },
                "shop": {"type": "string", "description": "Shop name; must already exist."},
                "order_number": {"type": "string"},
                "ordered_at": {"type": "string", "description": "ISO date the order was placed."},
                "comment": {"type": "string"},
            },
            "required": ["lines"],
        },
        preview=_preview_create_order,
        execute=_execute_create_order,
    ),
    "delete_order": WriteTool(
        name="delete_order",
        description="Delete an order and its lines (internal undo helper).",
        parameters={
            "type": "object",
            "properties": {"order_id": {"type": "integer"}},
            "required": ["order_id"],
        },
        preview=_preview_delete_order,
        execute=_execute_delete_order,
        model_facing=False,
        destructive=True,
    ),
    "arrive_order": WriteTool(
        name="arrive_order",
        description=(
            "Mark every outstanding line of an order as arrived, by default creating one spool per "
            "arriving unit in the given location. Use for 'my order arrived'. This cannot be undone. "
            "Requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "The order that arrived."},
                "create_spools": {"type": "boolean", "description": "Create a spool per unit (default true)."},
                "location": {"type": "string", "description": "Existing location name for the new spools."},
            },
            "required": ["order_id"],
        },
        preview=_preview_arrive_order,
        execute=_execute_arrive_order,
        destructive=True,
    ),
}
