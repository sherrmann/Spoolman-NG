"""Order tools: what is on the way, and turning an arrival into spools.

An order links to a Shop (not a Vendor), and its open/arrived state is DERIVED from its lines'
``arrived_at`` rather than stored — so status filtering happens here, over the rows the
database layer returns, because ``order.find`` filters only by shop.
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
    optional_float,
    require_write,
)
from spoolman.ai_tools.stats import parse_date
from spoolman.database import filament as filament_db
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


async def _resolve_shop_id(ctx: ToolContext, name: str | None) -> int | None:
    if name is None:
        return None
    items, _ = await shop_db.find(db=ctx.db, name=name)
    lowered = name.strip().lower()
    match = next((item for item in items if (item.name or "").strip().lower() == lowered), None)
    if match is None:
        raise ToolError(f"No shop named '{name}' exists.")
    return match.id


async def _run_find_orders(ctx: ToolContext, args: dict) -> dict:
    """List orders with their derived status and outstanding units."""
    limit = arg_limit(args)
    status = parse_status(args)
    shop_id = await _resolve_shop_id(ctx, clean_str(args.get("shop")))
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
    after = {
        "shop": shop,
        "order_number": clean_str(args.get("order_number")),
        "lines": described,
        "units": sum(line["quantity"] for line in lines),
    }
    return ConfirmCard(
        tool="create_order",
        title=f"Create an order of {after['units']} spool(s)" + (f" from {shop}" if shop else ""),
        summary="; ".join(described),
        before={},
        after={key: value for key, value in after.items() if value is not None},
    )


async def _execute_create_order(ctx: ToolContext, args: dict) -> ExecutionResult:
    require_write(ctx)
    lines = parse_lines(args)
    await _describe_lines(ctx, lines)
    created = await order_db.create(
        db=ctx.db,
        shop_id=await _resolve_shop_id(ctx, clean_str(args.get("shop"))),
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
    return ConfirmCard(
        tool="delete_order",
        title=f"Delete order #{order_id}",
        summary="The order and its lines are removed. Spools already created from it are kept.",
        before=order_row(item),
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
    ),
}
