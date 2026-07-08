"""Functionality for importing data — the inverse of spoolman.export (issue #55).

Parsing here is deliberately format- and API-agnostic: it turns a CSV or JSON body (the exact shape
produced by the /export endpoints, i.e. flat rows with dot-separated keys) into per-row parameter
dicts. The API layer (spoolman/api/v1/import_.py) validates those dicts with the existing
*Parameters models and applies them to the database in a single all-or-nothing transaction.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ImportFormat(str, Enum):
    """Body format of an import request."""

    CSV = "csv"
    JSON = "json"


class ImportMode(str, Enum):
    """How to treat rows that carry an id matching an existing row."""

    # Always insert new rows; any id in the data is ignored (fresh copies).
    CREATE = "create"
    # Update the row whose id matches; insert the rest.
    UPSERT = "upsert"
    # Leave an existing id untouched; insert only the rows whose id is new/absent.
    SKIP_EXISTING = "skip_existing"


@dataclass
class ParsedRow:
    """A single import row split into its optional source id and its parameter dict."""

    source_id: int | None
    params: dict[str, Any]


@dataclass
class ImportResult:
    """Summary of an import operation, returned to the caller."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)


def parse_body(body: str, fmt: ImportFormat) -> list[dict[str, Any]]:
    """Parse a raw request body into a list of flat row dicts.

    CSV is read with a header row (matching the export). JSON accepts either a list of objects or a
    single object. Returns an empty list for an empty body.
    """
    body = body.strip()
    if not body:
        return []

    if fmt == ImportFormat.CSV:
        reader = csv.DictReader(io.StringIO(body))
        return [dict(row) for row in reader]

    data = json.loads(body)
    if isinstance(data, dict):
        return [data]
    if not isinstance(data, list):
        raise ValueError("JSON import must be a list of objects or a single object.")  # noqa: TRY004
    if not all(isinstance(item, dict) for item in data):
        raise ValueError("JSON import list must contain only objects.")
    return data


def _is_empty(value: Any) -> bool:  # noqa: ANN401
    """Treat None and blank/whitespace strings as absent (CSV renders unset cells as empty strings)."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def unflatten_row(row: dict[str, Any], *, fk_map: dict[str, str], ignore: set[str]) -> ParsedRow:
    """Turn one flat export row into a (source_id, params) pair.

    - ``id`` becomes the source id (used for upsert / skip matching), never a parameter.
    - keys in ``fk_map`` (e.g. ``vendor.id`` -> ``vendor_id``) are remapped to their foreign-key param.
    - ``extra.<key>`` entries are collected into an ``extra`` dict (values kept verbatim — the export
      already stores them JSON-encoded).
    - keys in ``ignore`` (computed/aggregate columns, ``registered``) and any other dotted/nested key
      are dropped, so a round-tripped export does not try to write read-only fields.
    - empty values are dropped so optional fields stay unset instead of failing validation.
    """
    params: dict[str, Any] = {}
    extra: dict[str, str] = {}
    source_id: int | None = None

    for key, value in row.items():
        if _is_empty(value):
            continue
        if key == "id":
            source_id = int(value)
            continue
        if key in fk_map:
            params[fk_map[key]] = int(value)
            continue
        if key.startswith("extra."):
            extra_key = key[len("extra.") :]
            extra[extra_key] = value if isinstance(value, str) else json.dumps(value)
            continue
        if key in ignore or "." in key:
            continue
        params[key] = value

    if extra:
        params["extra"] = extra

    return ParsedRow(source_id=source_id, params=params)
