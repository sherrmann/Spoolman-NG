"""Synthetic label noise for the match-rerank eval, generated from the SpoolmanDB catalog.

Real label readings are scarce -- photos are personal and slow to collect -- but the SpoolmanDB
catalog already holds thousands of real vendor/name/material/weight combinations. This turns each
catalog entry into a clean label, then perturbs it the way a vision extraction actually goes
wrong: a missing vendor, an OCR-mangled name, a missing weight reading. The result approximates a
real scan's extraction dict without a single photo.

The noise operators are fixed here, deliberately, and must not be tuned against match or rerank
results -- doing so would let the eval measure "cases chosen to make reranking look good" instead
of "cases the fuzzy scorer struggles with in practice". Each is a plausible label-reading mistake
observed or expected from a vision model, not one picked to move a number:

  drop_vendor        vendor is missing from the label
  vendor_case        vendor read in all caps or all lowercase
  vendor_suffix      "Filament" appended to the vendor, as many boxes print it
  material_in_name   the material echoed into the product name ("PLA+ Almond")
  drop_name_word     one word of a multi-word name misread as blank
  ocr_swap           a classic OCR confusion in the name (O/0, l/1/I, rn/m)
  material_drop_plus   a trailing "+" dropped from the material ("PLA+" -> "PLA")
  weight_missing     the net weight not printed, or not legible

There is deliberately no "weight read in kilograms" operator: every label passes through
spoolintake.normalize_extraction below, the same as a real scan's extraction, and that function
already reads any weight under 20 as kilograms and scales it back to grams -- so a kg noise
operator would round-trip straight back to the original value and change nothing.

Each operator is applied independently with probability NOISE_PROBABILITY.

Sampling is stratified by manufacturer, round-robin, so every maker gets an equal share of the
generated cases rather than a share proportional to its catalog size: with 59 makers in the
current catalog and n=300, each gets about 5 cases regardless of how many entries it has, so a
large maker such as Polymaker (15% of the catalog) is under-represented relative to its catalog
share, and a small one is over-represented.
"""

import random
import sys
from collections.abc import Callable
from pathlib import Path

# Run directly as `python scripts/match_eval_noise.py` (a sibling of scripts/ai_eval.py, following
# the same pattern) rather than as an installed package: CPython puts the *script's* directory on
# sys.path[0], not the repo root, and spoolman is not pip-installed here -- so the repo root has
# to be added by hand before the local-package import below can resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spoolman import spoolintake

#: Applied independently to every operator below.
NOISE_PROBABILITY = 0.3

_OCR_SWAPS = (("O", "0"), ("0", "O"), ("l", "1"), ("I", "1"), ("rn", "m"), ("m", "rn"))


#: drop_name_word is a no-op below this word count; a single-word name has nothing to drop.
_MIN_WORDS_TO_DROP = 2
#: vendor_case's coin flip between upper- and lower-casing the vendor.
_UPPER_OR_LOWER = 0.5


def label_from_entry(entry: dict) -> dict:
    """Build a clean label reading straight from a catalog entry's own fields."""
    return {
        "vendor": entry.get("manufacturer"),
        "name": entry.get("name"),
        "material": entry.get("material"),
        "weight_g": entry.get("weight"),
        "diameter_mm": entry.get("diameter"),
    }


def drop_vendor(label: dict, rng: random.Random) -> dict:  # noqa: ARG001
    """Blank the vendor, as if it were missing from the label."""
    if label.get("vendor") is None:
        return label
    return {**label, "vendor": None}


def vendor_case(label: dict, rng: random.Random) -> dict:
    """Upper- or lower-case the vendor, as a label printed in all-caps or misread might be."""
    vendor = label.get("vendor")
    if not vendor:
        return label
    return {**label, "vendor": vendor.upper() if rng.random() < _UPPER_OR_LOWER else vendor.lower()}


def vendor_suffix(label: dict, rng: random.Random) -> dict:  # noqa: ARG001
    """Append " Filament" to the vendor, as many boxes print it."""
    vendor = label.get("vendor")
    if not vendor:
        return label
    return {**label, "vendor": f"{vendor} Filament"}


def material_in_name(label: dict, rng: random.Random) -> dict:  # noqa: ARG001
    """Echo the material into the product name ("PLA+ Almond")."""
    name, material = label.get("name"), label.get("material")
    if not name or not material:
        return label
    return {**label, "name": f"{material} {name}"}


def drop_name_word(label: dict, rng: random.Random) -> dict:
    """Drop one word of a multi-word name; a no-op for a single-word name."""
    name = label.get("name")
    if not name:
        return label
    words = name.split()
    if len(words) < _MIN_WORDS_TO_DROP:
        return label
    drop = rng.randrange(len(words))
    return {**label, "name": " ".join(word for index, word in enumerate(words) if index != drop)}


def ocr_swap(label: dict, rng: random.Random) -> dict:
    """Replace one occurrence of a classic OCR confusion (O/0, l/1/I, rn/m) in the name."""
    name = label.get("name")
    if not name:
        return label
    present = [(old, new) for old, new in _OCR_SWAPS if old in name]
    if not present:
        return label
    old, new = rng.choice(present)
    return {**label, "name": name.replace(old, new, 1)}


def material_drop_plus(label: dict, rng: random.Random) -> dict:  # noqa: ARG001
    """Drop a trailing "+" from the material ("PLA+" -> "PLA")."""
    material = label.get("material")
    if not material or "+" not in material:
        return label
    return {**label, "material": material.replace("+", "")}


def weight_missing(label: dict, rng: random.Random) -> dict:  # noqa: ARG001
    """Blank the net weight, as if it were not printed or not legible."""
    if label.get("weight_g") is None:
        return label
    return {**label, "weight_g": None}


NOISE_OPERATORS: tuple[tuple[str, float, Callable[[dict, random.Random], dict]], ...] = (
    ("drop_vendor", NOISE_PROBABILITY, drop_vendor),
    ("vendor_case", NOISE_PROBABILITY, vendor_case),
    ("vendor_suffix", NOISE_PROBABILITY, vendor_suffix),
    ("material_in_name", NOISE_PROBABILITY, material_in_name),
    ("drop_name_word", NOISE_PROBABILITY, drop_name_word),
    ("ocr_swap", NOISE_PROBABILITY, ocr_swap),
    ("material_drop_plus", NOISE_PROBABILITY, material_drop_plus),
    ("weight_missing", NOISE_PROBABILITY, weight_missing),
)


def _apply_noise(label: dict, rng: random.Random) -> tuple[dict, list[str]]:
    """Apply every operator independently, skipping no-ops."""
    noisy = label
    applied: list[str] = []
    for name, probability, fn in NOISE_OPERATORS:
        if rng.random() >= probability:
            continue
        result = fn(noisy, rng)
        if result == noisy:
            continue  # a no-op for this label -- not recorded
        noisy = result
        applied.append(name)
    return noisy, applied


def generate_cases(catalog: list[dict], n: int, seed: int) -> list[dict]:
    """Generate n synthetic scan cases from the catalog, stratified round-robin by manufacturer.

    Deterministic for a given catalog and seed: same inputs, same output, every time.
    """
    rng = random.Random(seed)  # noqa: S311 -- reproducible synthetic-eval-data generation, not security
    usable = [entry for entry in catalog if entry.get("manufacturer") and entry.get("name") and entry.get("material")]

    by_manufacturer: dict[str, list[dict]] = {}
    for entry in usable:
        by_manufacturer.setdefault(entry["manufacturer"], []).append(entry)
    manufacturers = sorted(by_manufacturer)

    remaining = {manufacturer: list(entries) for manufacturer, entries in by_manufacturer.items()}
    cases = []
    index = 0
    while len(cases) < n and any(remaining.values()):
        for manufacturer in manufacturers:
            if len(cases) >= n:
                break
            pool = remaining[manufacturer]
            if not pool:
                continue
            choice_index = rng.randrange(len(pool))
            entry = pool.pop(choice_index)

            label = label_from_entry(entry)
            noisy, applied = _apply_noise(label, rng)
            extraction = spoolintake.normalize_extraction(noisy)
            cases.append(
                {
                    "id": f"gen-{index:04d}",
                    "extraction": extraction,
                    "catalog_id": entry["id"],
                    "noise": applied,
                },
            )
            index += 1
    return cases
