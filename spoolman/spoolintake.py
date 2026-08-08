"""Scan-to-Spool intake (#361): vision extraction plus two-stage matching.

Extraction and matching are deliberately separate stages joined only by the
extraction JSON contract, so the extraction step is swappable — the configured
server-side vision model today, on-device extraction in the companion app later —
while matching stays plain fuzzy search with no LLM involved: the user's **own
filament library first** (a known filament just gains a spool, no duplicate
records), then the **locally-synced SpoolmanDB catalog**, with raw extraction as
the caller's fallback.

Photos are ephemeral by design: image bytes exist only as request-scoped variables
on their way to the configured endpoint, are never logged, and are never written to
disk or database.
"""

import asyncio
import difflib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai, externaldb
from spoolman.database import filament

logger = logging.getLogger(__name__)

#: The extraction JSON contract, shared with future on-device extractors.
EXTRACTION_KEYS = (
    "vendor",
    "name",
    "material",
    "color_hex",
    "weight_g",
    "spool_weight_g",
    "diameter_mm",
    "extruder_temp_c",
    "bed_temp_c",
    "lot_nr",
    "article_number",
    "confidence",
)

_STRING_KEYS = ("vendor", "name", "material", "lot_nr", "article_number")
_NUMBER_KEYS = ("weight_g", "spool_weight_g", "diameter_mm", "extruder_temp_c", "bed_temp_c")

#: A net spool weight below this is read as kilograms mis-reported ("1" for a 1 kg
#: spool) — no real spool holds less than 20 g of filament.
_MIN_PLAUSIBLE_WEIGHT_G = 20

EXTRACTION_PROMPT = (
    "You are reading a photo of a 3D-printing filament spool label or box. Extract what the "
    "label actually shows and answer with STRICT JSON only - no prose, no code fences.\n"
    "Keys (use null for anything not readable on the label):\n"
    '  "vendor": manufacturer/brand name\n'
    '  "name": the filament\'s name or color name as printed\n'
    '  "material": e.g. PLA, PETG, ABS, ASA, TPU\n'
    '  "color_hex": 6-digit hex of the filament color if determinable, without #\n'
    '  "weight_g": net filament weight in GRAMS (1 kg = 1000)\n'
    '  "spool_weight_g": empty-spool weight in grams, only if printed\n'
    '  "diameter_mm": filament diameter in mm, e.g. 1.75\n'
    '  "extruder_temp_c": recommended nozzle temperature in Celsius (middle of a printed range)\n'
    '  "bed_temp_c": recommended bed temperature in Celsius (middle of a printed range)\n'
    '  "lot_nr": lot/batch number as printed\n'
    '  "article_number": SKU/article number as printed\n'
    '  "confidence": "high", "medium" or "low" - your overall reading confidence\n'
    "Do not guess values that are not on the label."
)


class ExtractionParseError(Exception):
    """The model reply did not contain usable JSON; the message is user-safe."""


# --- Extraction --------------------------------------------------------------------


def parse_json_block(text: str) -> dict:
    """Pull the first JSON object out of a model reply, tolerating fences and prose."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start == -1:
        raise ExtractionParseError("The model did not return JSON.")
    depth = 0
    for index in range(start, len(cleaned)):
        if cleaned[index] == "{":
            depth += 1
        elif cleaned[index] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError as exc:
                    raise ExtractionParseError("The model returned malformed JSON.") from exc
                if not isinstance(parsed, dict):
                    raise ExtractionParseError("The model returned JSON that is not an object.")
                return parsed
    raise ExtractionParseError("The model returned truncated JSON.")


def coerce_number(value: object) -> float | None:
    """Coerce a raw extraction/catalog value to a float, or None if it isn't numeric-ish.

    Public because both this module's own scoring path and the curated ai_tools.catalog tool
    (a sibling that reuses this scorer against the same catalog) need the identical coercion:
    a bare bool is rejected (bool is an int subclass, but True/False are never a real
    measurement), an int/float passes through, and a string has its first number pulled out
    (tolerating a comma decimal separator).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", value)
        if match:
            return float(match.group(0).replace(",", "."))
    return None


def normalize_extraction(raw: dict) -> dict:
    """Normalize a raw extraction into the contract: known keys, clean types, sane units."""
    out: dict = dict.fromkeys(EXTRACTION_KEYS)
    for key in _STRING_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    for key in _NUMBER_KEYS:
        out[key] = coerce_number(raw.get(key))

    if out["weight_g"] is not None and out["weight_g"] < _MIN_PLAUSIBLE_WEIGHT_G:
        out["weight_g"] = round(out["weight_g"] * 1000, 1)

    color = raw.get("color_hex")
    if isinstance(color, str):
        color = color.strip().lstrip("#").lower()
        if re.fullmatch(r"[0-9a-f]{6}", color):
            out["color_hex"] = color

    confidence = raw.get("confidence")
    if isinstance(confidence, str) and confidence.lower() in ("high", "medium", "low"):
        out["confidence"] = confidence.lower()
    return out


async def extract(config: ai.AIConfig, image_base64: str, mime: str) -> dict:
    """Send the photo to the configured vision model and return a normalized extraction.

    The image travels as a data URL inside the request body and nowhere else.
    """
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": EXTRACTION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_base64}"}},
            ],
        },
    ]
    reply = await ai.chat_completion(config, messages, use_vision_model=True, want_json=True)
    return normalize_extraction(parse_json_block(reply))


# --- Matching (no LLM involved) ----------------------------------------------------


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _similarity(a: str | None, b: str | None) -> float:
    """Compute string similarity in [0, 1] with a containment boost for substring matches."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    if na in nb or nb in na:
        return max(ratio, 0.85)
    return ratio


#: Two spool weights within 5% of each other count as the same nominal size.
_WEIGHT_TOLERANCE = 0.05


def _weight_closeness(a: float | None, b: float | None) -> float:
    if a is None or b is None or a <= 0 or b <= 0:
        return 0.0
    return 1.0 if abs(a - b) / max(a, b) <= _WEIGHT_TOLERANCE else 0.0


def score_candidate(
    extraction: dict,
    *,
    vendor: str | None,
    name: str | None,
    material: str | None,
    weight_g: float | None,
) -> float:
    """Score a filament candidate against an extraction; pure and unit-testable.

    Name 0.4 + vendor 0.3 + material 0.2 + weight 0.1; a definite material mismatch
    scales the whole score down hard (a PETG label must not match a PLA record).
    """
    name_score = _similarity(extraction.get("name"), name)
    vendor_score = _similarity(extraction.get("vendor"), vendor)
    material_a, material_b = _norm(extraction.get("material")), _norm(material)
    if material_a and material_b:
        material_score = 1.0 if material_a == material_b else 0.0
    else:
        material_score = 0.5 if material_a or material_b else 0.0
    weight_score = _weight_closeness(extraction.get("weight_g"), weight_g)

    score = 0.4 * name_score + 0.3 * vendor_score + 0.2 * material_score + 0.1 * weight_score
    if material_a and material_b and material_a != material_b:
        score *= 0.3
    return round(score, 3)


_LIBRARY_MIN_SCORE = 0.45
_CATALOG_MIN_SCORE = 0.5
_MATCH_LIMIT = 5


def _rank_library(rows: list[dict], extraction: dict, aggregates: dict) -> list[dict]:
    """Score already-loaded filament rows against the extraction (best first).

    Split out from the async wrapper because this is the CPU-bound half: difflib over
    every filament in the library. Kept pure so it can run off the event loop.
    """
    candidates = []
    for row in rows:
        score = score_candidate(
            extraction,
            vendor=row["vendor"],
            name=row["name"],
            material=row["material"],
            weight_g=row["weight_g"],
        )
        if score < _LIBRARY_MIN_SCORE:
            continue
        spool_count, remaining = aggregates.get(row["filament_id"], (0, 0.0))
        candidates.append(
            {
                "kind": "library",
                **row,
                "active_spool_count": spool_count,
                "remaining_weight_g": round(remaining, 1),
                "match_percent": int(score * 100),
            },
        )
    candidates.sort(key=lambda entry: -entry["match_percent"])
    return candidates[:_MATCH_LIMIT]


async def match_library(db: AsyncSession, extraction: dict) -> list[dict]:
    """Rank the user's own filaments against the extraction (best first)."""
    items, _ = await filament.find(db=db)
    aggregates = await filament.get_aggregates(db, [item.id for item in items])
    rows = [
        {
            "filament_id": item.id,
            "vendor": item.vendor.name if item.vendor is not None else None,
            "name": item.name,
            "material": item.material,
            "weight_g": item.weight,
        }
        for item in items
    ]
    # Off the event loop: a large library is thousands of difflib comparisons, which would
    # otherwise stall every other request for the duration.
    return await asyncio.to_thread(_rank_library, rows, extraction, aggregates)


@dataclass
class _CatalogCache:
    path: Path | None = None
    mtime: float | None = None
    entries: list[dict] | None = None


_catalog_cache = _CatalogCache()


def load_catalog() -> list[dict]:
    """Load the locally-synced SpoolmanDB filament catalog (cached by file mtime).

    Missing or unreadable cache file degrades to an empty catalog — the intake flow
    then simply offers no catalog matches, it never fails on this.
    """
    path = externaldb.get_filaments_file()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _catalog_cache.entries is not None and _catalog_cache.path == path and _catalog_cache.mtime == mtime:
        return _catalog_cache.entries
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read the external filament catalog at %s.", path)
        return []
    entries = [entry for entry in parsed if isinstance(entry, dict)] if isinstance(parsed, list) else []
    _catalog_cache.path = path
    _catalog_cache.mtime = mtime
    _catalog_cache.entries = entries
    return entries


def match_catalog(extraction: dict) -> list[dict]:
    """Rank SpoolmanDB catalog entries against the extraction (best first).

    Synchronous and CPU-bound (difflib across the whole catalog, which runs to thousands
    of entries); :func:`build_matches` runs it off the event loop.
    """
    candidates = []
    for entry in load_catalog():
        score = score_candidate(
            extraction,
            vendor=entry.get("manufacturer"),
            name=entry.get("name"),
            material=entry.get("material"),
            weight_g=coerce_number(entry.get("weight")),
        )
        if score < _CATALOG_MIN_SCORE:
            continue
        candidates.append(
            {
                "kind": "catalog",
                "external_id": entry.get("id"),
                "vendor": entry.get("manufacturer"),
                "name": entry.get("name"),
                "material": entry.get("material"),
                "weight_g": entry.get("weight"),
                "diameter_mm": entry.get("diameter"),
                "match_percent": int(score * 100),
            },
        )
    candidates.sort(key=lambda entry: -entry["match_percent"])
    return candidates[:_MATCH_LIMIT]


async def build_matches(db: AsyncSession, extraction: dict) -> dict:
    """Run both match stages: the user's library first, then the catalog."""
    return {
        "library": await match_library(db, extraction),
        "catalog": await asyncio.to_thread(match_catalog, extraction),
    }
