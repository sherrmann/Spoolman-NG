"""Tests for scripts/match_eval_noise.py (imported by path, as tests/test_ai_eval_script.py does)."""

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "match_eval_noise.py"


@pytest.fixture
def noise_module() -> Iterator[ModuleType]:
    """Import scripts/match_eval_noise.py by path (it is a standalone script, not a package)."""
    spec = importlib.util.spec_from_file_location("_match_eval_noise_under_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("_match_eval_noise_under_test", None)


CATALOG = [
    {
        "id": "3d-fuel_pla+_almond_1000_175_n",
        "manufacturer": "3D-Fuel",
        "name": "Almond Swirl",
        "material": "PLA+",
        "weight": 1000.0,
        "diameter": 1.75,
    },
    {
        "id": "prusament_petg_jet_black_1000_175",
        "manufacturer": "Prusament",
        "name": "Jet Black",
        "material": "PETG",
        "weight": 1000.0,
        "diameter": 1.75,
    },
    {
        "id": "overture_pla_orange_1000_175",
        "manufacturer": "Overture",
        "name": "Orange",
        "material": "PLA",
        "weight": 1000.0,
        "diameter": 1.75,
    },
]


def _label(**overrides: object) -> dict:
    base = {"vendor": "3D-Fuel", "name": "Almond Swirl", "material": "PLA+", "weight_g": 1000.0, "diameter_mm": 1.75}
    base.update(overrides)
    return base


# --- label_from_entry ---------------------------------------------------------------


def test_label_from_entry_maps_catalog_fields(noise_module: ModuleType) -> None:
    label = noise_module.label_from_entry(CATALOG[0])
    assert label == {
        "vendor": "3D-Fuel",
        "name": "Almond Swirl",
        "material": "PLA+",
        "weight_g": 1000.0,
        "diameter_mm": 1.75,
    }


# --- individual operators, including their no-op cases -------------------------------


def test_drop_vendor(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    assert noise_module.drop_vendor(_label(), rng)["vendor"] is None
    # No-op: nothing to drop.
    label = _label(vendor=None)
    assert noise_module.drop_vendor(label, rng) == label


def test_vendor_case(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(1)
    result = noise_module.vendor_case(_label(), rng)
    assert result["vendor"] in ("3D-FUEL", "3d-fuel")
    label = _label(vendor=None)
    assert noise_module.vendor_case(label, rng) == label


def test_vendor_suffix(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    assert noise_module.vendor_suffix(_label(), rng)["vendor"] == "3D-Fuel Filament"
    label = _label(vendor=None)
    assert noise_module.vendor_suffix(label, rng) == label


def test_material_in_name(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    assert noise_module.material_in_name(_label(), rng)["name"] == "PLA+ Almond Swirl"
    label = _label(material=None)
    assert noise_module.material_in_name(label, rng) == label


def test_drop_name_word(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    result = noise_module.drop_name_word(_label(), rng)
    assert result["name"] in ("Swirl", "Almond")
    # No-op: single-word name.
    label = _label(name="Almond")
    assert noise_module.drop_name_word(label, rng) == label


def test_ocr_swap(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    result = noise_module.ocr_swap(_label(name="Cool Grey"), rng)
    assert result["name"] != "Cool Grey"
    # No-op: name has none of the swappable substrings.
    label = _label(name="Xyz")
    assert noise_module.ocr_swap(label, rng) == label


def test_material_drop_plus(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    assert noise_module.material_drop_plus(_label(), rng)["material"] == "PLA"
    # No-op: no plus to drop.
    label = _label(material="PETG")
    assert noise_module.material_drop_plus(label, rng) == label


def test_weight_missing(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    assert noise_module.weight_missing(_label(), rng)["weight_g"] is None
    label = _label(weight_g=None)
    assert noise_module.weight_missing(label, rng) == label


def test_weight_in_kg(noise_module: ModuleType) -> None:
    rng = noise_module.random.Random(0)
    assert noise_module.weight_in_kg(_label(), rng)["weight_g"] == 1.0
    label = _label(weight_g=None)
    assert noise_module.weight_in_kg(label, rng) == label


# --- weight operator mutual exclusion -------------------------------------------------


def test_weight_operators_are_mutually_exclusive(noise_module: ModuleType) -> None:
    for seed in range(200):
        rng = noise_module.random.Random(seed)
        _, applied = noise_module._apply_noise(_label(), rng)  # noqa: SLF001
        assert not ({"weight_missing", "weight_in_kg"} <= set(applied))


# --- determinism -----------------------------------------------------------------------


def test_generate_cases_is_deterministic_per_seed(noise_module: ModuleType) -> None:
    first = noise_module.generate_cases(CATALOG, 6, seed=42)
    second = noise_module.generate_cases(CATALOG, 6, seed=42)
    assert first == second


def test_generate_cases_differs_across_seeds(noise_module: ModuleType) -> None:
    a = noise_module.generate_cases(CATALOG, 6, seed=1)
    b = noise_module.generate_cases(CATALOG, 6, seed=2)
    assert a != b


# --- stratification ----------------------------------------------------------------------


def test_generate_cases_stratifies_by_manufacturer(noise_module: ModuleType) -> None:
    # Each manufacturer needs at least two entries for round-robin stratification to give two
    # cases apiece; CATALOG above has only one entry per manufacturer, so build a wider one here.
    catalog = [
        {**entry, "id": f"{entry['id']}-{suffix}", "name": f"{entry['name']} {suffix}"}
        for entry in CATALOG
        for suffix in ("A", "B")
    ]
    cases = noise_module.generate_cases(catalog, 6, seed=1)
    assert len(cases) == 6
    manufacturers = [
        next(entry["manufacturer"] for entry in catalog if entry["id"] == case["catalog_id"]) for case in cases
    ]
    counts = {name: manufacturers.count(name) for name in ("3D-Fuel", "Prusament", "Overture")}
    assert counts == {"3D-Fuel": 2, "Prusament": 2, "Overture": 2}


# --- output passes through normalize_extraction ----------------------------------------


def test_weight_in_kg_comes_back_normalized_to_grams(noise_module: ModuleType) -> None:
    # normalize_extraction reads any weight below _MIN_PLAUSIBLE_WEIGHT_G (20) as kilograms and
    # scales it back up -- so a label noised to "1.0 kg" round-trips to 1000 g, not 1.0 g.
    catalog = [
        {
            "id": "only-entry",
            "manufacturer": "OnlyVendor",
            "name": "Solo Multi Word",
            "material": "PLA",
            "weight": 1000.0,
            "diameter": 1.75,
        },
    ]
    # Force weight_in_kg by trying seeds until it is the noise applied.
    for seed in range(500):
        cases = noise_module.generate_cases(catalog, 1, seed=seed)
        if "weight_in_kg" in cases[0]["noise"]:
            assert cases[0]["extraction"]["weight_g"] == 1000
            break
    else:
        pytest.fail("no seed in range produced a weight_in_kg case to check normalization against")


# --- catalog_id ------------------------------------------------------------------------


def test_catalog_id_is_the_source_entry_id(noise_module: ModuleType) -> None:
    cases = noise_module.generate_cases(CATALOG, 3, seed=1)
    ids = {entry["id"] for entry in CATALOG}
    assert all(case["catalog_id"] in ids for case in cases)


# --- skipping incomplete entries --------------------------------------------------------


def test_generate_cases_skips_entries_missing_required_fields(noise_module: ModuleType) -> None:
    catalog = [
        *CATALOG,
        {"id": "no-name", "manufacturer": "NoName Co", "name": None, "material": "PLA", "weight": 1000.0},
        {"id": "no-manufacturer", "manufacturer": None, "name": "Something", "material": "PLA", "weight": 1000.0},
        {"id": "no-material", "manufacturer": "NoMaterial Co", "name": "Something", "material": None, "weight": 1000.0},
    ]
    cases = noise_module.generate_cases(catalog, 20, seed=1)
    used_ids = {case["catalog_id"] for case in cases}
    assert "no-name" not in used_ids
    assert "no-manufacturer" not in used_ids
    assert "no-material" not in used_ids
