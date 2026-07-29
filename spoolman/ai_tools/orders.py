"""Order tools: what is on the way, and turning an arrival into spools.

An order links to a Shop (not a Vendor), and its open/arrived state is DERIVED from its lines'
``arrived_at`` rather than stored — so status filtering happens here, over the rows the
database layer returns, because ``order.find`` filters only by shop.
"""

from spoolman.ai_tools.base import (
    ReadTool,
    ToolContext,
    ToolError,
    WriteTool,
    arg_limit,
    clean_str,
)
from spoolman.ai_tools.stats import parse_date
from spoolman.database import order as order_db
from spoolman.database import shop as shop_db

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

WRITE_TOOLS: dict[str, WriteTool] = {}
