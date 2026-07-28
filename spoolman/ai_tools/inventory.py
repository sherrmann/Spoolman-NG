"""Locations and vendors: the registries a user organises their inventory by.

Reads answer "where do I keep things" and "who do I buy from"; the writes exist so the
assistant can create a location or vendor the user names in passing, instead of dead-ending
a filament creation on a vendor that doesn't exist yet.
"""

from spoolman.ai_tools.base import ReadTool, ToolContext, WriteTool, arg_limit, clean_str
from spoolman.database import location as location_db


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
    """List storage locations with how many spools and how much filament each holds."""
    limit = arg_limit(args)
    items, total = await location_db.find(db=ctx.db, name=clean_str(args.get("query")), limit=limit)
    ids = [item.id for item in items]
    counts = await location_db.get_aggregates(ctx.db, ids)
    weights = await location_db.get_weight_aggregates(ctx.db, ids)
    rows = [
        location_row(item, spool_count=counts.get(item.id, 0), remaining_g=weights.get(item.id, 0.0)) for item in items
    ]
    rows.sort(key=lambda row: -row["remaining_weight_g"])
    return {"count": total, "returned": len(rows), "locations": rows}


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
}

WRITE_TOOLS: dict[str, WriteTool] = {}
