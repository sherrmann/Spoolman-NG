"""SpoolmanDB catalog lookup: real filament specifications, so the model doesn't invent them.

Reuses the locally-synced catalog and the scorer that Scan-to-Spool already uses
(:mod:`spoolman.spoolintake`) rather than opening a second path to the same data. Scoring is
CPU-bound across thousands of entries, so it runs off the event loop.
"""

import asyncio

from spoolman import spoolintake
from spoolman.ai_tools.base import ReadTool, ToolContext, ToolError, arg_limit, clean_str

#: Below this a "match" is noise; the same floor Scan-to-Spool's catalog stage uses.
MIN_SCORE = 0.5


def build_extraction(args: dict) -> dict:
    """Map the tool's arguments onto the extraction shape the shared scorer expects."""
    extraction = {
        "vendor": clean_str(args.get("vendor")),
        "name": clean_str(args.get("name")),
        "material": clean_str(args.get("material")),
        "weight_g": None,
    }
    if not any((extraction["vendor"], extraction["name"], extraction["material"])):
        raise ToolError("Give at least one of 'vendor', 'name' or 'material' to look up.")
    return extraction


def entry_row(entry: dict, *, score: float) -> dict:
    """Shape one catalog entry into the fields create_filament needs."""
    return {
        "external_id": entry.get("id"),
        "vendor": entry.get("manufacturer"),
        "name": entry.get("name"),
        "material": entry.get("material"),
        "density": entry.get("density"),
        "diameter_mm": entry.get("diameter"),
        "weight_g": entry.get("weight"),
        "extruder_temp": entry.get("extruder_temp"),
        "bed_temp": entry.get("bed_temp"),
        "match_percent": int(score * 100),
    }


def _rank(extraction: dict, limit: int) -> list[dict]:
    """Score the whole catalog against the extraction and return the best rows. Pure and blocking."""
    scored = []
    for entry in spoolintake.load_catalog():
        score = spoolintake.score_candidate(
            extraction,
            vendor=entry.get("manufacturer"),
            name=entry.get("name"),
            material=entry.get("material"),
            weight_g=entry.get("weight"),
        )
        if score >= MIN_SCORE:
            scored.append(entry_row(entry, score=score))
    scored.sort(key=lambda row: -row["match_percent"])
    return scored[:limit]


async def _run_catalog_lookup(ctx: ToolContext, args: dict) -> dict:  # noqa: ARG001
    """Search the SpoolmanDB catalog for a filament's real specifications."""
    extraction = build_extraction(args)
    limit = min(arg_limit(args), 10)
    rows = await asyncio.to_thread(_rank, extraction, limit)
    return {"count": len(rows), "matches": rows}


READ_TOOLS: dict[str, ReadTool] = {
    "catalog_lookup": ReadTool(
        name="catalog_lookup",
        description=(
            "Look up a filament's real specifications (density, diameter, spool weight, print "
            "temperatures) in the public SpoolmanDB catalog. Call this BEFORE create_filament when "
            "you do not know the density and diameter; never guess those values."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vendor": {"type": "string", "description": "Manufacturer name, e.g. Sunlu, Prusament."},
                "name": {"type": "string", "description": "Product name, e.g. 'PLA Meta'."},
                "material": {"type": "string", "description": "Material, e.g. PLA, PETG, ASA."},
                "limit": {"type": "integer", "description": "Max matches to return (default 25, capped at 10)."},
            },
        },
        run=_run_catalog_lookup,
    ),
}

WRITE_TOOLS: dict = {}
