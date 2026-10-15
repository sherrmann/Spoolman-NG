"""Export spools in the row format of SimplyPrint's Filament Manager import (#312).

SimplyPrint's own exporter (https://cdn.simplyprint.io/downloads/tools/spoolman-export.py) writes
a JSON array of flat rows from a Spoolman instance. This module writes the same keys, in the same
order, so the file can be uploaded to SimplyPrint unchanged. The code is our own; only the field
names and meanings follow that script.
"""

from typing import Any

from spoolman.api.v1.models import Spool, datetime_to_str

# The keys of every row, in the order SimplyPrint's exporter writes them.
SIMPLYPRINT_KEYS = (
    "spoolman_spool_id",
    "brand",
    "material",
    "filament_name",
    "color_hex",
    "width",
    "total_weight_grams",
    "remaining_weight_grams",
    "location_name",
    "cost",
    "lot_nr",
    "custom_note",
    "bought_at",
)


def simplyprint_row(spool: Spool) -> dict[str, Any]:
    """Map one spool to a SimplyPrint import row.

    Empty text fields are written as "" and a missing width as 1.75, because that is what
    SimplyPrint's script produces: it reads the spool API, which leaves empty fields out, and
    fills them with those defaults. Only the three numbers its script can leave empty
    (`total_weight_grams`, `remaining_weight_grams`, `cost`) are ever null here.

    Multi-colour spools export `color_hex` only, which is "" for a filament with no single colour.
    `remaining_weight_grams` is the API's own `remaining_weight`, which is
    `max(total - used_weight, 0)` and null when the total is unknown, as in SimplyPrint's script.
    """
    fil = spool.filament
    # The measured per-spool diameter wins over the filament's nominal one.
    width = spool.diameter if spool.diameter is not None else fil.diameter
    return {
        "spoolman_spool_id": spool.id,
        "brand": fil.vendor.name if fil.vendor is not None else "",
        "material": fil.material or "",
        "filament_name": fil.name or "",
        "color_hex": fil.color_hex or "",
        "width": width if width is not None else _DEFAULT_WIDTH,
        "total_weight_grams": spool.initial_weight if spool.initial_weight is not None else fil.weight,
        "remaining_weight_grams": spool.remaining_weight,
        "location_name": spool.location or "",
        "cost": spool.price,
        "lot_nr": spool.lot_nr or "",
        "custom_note": spool.comment or "",
        "bought_at": datetime_to_str(spool.registered),
    }


#: The width SimplyPrint's script assumes when Spoolman gives none.
_DEFAULT_WIDTH = 1.75
