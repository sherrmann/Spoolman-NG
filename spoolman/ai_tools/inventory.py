"""Locations and vendors: the registries a user organises their inventory by.

Reads answer "where do I keep things" and "who do I buy from"; the writes exist so the
assistant can create a location or vendor the user names in passing, instead of dead-ending
a filament creation on a vendor that doesn't exist yet.
"""

from spoolman.ai_tools.base import ReadTool, ToolContext, WriteTool, arg_limit, clean_str
from spoolman.database import location as location_db
from spoolman.database import vendor as vendor_db


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

WRITE_TOOLS: dict[str, WriteTool] = {}
