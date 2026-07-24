"""Natural-language spool search (#362, B2).

Translate a free-text query like "matte black PETG under 500 g in shelf B" into the spool
list's *existing* filter model, so the result is ordinary, editable filter chips — not an
opaque result set. Everything here is deliberately transparent and correctable:

* The model is grounded on the real vocabulary — the actual materials, vendors,
  locations and lot numbers in this database — and told to pick only from those lists.
* Its output is then validated against that same vocabulary server-side: a value the
  model returns is kept only if it genuinely exists (case-insensitively) and is echoed
  back in the database's own casing. A hallucinated material or a made-up location is
  dropped, never invented into a filter (the #362 acceptance criterion).
* Anything the model couldn't map to a real field degrades to free-text ``search``, and a
  reply we can't parse at all degrades to searching the raw query — the AI path never
  blocks the normal one.

The translation is a single strict-JSON completion (no tool calling), which keeps it fast
and workable even with a small local model.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai
from spoolman.database import filament as filament_db
from spoolman.database import models
from spoolman.database import spool as spool_db
from spoolman.spoolintake import ExtractionParseError, parse_json_block

logger = logging.getLogger(__name__)

#: Spool fields a natural-language query is allowed to sort by (mapped verbatim onto the
#: list's sort model, which understands the computed keys too).
_ALLOWED_SORT_FIELDS = frozenset(
    {"remaining_weight", "used_weight", "first_used", "last_used", "registered", "location", "price"},
)

#: Cap the vocabulary handed to the model so a large library can't blow up the prompt.
_MAX_VOCAB = 80

#: Length of a valid 6-digit RGB hex colour (without '#').
_HEX_LEN = 6

#: The categorical query keys and the spool-list filter field each maps to.
_FIELD_MAP = {
    "material": "filament.material",
    "vendor": "filament.vendor.name",
    "location": "location",
    "lot_nr": "lot_nr",
}


def _prompt(query: str, vocab: dict[str, list[str]], locale: str) -> str:
    """Build the strict-JSON translation prompt, grounded on the real vocabulary."""

    def _list(values: list[str]) -> str:
        return json.dumps(values, ensure_ascii=False) if values else "(none on record)"

    return (
        "You translate a user's plain-language request into filters for a 3D-printing filament "
        "spool list. Answer with STRICT JSON only - no prose, no code fences.\n"
        f"User request (their language, locale {locale}): {query!r}\n\n"
        "Use ONLY values from these lists that already exist in the database. If the request mentions "
        "a material/vendor/location/lot that is NOT in the matching list, do not invent it - put those "
        'words in "search" instead.\n'
        f"materials: {_list(vocab['materials'])}\n"
        f"vendors: {_list(vocab['vendors'])}\n"
        f"locations: {_list(vocab['locations'])}\n"
        f"lot_numbers: {_list(vocab['lot_numbers'])}\n\n"
        "Output keys (use null when not applicable):\n"
        '  "material": array of materials from the list, or null\n'
        '  "vendor": array of vendors from the list, or null\n'
        '  "location": array of locations from the list, or null\n'
        '  "lot_nr": array of lot numbers from the list, or null\n'
        '  "color_hex": a 6-digit hex (no #) if a colour is described, e.g. black -> "000000", or null\n'
        '  "search": leftover free-text terms that are not covered above, or null\n'
        '  "sort": {"field": one of '
        f"{sorted(_ALLOWED_SORT_FIELDS)}, "
        '"direction": "asc" or "desc"}, or null\n'
        "Match list values case-insensitively but copy them exactly as written in the list."
    )


async def _vendor_names(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(models.Vendor.name).distinct())
    return [name for (name,) in rows.all() if name]


async def _vocabulary(db: AsyncSession) -> dict[str, list[str]]:
    return {
        "materials": [value for value in await filament_db.find_materials(db=db) if value][:_MAX_VOCAB],
        "vendors": (await _vendor_names(db))[:_MAX_VOCAB],
        "locations": [value for value in await spool_db.find_locations(db=db) if value][:_MAX_VOCAB],
        "lot_numbers": [value for value in await spool_db.find_lot_numbers(db=db) if value][:_MAX_VOCAB],
    }


def _as_list(value: object) -> list[str]:
    """Coerce a model value (string or list) to a list of non-empty strings."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _ground(values: list[str], vocab: list[str]) -> list[str]:
    """Keep only requested values that exist in the vocabulary; return them in DB casing.

    This is the hallucination guard: a value with no case-insensitive match is dropped.
    """
    lookup = {entry.casefold(): entry for entry in vocab}
    grounded: list[str] = []
    for value in values:
        canonical = lookup.get(value.strip().casefold())
        if canonical is not None and canonical not in grounded:
            grounded.append(canonical)
    return grounded


def _valid_color_hex(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lstrip("#").lower()
    return cleaned if len(cleaned) == _HEX_LEN and all(c in "0123456789abcdef" for c in cleaned) else None


def _valid_sort(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    field = value.get("field")
    direction = str(value.get("direction", "asc")).lower()
    if field in _ALLOWED_SORT_FIELDS and direction in ("asc", "desc"):
        return {"field": field, "direction": direction}
    return None


def _empty(search: str | None = None) -> dict:
    return {"filters": [], "search": search, "color_hex": None, "sort": None}


def _validate(raw: dict, vocab: dict[str, list[str]]) -> dict:
    """Turn a parsed model reply into a validated, fully-grounded filter payload."""
    filters = []
    for key, field_name in _FIELD_MAP.items():
        grounded = _ground(_as_list(raw.get(key)), vocab[_vocab_key(key)])
        if grounded:
            filters.append({"field": field_name, "values": grounded})
    search = raw.get("search")
    return {
        "filters": filters,
        "search": search.strip() if isinstance(search, str) and search.strip() else None,
        "color_hex": _valid_color_hex(raw.get("color_hex")),
        "sort": _valid_sort(raw.get("sort")),
    }


def _vocab_key(field: str) -> str:
    return {"material": "materials", "vendor": "vendors", "location": "locations", "lot_nr": "lot_numbers"}[field]


async def translate(db: AsyncSession, config: ai.AIConfig, query: str, *, locale: str = "en") -> dict:
    """Translate a free-text query into a validated spool-filter payload.

    Never raises on a provider or parse problem: an unparseable reply degrades to a plain
    free-text search over the original query, so the AI button can't break the search box.
    """
    query = query.strip()
    if not query:
        return _empty()
    vocab = await _vocabulary(db)
    messages = [{"role": "user", "content": _prompt(query, vocab, locale)}]
    try:
        reply = await ai.chat_completion(config, messages, max_tokens=400)
        raw = parse_json_block(reply)
    except (ai.AIRequestError, ExtractionParseError):
        # Degrade to the normal free-text path rather than failing the request.
        return _empty(search=query)
    return _validate(raw, vocab)
