"""Natural-language search translation (#362 B2).

Free text in, the *existing* filter model out — no new query language, no black box.
The model is prompted with the install's actual filter vocabulary (materials, vendors,
locations, lot numbers) and must pick from it; the reply is then validated against
that same vocabulary server-side, so a hallucinated value is dropped, never applied.
The client applies the result as ordinary, editable filter state, and anything the
request asked for that the filter model cannot express is reported back verbatim in
``dropped`` instead of being silently ignored.
"""

import json
import re
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import filament, spool, vendor

SearchEntity = Literal["spool", "filament"]

#: Vocabulary lists sent to the model are capped to keep the prompt bounded on large
#: installs; validation always runs against the full lists.
_PROMPT_VALUES_CAP = 80
#: Bound on the free-text query, matching what a search box plausibly holds.
MAX_QUERY_CHARS = 500

_HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")

#: filter key -> whether it applies per entity; also the validation allowlist.
_ENTITY_LIST_KEYS = {
    "spool": ("materials", "vendors", "locations", "lot_numbers"),
    "filament": ("materials", "vendors", "article_numbers"),
}


async def vocabulary(db: AsyncSession, entity: SearchEntity) -> dict[str, list[str]]:
    """Collect the install's real filter values for an entity - the validation allowlist."""
    vendors = [item.name for item in (await vendor.find(db=db))[0]]
    vocab: dict[str, list[str]] = {
        "materials": await filament.find_materials(db=db),
        "vendors": vendors,
    }
    if entity == "spool":
        vocab["locations"] = await spool.find_locations(db=db)
        vocab["lot_numbers"] = await spool.find_lot_numbers(db=db)
    else:
        vocab["article_numbers"] = await filament.find_article_numbers(db=db)
    return vocab


def build_messages(query: str, entity: SearchEntity, vocab: dict[str, list[str]]) -> list[dict]:
    """Build the chat messages asking the model to translate a query into filter JSON."""
    noun = "physical filament spools" if entity == "spool" else "filament types"
    lines = [
        f"You translate a search request over an inventory of {noun} (3D printing) into JSON filters.",
        "Reply with ONLY a JSON object - no prose, no code fences. Omit keys that do not apply.",
        "Keys:",
        '- "search": free text to match against names (string). Use for words that are not covered below.',
    ]
    for key in _ENTITY_LIST_KEYS[entity]:
        values = ", ".join(json.dumps(value) for value in vocab.get(key, [])[:_PROMPT_VALUES_CAP])
        lines.append(f'- "{key}": array of strings chosen ONLY from: [{values}]')
    lines.append(
        '- "color_hex": 6-digit RGB hex (no "#") approximating a requested color, e.g. "1a1a1a" for black.',
    )
    if entity == "spool":
        lines.append('- "archived": true ONLY if the request explicitly asks for archived/retired spools.')
    lines += [
        '- "dropped": array of short verbatim phrases from the request that CANNOT be expressed'
        " with the keys above (for example weight or price limits). Never guess around them.",
        "Copy list values exactly as spelled above. Do not invent values that are not in the lists.",
        "The request may be in any language; match meaning, not spelling.",
    ]
    return [
        {"role": "system", "content": "\n".join(lines)},
        {"role": "user", "content": query},
    ]


def _clean_str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [entry.strip() for entry in raw if isinstance(entry, str) and entry.strip()]


def sanitize(reply: dict, entity: SearchEntity, vocab: dict[str, list[str]]) -> tuple[dict, list[str]]:
    """Validate a model reply against the real vocabulary.

    Returns (filters, dropped): filters contains only allowlisted keys with values
    that actually exist (canonical casing restored); dropped collects both the
    model's own inexpressible-parts report and every value it invented.
    """
    filters: dict = {}
    dropped = _clean_str_list(reply.get("dropped"))

    for key in _ENTITY_LIST_KEYS[entity]:
        canonical = {value.casefold(): value for value in vocab.get(key, [])}
        kept: list[str] = []
        for wanted in _clean_str_list(reply.get(key)):
            match = canonical.get(wanted.casefold())
            if match is None:
                dropped.append(wanted)
            elif match not in kept:
                kept.append(match)
        if kept:
            filters[key] = kept

    search = reply.get("search")
    if isinstance(search, str) and search.strip():
        filters["search"] = search.strip()[:MAX_QUERY_CHARS]

    color = reply.get("color_hex")
    if isinstance(color, str) and _HEX_RE.match(color.strip().removeprefix("#")):
        filters["color_hex"] = color.strip().removeprefix("#").lower()
    if entity == "spool" and reply.get("archived") is True:
        filters["archived"] = True

    return filters, dropped[:10]
