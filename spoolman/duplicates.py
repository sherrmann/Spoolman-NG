"""Warn before creating a manufacturer or filament that already exists.

Two tiers, for manufacturers and for filaments alike:

* **Exact**, always on and done in code. Manufacturers: names that are equal once case, spacing,
  accents' compatibility forms and punctuation are ignored ("eSUN", "e-sun", "ESUN "). Filaments:
  the same manufacturer, name (compared the same way), material, filament size and colour.
* **Decision model**, only when the ``ai_feature_duplicate_check`` toggle is on and a decision
  endpoint is configured (see :mod:`spoolman.decision`): one Choice question over the existing
  records, for the same thing written differently ("Bambu" and "Bambu Lab"; "PolyTerra PLA
  Charcoal" and "PolyTerra Charcoal Black"). It is opt-in because it sends what is being typed and
  existing names to that endpoint on every pause in typing. Colours are compared in code, never
  by the model: a filament whose colour is known to differ is never offered to it.

Neither tier blocks anything: the result is a hint the client shows next to the name field.
Any failure of the decision model leaves the exact tier's answer standing.
"""

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai, decision, spoolintake
from spoolman import math as colour_math
from spoolman.database import filament as filament_db
from spoolman.database import models

logger = logging.getLogger(__name__)

FEATURE_SETTING = "ai_feature_duplicate_check"

#: Most manufacturers offered to the model in one question. A library rarely has more; above
#: this the closest names by spelling are offered.
_SHORTLIST = 50
#: Names shorter than this are still being typed; asking about them wastes a request.
_MIN_NAME_LENGTH = 2
#: The model's probability for its pick must reach this before the client shows it. A wrong
#: "did you mean" is worse than none, so this errs high; scripts/duplicate_eval.py measures it.
SUGGEST_MIN_PROBABILITY = 0.6
_NONE = "none"
_VENDOR_INSTRUCTIONS = (
    "The state is the name a user is typing for a new 3D-printer filament manufacturer. Is it "
    "the same company as one of the listed existing manufacturers, written differently: another "
    "spelling or capitalisation, an abbreviation, or with or without a suffix such as 'Lab', "
    "'3D', 'Filament' or 'Technology'? Answer 'none' if it is a different company, even one "
    "with a similar name, or a product line rather than a manufacturer."
)


@dataclass(frozen=True)
class Match:
    """An existing record the new one may duplicate."""

    id: int
    name: str
    #: The model's probability for this pick; None for an exact match.
    probability: float | None = None


@dataclass(frozen=True)
class SimilarResult:
    """What the client shows: an exact match, else the model's suggestion, else nothing."""

    exact: Match | None = None
    suggestion: Match | None = None

    @property
    def source(self) -> str | None:
        """Which tier produced the hint: "exact", "model", or None."""
        if self.exact is not None:
            return "exact"
        return "model" if self.suggestion is not None else None


def normalize_name(value: str | None) -> str:
    """Compare-ready name: compatibility forms folded (NFKC), case folded, spacing collapsed."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "").casefold()).strip()


def exact_key(value: str | None) -> str:
    """Return the key two names must share to count as the same: letters and digits only.

    "e-Sun", "eSUN" and "E SUN" share a key; "eSUN 3D" does not, which is the model's job.
    """
    # Letters, digits and combining marks: isalnum() would drop the vowel signs of Indic scripts
    # and so merge names that differ only in them.
    return "".join(char for char in normalize_name(value) if unicodedata.category(char)[0] in "LNM")


async def _vendors(db: AsyncSession, exclude_id: int | None) -> list[Match]:
    rows = await db.execute(select(models.Vendor.id, models.Vendor.name).order_by(models.Vendor.id))
    return [Match(id=vid, name=name) for vid, name in rows if name and vid != exclude_id]


def _exact_vendor(name: str, vendors: list[Match]) -> Match | None:
    key = exact_key(name)
    if not key:
        return None
    # Prefer the vendor database/vendor.find_id_by_exact_name would pick (the same name ignoring
    # case and surrounding spaces), so the hint names the vendor an NFC or import path reuses.
    # Otherwise the oldest vendor sharing the key.
    wanted = name.strip().casefold()
    same = next((vendor for vendor in vendors if vendor.name.strip().casefold() == wanted), None)
    return same or next((vendor for vendor in vendors if exact_key(vendor.name) == key), None)


def _shortlist(name: str, vendors: list[Match]) -> list[Match]:
    if len(vendors) <= _SHORTLIST:
        return vendors
    ranked = sorted(vendors, key=lambda vendor: -spoolintake._similarity(name, vendor.name))  # noqa: SLF001
    return ranked[:_SHORTLIST]


def _vendor_question(candidates: list[Match]) -> dict:
    options = {f"v{vendor.id}": vendor.name for vendor in candidates}
    options[_NONE] = "None of these: a different manufacturer."
    return decision.choice_question(_VENDOR_INSTRUCTIONS, options)


async def model_enabled(db: AsyncSession) -> decision.DecisionConfig | None:
    """Return the decision endpoint when the duplicate check may use it, else None."""
    if not (await ai.get_feature_flags(db)).get("duplicate_check"):
        return None
    return await decision.resolve_config(db)


async def _ask_pick(
    config: decision.DecisionConfig,
    state: str | dict,
    question_id: str,
    question: dict,
    matches: dict[str, Match],
) -> Match | None:
    """Ask one Choice question; return the picked Match when the model is sure enough, else None.

    ``matches`` maps each option id in ``question`` except "none" to the record it stands for.
    """
    try:
        answer = (await decision.ask_choices(config, state, {question_id: question}))[question_id]
    except decision.DecisionError as exc:
        logger.warning("Duplicate check: no model answer: %s", exc)
        return None
    except Exception:  # noqa: BLE001 - an optional hint must never break the form
        logger.warning("Duplicate check: no model answer after an unexpected error.", exc_info=True)
        return None
    if answer.choice == _NONE:
        return None
    probability = answer.probabilities.get(answer.choice, answer.confidence)
    if probability is None or probability < SUGGEST_MIN_PROBABILITY:
        return None
    picked = matches[answer.choice]  # the model can only answer an offered option (_parse_choice)
    return Match(id=picked.id, name=picked.name, probability=round(probability, 3))


async def _model_vendor(db: AsyncSession, name: str, vendors: list[Match]) -> Match | None:
    """Ask the decision model which vendor ``name`` is; None when off, unsure, or failing."""
    config = await model_enabled(db)
    if config is None:
        return None
    candidates = _shortlist(name, vendors)
    try:
        question = _vendor_question(candidates)
    except ValueError:
        return None
    return await _ask_pick(config, name, "vendor", question, {f"v{vendor.id}": vendor for vendor in candidates})


async def similar_vendor(db: AsyncSession, name: str, *, exclude_id: int | None = None) -> SimilarResult:
    """Return an existing vendor that ``name`` probably duplicates, if any.

    ``exclude_id`` leaves out the vendor being renamed, so it is not reported as its own duplicate.
    """
    name = name.strip()
    vendors = await _vendors(db, exclude_id)
    exact = _exact_vendor(name, vendors)
    if exact is not None or len(exact_key(name)) < _MIN_NAME_LENGTH or not vendors:
        return SimilarResult(exact=exact)
    return SimilarResult(suggestion=await _model_vendor(db, name, vendors))


# --- Filaments ----------------------------------------------------------------------------------

#: CIE94 colour difference below which two colours count as the same. About 2.3 is the smallest
#: difference people notice side by side; swatches entered by hand or picked from a photo land a
#: little further apart than that for the same filament.
_SAME_COLOUR_DELTA_E = 3.0
_HEX_COLOUR = re.compile(r"^#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$")
_FILAMENT_INSTRUCTIONS = (
    "The state describes a new 3D-printer filament a user is about to add to their inventory. Is "
    "it the same product as one of the listed existing filaments: the same manufacturer, the same "
    "product line and the same material? A product may be named differently, for example with or "
    "without the material or colour in its name. Each listed filament says whether its colour "
    "matches the new one. Answer 'none' if it is a different product, or if you are unsure."
)

ColourRelation = Literal["same colour", "different colour", "colour unknown"]


@dataclass(frozen=True)
class FilamentDraft:
    """The fields of a filament being created that tell whether it already exists."""

    vendor_id: int | None = None
    #: A manufacturer typed by name, for a form that creates the manufacturer too.
    vendor_name: str | None = None
    name: str | None = None
    material: str | None = None
    color_hex: str | None = None
    multi_color_hexes: str | None = None
    diameter: float | None = None


def _colours(color_hex: str | None, multi_color_hexes: str | None) -> tuple[str, ...] | None:
    """Return the filament's colours as lower-case RRGGBB, or None when unknown or unreadable."""
    raw = [part.strip() for part in multi_color_hexes.split(",")] if multi_color_hexes else [color_hex or ""]
    colours = []
    for part in raw:
        match = _HEX_COLOUR.match(part)
        if match is None:
            return None
        colours.append(match.group(1).lower())
    return tuple(colours) or None


def colour_relation(a: tuple[str, ...] | None, b: tuple[str, ...] | None) -> ColourRelation:
    """Compare two filaments' colours: same when every colour is within ``_SAME_COLOUR_DELTA_E``.

    Multi-colour filaments are compared colour by colour in their stored order, and the direction
    (coaxial or along the length) is not compared. CIE94 weights by the first colour's chroma, so
    each pair is measured both ways and must be close both ways: the answer never depends on
    which filament came first.
    """
    if a is None or b is None:
        return "colour unknown"
    if len(a) != len(b):
        return "different colour"
    for left, right in zip(a, b, strict=True):
        lab_left = colour_math.rgb_to_lab(colour_math.hex_to_rgb(left))
        lab_right = colour_math.rgb_to_lab(colour_math.hex_to_rgb(right))
        distance = max(colour_math.delta_e(lab_left, lab_right), colour_math.delta_e(lab_right, lab_left))
        if distance >= _SAME_COLOUR_DELTA_E:
            return "different colour"
    return "same colour"


def _filament_label(row: dict) -> str:
    text = " ".join(str(part) for part in (row.get("vendor"), row.get("name")) if part) or "Unnamed filament"
    return f"{text} ({row['material']})" if row.get("material") else text


async def _filament_rows(db: AsyncSession, exclude_id: int | None) -> list[dict]:
    items, _ = await filament_db.find(db=db)
    return [
        {
            "filament_id": item.id,
            "vendor_id": item.vendor_id,
            "vendor": item.vendor.name if item.vendor is not None else None,
            "name": item.name,
            "material": item.material,
            "weight_g": item.weight,
            "diameter_mm": item.diameter,
            "colours": _colours(item.color_hex, item.multi_color_hexes),
        }
        for item in items
        if item.id != exclude_id
    ]


def _same_vendor(draft: FilamentDraft, row: dict) -> bool:
    if draft.vendor_id is not None:
        return row["vendor_id"] == draft.vendor_id
    if draft.vendor_name and draft.vendor_name.strip():
        # A typed name made only of punctuation names no manufacturer: it matches nothing.
        key = exact_key(draft.vendor_name)
        return bool(key) and bool(row["vendor"]) and exact_key(row["vendor"]) == key
    return row["vendor_id"] is None


def _same_size(a: object, b: object) -> bool:
    size_a = spoolintake._diameter_class(a)  # noqa: SLF001
    size_b = spoolintake._diameter_class(b)  # noqa: SLF001
    return size_a is None or size_b is None or size_a == size_b


def _exact_filament(draft: FilamentDraft, colours: tuple[str, ...] | None, rows: list[dict]) -> dict | None:
    name_key = exact_key(draft.name)
    material_key = spoolintake._material_key(draft.material)  # noqa: SLF001
    if not name_key:
        # Without a name the form is still being filled in: picking the material first must not
        # flag every unnamed filament of that material.
        return None
    for row in sorted(rows, key=lambda r: r["filament_id"]):  # the oldest wins
        if (
            _same_vendor(draft, row)
            and exact_key(row["name"]) == name_key
            and spoolintake._material_key(row["material"]) == material_key  # noqa: SLF001
            and _same_size(draft.diameter, row["diameter_mm"])
            and (colours == row["colours"] or colour_relation(colours, row["colours"]) == "same colour")
        ):
            return row
    return None


def _filament_question(candidates: list[dict], colours: tuple[str, ...] | None) -> dict:
    options = {}
    for row in candidates:
        text = _filament_label(row)
        if row.get("diameter_mm"):
            text += f", {row['diameter_mm']:g} mm"
        options[f"f{row['filament_id']}"] = f"{text}; {colour_relation(colours, row['colours'])}"
    options[_NONE] = "None of these: a different product."
    return decision.choice_question(_FILAMENT_INSTRUCTIONS, options)


async def _model_filament(
    db: AsyncSession,
    draft: FilamentDraft,
    vendor_name: str | None,
    colours: tuple[str, ...] | None,
    rows: list[dict],
) -> Match | None:
    """Ask the decision model which filament the draft is; None when off, unsure, or failing."""
    config = await model_enabled(db)
    if config is None:
        return None
    reading = {"vendor": vendor_name, "name": draft.name, "material": draft.material, "diameter_mm": draft.diameter}
    ranked = await asyncio.to_thread(spoolintake._rank_library, rows, reading, {})  # noqa: SLF001
    # Colour is decided here, not by the model: a filament known to be another colour is a
    # different product however alike the names are.
    candidates = [row for row in ranked if colour_relation(colours, row["colours"]) != "different colour"]
    if not candidates:
        return None
    try:
        question = _filament_question(candidates, colours)
    except ValueError:
        return None
    state = {key: value for key, value in reading.items() if value}
    matches = {f"f{row['filament_id']}": Match(id=row["filament_id"], name=_filament_label(row)) for row in candidates}
    return await _ask_pick(config, state, "filament", question, matches)


async def similar_filament(db: AsyncSession, draft: FilamentDraft, *, exclude_id: int | None = None) -> SimilarResult:
    """Return an existing filament that ``draft`` probably duplicates, if any.

    ``exclude_id`` leaves out the filament being edited, so it is not reported as its own duplicate.
    """
    rows = await _filament_rows(db, exclude_id)
    if not rows:
        return SimilarResult()
    colours = _colours(draft.color_hex, draft.multi_color_hexes)
    exact = _exact_filament(draft, colours, rows)
    if exact is not None:
        return SimilarResult(exact=Match(id=exact["filament_id"], name=_filament_label(exact)))
    if len(exact_key(draft.name)) < _MIN_NAME_LENGTH:
        return SimilarResult()
    vendor_name = draft.vendor_name
    if draft.vendor_id is not None:
        vendor_name = next((row["vendor"] for row in rows if row["vendor_id"] == draft.vendor_id), None)
        if vendor_name is None:
            vendor = await db.get(models.Vendor, draft.vendor_id)
            vendor_name = vendor.name if vendor is not None else None
    return SimilarResult(suggestion=await _model_filament(db, draft, vendor_name, colours, rows))
