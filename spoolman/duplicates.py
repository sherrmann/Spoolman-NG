"""Warn before creating a manufacturer that already exists under another spelling.

Two tiers:

* **Exact**, always on and done in code: names that are equal once case, spacing, accents'
  compatibility forms and punctuation are ignored ("eSUN", "e-sun", "ESUN ").
* **Decision model**, only when the ``ai_feature_duplicate_check`` toggle is on and a decision
  endpoint is configured (see :mod:`spoolman.decision`): one Choice question over the existing
  manufacturers, for the same brand written differently ("Bambu" and "Bambu Lab"). It is opt-in
  because it sends the typed name and the existing manufacturer names to that endpoint on every
  pause in typing.

Neither tier blocks anything: the result is a hint the client shows next to the name field.
Any failure of the decision model leaves the exact tier's answer standing.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai, decision, spoolintake
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


async def _model_vendor(db: AsyncSession, name: str, vendors: list[Match]) -> Match | None:
    """Ask the decision model which vendor ``name`` is; None when off, unsure, or failing."""
    config = await model_enabled(db)
    if config is None:
        return None
    candidates = _shortlist(name, vendors)
    try:
        answer = (await decision.ask_choices(config, name, {"vendor": _vendor_question(candidates)}))["vendor"]
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
    picked = next(vendor for vendor in candidates if f"v{vendor.id}" == answer.choice)
    return Match(id=picked.id, name=picked.name, probability=round(probability, 3))


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
