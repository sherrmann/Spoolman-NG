"""Read a Spoolstock CSV export into Spoolman vendors, filaments and spools (#436).

Spoolstock exports one row per spool with its filament and brand flattened into dotted columns
(``filament.name``, ``filament.brand.name``, ``filament.material.density`` and so on). The column
names and their meaning are taken from the export format; nothing here is copied from another
importer. This module is pure: it turns rows into parameter dicts and leaves matching existing
records and writing them to the API layer (spoolman/api/v1/import_.py).

Mapping choices worth knowing:

* The filament's name is Spoolstock's ``filament.name`` (usually the colour); the product line and
  the re-purchase link go into the filament's comment, since Spoolman has no fields for them.
* A Spoolstock temperature range is kept as the filament's recommended range, and its midpoint
  becomes the nozzle or bed temperature to print at.
* Several colour codes become a multi-colour filament. Spoolstock does not say whether the colours
  run side by side or along the strand, so ``coaxial`` (side by side, as in dual-colour silk) is
  assumed and can be changed afterwards.
* The spool keeps Spoolstock's id in its comment (``Spoolstock ID: <id>``), which is how a second
  import of the same file recognises spools it has already brought in.
"""

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

#: Spoolman requires a diameter; Spoolstock rows normally carry one, and this is the common size.
DEFAULT_DIAMETER = 1.75

#: Marks a spool imported from Spoolstock, and carries its id for recognising it again.
SPOOL_ID_MARKER = "Spoolstock ID: "

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?)$")

#: A column every Spoolstock export has; a file without it is not one.
REQUIRED_COLUMN = "short_id"

#: Bounds for a value to be taken as meant. They keep a typo out of the database (and inside the
#: column types: integer temperatures, single-precision floats on MySQL), as a row error.
MAX_TEMPERATURE = 1000
MAX_AMOUNT = 1e9


@dataclass
class SpoolstockRow:
    """One Spoolstock row, mapped onto Spoolman's three levels."""

    short_id: str
    vendor_name: str
    filament: dict[str, Any] = field(default_factory=dict)
    spool: dict[str, Any] = field(default_factory=dict)
    #: The material's density was missing; the caller may fill it from known material data.
    density_missing: bool = False


def parse_csv(body: str) -> list[dict[str, str]]:
    """Parse a Spoolstock export into rows keyed by column name; blank rows are dropped."""
    text = body.lstrip("﻿")  # a byte-order mark from spreadsheet tools
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or REQUIRED_COLUMN not in reader.fieldnames:
        raise ValueError(f"This does not look like a Spoolstock export: it has no '{REQUIRED_COLUMN}' column.")
    rows = []
    for row in reader:
        # csv.DictReader keeps the values beyond the header's last column as a list under None.
        if None in row:
            raise ValueError(f"row {reader.line_num} has more fields than the header has columns")
        if any((value or "").strip() for value in row.values()):
            rows.append(row)
    return rows


def _text(row: dict[str, str], key: str) -> str | None:
    value = (row.get(key) or "").strip()
    return value or None


def _number(row: dict[str, str], key: str, limit: float = MAX_AMOUNT) -> float | None:
    """Read a number; None when empty or unreadable, ValueError when beyond ``limit``."""
    value = _text(row, key)
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        # Not guessed at: "1,000" may be a thousand or one, depending on where the file came from.
        return None
    if not math.isfinite(number):
        return None
    if abs(number) > limit:
        raise ValueError(f"{key} is {value}, more than the {limit:g} it can plausibly be")
    return number


def _temperatures(row: dict[str, str], low_key: str, high_key: str) -> tuple[int | None, int | None, int | None]:
    """Return (temperature to print at, range low, range high); the first is the range's midpoint."""
    low, high = _number(row, low_key, MAX_TEMPERATURE), _number(row, high_key, MAX_TEMPERATURE)
    if low is not None and high is not None and low > high:
        raise ValueError(f"{low_key} ({low:g}) is above {high_key} ({high:g})")
    if low is not None and high is not None:
        middle = (low + high) / 2
    else:
        middle = low if low is not None else high
    return tuple(round(v) if v is not None else None for v in (middle, low, high))  # type: ignore[return-value]


def colours(value: str | None) -> list[str]:
    """Return the hex colours (upper case, no ``#``) in a Spoolstock colour cell.

    The cell holds a JSON list (``["#1B1B1F", "#FFFFFF"]``) or, in older exports, plain codes
    separated by commas. Anything that is not a 6 or 8 digit hex code is left out.
    """
    if not value or not value.strip():
        return []
    try:
        parsed = json.loads(value)
        items = parsed if isinstance(parsed, list) else [parsed]
    except (json.JSONDecodeError, TypeError):
        items = value.split(",")
    found = []
    for item in items:
        match = _HEX.match(str(item).strip())
        if match:
            found.append(match.group(1).upper())
    return found


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "yes", "1"}


def map_row(row: dict[str, str]) -> SpoolstockRow:
    """Map one Spoolstock row to vendor name, filament parameters and spool parameters.

    Raises ValueError when the row cannot be imported: no Spoolstock id, a temperature range whose
    low end is above its high end, or a number beyond what it can plausibly be.
    """
    short_id = _text(row, "short_id")
    if short_id is None:
        raise ValueError("the row has no short_id")

    vendor_name = _text(row, "filament.brand.name") or "Unknown"
    net_weight = _number(row, "size")
    spool_weight = _number(row, "empty_spool.weight")
    density = _number(row, "filament.material.density")

    extruder, extruder_min, extruder_max = _temperatures(
        row,
        "filament.material.low_temp",
        "filament.material.high_temp",
    )
    bed, bed_min, bed_max = _temperatures(row, "filament.material.low_bed_temp", "filament.material.high_bed_temp")
    filament: dict[str, Any] = {
        "name": _text(row, "filament.name"),
        "material": _text(row, "filament.material.name"),
        "density": density,
        "diameter": _number(row, "diameter") or _number(row, "filament.diameter") or DEFAULT_DIAMETER,
        "weight": net_weight,
        "spool_weight": spool_weight,
        "article_number": _text(row, "filament.upc"),
        "settings_extruder_temp": extruder,
        "settings_bed_temp": bed,
        "settings_extruder_temp_min": extruder_min,
        "settings_extruder_temp_max": extruder_max,
        "settings_bed_temp_min": bed_min,
        "settings_bed_temp_max": bed_max,
    }
    found = colours(row.get("filament.color_hex_codes"))
    if len(found) == 1:
        filament["color_hex"] = found[0]
    elif len(found) > 1:
        filament["multi_color_hexes"] = ",".join(found)
        filament["multi_color_direction"] = "coaxial"
    comment_lines = [
        _text(row, "filament.notes"),
        f"Product line: {family}" if (family := _text(row, "filament.product_family")) else None,
        f"Buy again: {url}" if (url := _text(row, "filament.repurchase_url")) else None,
    ]
    if any(comment_lines):
        filament["comment"] = "\n".join(line for line in comment_lines if line)

    remaining = _number(row, "remaining_weight")
    initial = net_weight if net_weight is not None else remaining
    spool: dict[str, Any] = {
        "initial_weight": initial,
        "spool_weight": spool_weight,
        "price": _number(row, "price"),
        "archived": _is_true(row.get("depleted")),
    }
    if initial is not None and remaining is not None:
        spool["used_weight"] = round(max(initial - remaining, 0.0), 2)
    spool_lines = [
        _text(row, "notes"),
        f"Bought from: {source}" if (source := _text(row, "purchase_source")) else None,
        f"Bought on: {bought}" if (bought := _text(row, "purchased_on")) else None,
        f"{SPOOL_ID_MARKER}{short_id}",
    ]
    spool["comment"] = "\n".join(line for line in spool_lines if line)

    return SpoolstockRow(
        short_id=short_id,
        vendor_name=vendor_name,
        filament={k: v for k, v in filament.items() if v is not None},
        spool={k: v for k, v in spool.items() if v is not None},
        density_missing=density is None,
    )


def imported_ids(comments: list[str | None]) -> set[str]:
    """Return the Spoolstock ids recorded in spool comments by an earlier import."""
    ids = set()
    for comment in comments:
        for line in (comment or "").splitlines():
            if line.startswith(SPOOL_ID_MARKER):
                ids.add(line[len(SPOOL_ID_MARKER) :].strip())
    return ids
