"""Tests for scripts/ai_eval_vision.py's ``--dump-extractions`` flag (imported by path)."""

import base64
import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from spoolman import ai

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ai_eval_vision.py"


@pytest.fixture
def vision_module() -> Iterator[ModuleType]:
    """Import scripts/ai_eval_vision.py by path (it is a standalone script, not a package)."""
    spec = importlib.util.spec_from_file_location("_ai_eval_vision_under_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("_ai_eval_vision_under_test", None)


@pytest.fixture
def photos(tmp_path: Path) -> Path:
    """Build a photo directory with cases.json and dummy image files for two cases."""
    folder = tmp_path / "photos"
    folder.mkdir()
    (folder / "good.jpg").write_bytes(b"not-really-a-jpeg")
    (folder / "bad.jpg").write_bytes(b"also-not-a-jpeg")
    cases = [
        {"file": "good.jpg", "what": "extracts cleanly", "want": {"vendor": "Prusament", "weight_g": 1000}},
        {"file": "bad.jpg", "what": "extraction fails", "want": {"vendor": "Overture", "weight_g": 1000}},
    ]
    (folder / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def _ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOOLMAN_AI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("SPOOLMAN_AI_MODEL", "test-model")


_GOOD_EXTRACTION = {
    "vendor": "Prusament",
    "name": "Jet Black",
    "material": "PETG",
    "color_hex": None,
    "weight_g": 1000.0,
    "spool_weight_g": None,
    "diameter_mm": 1.75,
    "extruder_temp_c": None,
    "bed_temp_c": None,
    "lot_nr": None,
    "article_number": None,
    "confidence": "high",
}


async def _fake_extract(config: ai.AIConfig, image_base64: str, mime: str) -> dict:  # noqa: ARG001
    if image_base64 == base64.b64encode(b"not-really-a-jpeg").decode():
        return _GOOD_EXTRACTION
    raise ai.AIRequestError("simulated failure")


async def test_dump_extractions_writes_only_successful_photos(
    vision_module: ModuleType,
    photos: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vision_module.spoolintake, "extract", _fake_extract)
    dump_path = photos.parent / "dump.jsonl"

    exit_code = await vision_module._main(photos, min_completion=0.0, dump_extractions=dump_path)  # noqa: SLF001

    assert exit_code == 0
    lines = dump_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry == {"file": "good.jpg", "extraction": _GOOD_EXTRACTION}


async def test_dump_extractions_overwrites_an_existing_file(
    vision_module: ModuleType,
    photos: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vision_module.spoolintake, "extract", _fake_extract)
    dump_path = photos.parent / "dump.jsonl"
    dump_path.write_text("stale content from a previous run\n", encoding="utf-8")

    await vision_module._main(photos, min_completion=0.0, dump_extractions=dump_path)  # noqa: SLF001

    lines = dump_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "stale" not in dump_path.read_text(encoding="utf-8")


async def test_no_dump_file_written_without_the_flag(
    vision_module: ModuleType,
    photos: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vision_module.spoolintake, "extract", _fake_extract)

    exit_code = await vision_module._main(photos, min_completion=0.0, dump_extractions=None)  # noqa: SLF001

    assert exit_code == 0
    assert not (photos.parent / "dump.jsonl").exists()


async def test_a_case_without_want_or_what_is_still_dumped(
    vision_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Photos labelled only for the rerank eval carry a catalog_id and no expected fields."""
    folder = tmp_path / "labelled-only"
    folder.mkdir()
    (folder / "good.jpg").write_bytes(b"not-really-a-jpeg")
    (folder / "cases.json").write_text(json.dumps([{"file": "good.jpg", "catalog_id": "x"}]), encoding="utf-8")
    monkeypatch.setattr(vision_module.spoolintake, "extract", _fake_extract)
    dump_path = tmp_path / "dump.jsonl"

    exit_code = await vision_module._main(folder, min_completion=1.0, dump_extractions=dump_path)  # noqa: SLF001

    assert exit_code == 0
    assert json.loads(dump_path.read_text(encoding="utf-8"))["file"] == "good.jpg"
