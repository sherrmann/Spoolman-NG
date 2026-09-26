"""Tests for the manufacturer and filament duplicate checks (spoolman/duplicates.py).

Oracle strategy:
  * The exact tier is pure code -- normalize_name/exact_key/_exact_vendor/_colours/colour_relation
    are asserted directly, and similar_vendor/similar_filament's exact path through a throwaway
    DB session.
  * The model tier's only boundary is the outbound HTTP request to the decision endpoint,
    mocked with respx exactly like tests/test_ai.py and tests/integration/test_ai_endpoints.py.
    Assertions are on the observable SimilarResult, plus "no request was made" where that is
    the point of the test.
"""

import json

import pytest
import respx
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai, duplicates
from spoolman.database import filament as filament_db
from spoolman.database import setting as setting_db
from spoolman.database import vendor as vendor_db
from spoolman.settings import SETTINGS

_DECISION_URL = "https://api.typesafe.ai/v1/systemone"


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the AI probe cache and the SPOOLMAN_AI_* env between tests."""
    monkeypatch.setattr(ai, "_state", ai._AIState())  # noqa: SLF001
    for name in (
        ai.ENV_BASE_URL,
        ai.ENV_API_KEY,
        ai.ENV_MODEL,
        ai.ENV_VISION_MODEL,
        ai.ENV_DECISION_BASE_URL,
        ai.ENV_DECISION_API_KEY,
        ai.ENV_DECISION_MODEL,
    ):
        monkeypatch.delenv(name, raising=False)


async def _enable_duplicate_check(db: AsyncSession) -> None:
    await setting_db.update(db=db, definition=SETTINGS["ai_feature_duplicate_check"], value=json.dumps(obj=True))


async def _set_decision_base_url(db: AsyncSession, url: str) -> None:
    await setting_db.update(db=db, definition=SETTINGS[ai.SETTING_DECISION_BASE_URL], value=json.dumps(url))


def _answer_payload(choice: str, *, probabilities: dict | None = None, confidence: float | None = None) -> dict:
    answer: dict = {"type": "choice", "choice": choice}
    if probabilities is not None:
        answer["probabilities"] = probabilities
    if confidence is not None:
        answer["confidence"] = confidence
    return {"model": "jev-1.13.0", "answers": {"vendor": answer}, "usage": {}}


def _filament_answer_payload(choice: str, *, probabilities: dict | None = None) -> dict:
    answer: dict = {"type": "choice", "choice": choice}
    if probabilities is not None:
        answer["probabilities"] = probabilities
    return {"model": "jev-1.13.0", "answers": {"filament": answer}, "usage": {}}


async def _create_filament(
    db: AsyncSession,
    *,
    vendor_id: int | None = None,
    name: str | None = "PolyLite PLA",
    material: str | None = "PLA",
    diameter: float = 1.75,
    color_hex: str | None = "ff0000",
    multi_color_hexes: str | None = None,
) -> object:
    return await filament_db.create(
        db=db,
        vendor_id=vendor_id,
        name=name,
        material=material,
        density=1.24,
        diameter=diameter,
        color_hex=color_hex,
        multi_color_hexes=multi_color_hexes,
    )


# --- normalize_name / exact_key -----------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["eSUN", "e-Sun", "E SUN ", "ｅＳＵＮ"],  # full-width "eSUN"  # noqa: RUF001
)
def test_exact_key_shares_a_key_across_spellings(name: str) -> None:
    assert duplicates.exact_key(name) == duplicates.exact_key("eSUN")


def test_exact_key_distinguishes_a_longer_name() -> None:
    assert duplicates.exact_key("eSUN 3D") != duplicates.exact_key("eSUN")


@pytest.mark.parametrize("name", ["", "---", None])
def test_exact_key_is_empty_for_punctuation_or_nothing(name: str | None) -> None:
    assert duplicates.exact_key(name) == ""


# --- similar_vendor: exact tier, no model configured --------------------------------


async def test_similar_vendor_exact_match_oldest_wins(db_session: AsyncSession) -> None:
    # Neither existing name is a literal casefold match for "ESUN", so _exact_vendor falls
    # back to the oldest vendor sharing its exact_key rather than preferring either by name.
    first = await vendor_db.create(db=db_session, name="E-Sun")
    await vendor_db.create(db=db_session, name="E Sun")

    result = await duplicates.similar_vendor(db_session, "ESUN")

    assert result.exact is not None
    assert result.exact.id == first.id
    assert result.exact.probability is None
    assert result.source == "exact"
    assert result.suggestion is None


async def test_similar_vendor_exact_match_prefers_the_casefold_match_over_the_oldest(
    db_session: AsyncSession,
) -> None:
    """database.vendor.find_id_by_exact_name's own rule wins before falling back to the oldest."""
    e_sun = await vendor_db.create(db=db_session, name="E-Sun")
    esun = await vendor_db.create(db=db_session, name="eSUN")

    assert (await duplicates.similar_vendor(db_session, "esun")).exact.id == esun.id
    assert (await duplicates.similar_vendor(db_session, "e sun")).exact.id == e_sun.id


async def test_similar_vendor_exact_match_excludes_the_renamed_vendor(db_session: AsyncSession) -> None:
    renamed = await vendor_db.create(db=db_session, name="eSUN")

    result = await duplicates.similar_vendor(db_session, "eSUN", exclude_id=renamed.id)

    assert result.exact is None
    assert result.suggestion is None


async def test_similar_vendor_near_miss_returns_nothing_without_a_model(db_session: AsyncSession) -> None:
    await vendor_db.create(db=db_session, name="Polymaker")

    result = await duplicates.similar_vendor(db_session, "Polylite")

    assert result.exact is None
    assert result.suggestion is None
    assert result.source is None


async def test_similar_vendor_punctuation_only_name_returns_nothing(db_session: AsyncSession) -> None:
    await vendor_db.create(db=db_session, name="Polymaker")

    result = await duplicates.similar_vendor(db_session, "---")

    assert result.exact is None
    assert result.suggestion is None


# --- similar_vendor: the model tier is gated on both settings -----------------------


async def test_model_not_called_when_toggle_off_even_with_url_set(db_session: AsyncSession) -> None:
    await _set_decision_base_url(db_session, "https://api.typesafe.ai")
    await vendor_db.create(db=db_session, name="Bambu Lab")

    # A registered route, not a bare respx.mock: an unmocked call would raise inside
    # similar_vendor, where the catch-all turns it into "no suggestion" and the test would pass.
    with respx.mock:
        route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_answer_payload("none")))
        result = await duplicates.similar_vendor(db_session, "Bambu")

    assert route.call_count == 0
    assert result.suggestion is None


async def test_model_not_called_when_url_unset_even_with_toggle_on(db_session: AsyncSession) -> None:
    await _enable_duplicate_check(db_session)
    await vendor_db.create(db=db_session, name="Bambu Lab")

    # A registered route, not a bare respx.mock: an unmocked call would raise inside
    # similar_vendor, where the catch-all turns it into "no suggestion" and the test would pass.
    with respx.mock:
        route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_answer_payload("none")))
        result = await duplicates.similar_vendor(db_session, "Bambu")

    assert route.call_count == 0
    assert result.suggestion is None


@pytest.mark.parametrize("name", ["---", "a-"])
async def test_model_not_called_for_a_name_too_short_once_normalized(db_session: AsyncSession, name: str) -> None:
    await _enable_duplicate_check(db_session)
    await _set_decision_base_url(db_session, "https://api.typesafe.ai")
    await vendor_db.create(db=db_session, name="Bambu Lab")

    # A registered route, not a bare respx.mock: an unmocked call would raise inside
    # similar_vendor, where the catch-all turns it into "no suggestion" and the test would pass.
    with respx.mock:
        route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_answer_payload("none")))
        result = await duplicates.similar_vendor(db_session, name)

    assert route.call_count == 0
    assert result.suggestion is None


# --- similar_vendor: model tier, both settings on -----------------------------------


@pytest.fixture
async def _model_ready(db_session: AsyncSession) -> None:
    await _enable_duplicate_check(db_session)
    await _set_decision_base_url(db_session, "https://api.typesafe.ai")


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_model_question_options_and_state(db_session: AsyncSession) -> None:
    bambu = await vendor_db.create(db=db_session, name="Bambu Lab")
    polymaker = await vendor_db.create(db=db_session, name="Polymaker")
    route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_answer_payload("none")))

    await duplicates.similar_vendor(db_session, "Bambu")

    sent = json.loads(route.calls.last.request.content)
    assert sent["state"] == "Bambu"
    question = sent["questions"]["vendor"]
    assert question["criteria"] == {
        f"v{bambu.id}": "Bambu Lab",
        f"v{polymaker.id}": "Polymaker",
        "none": "None of these: a different manufacturer.",
    }


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_model_pick_at_or_above_threshold_is_suggested(db_session: AsyncSession) -> None:
    bambu = await vendor_db.create(db=db_session, name="Bambu Lab")
    respx.post(_DECISION_URL).mock(
        return_value=Response(
            200,
            json=_answer_payload(f"v{bambu.id}", probabilities={f"v{bambu.id}": duplicates.SUGGEST_MIN_PROBABILITY}),
        ),
    )

    result = await duplicates.similar_vendor(db_session, "Bambu")

    assert result.suggestion is not None
    assert result.suggestion.id == bambu.id
    assert result.suggestion.probability == duplicates.SUGGEST_MIN_PROBABILITY
    assert result.source == "model"


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_model_pick_below_threshold_gives_nothing(db_session: AsyncSession) -> None:
    bambu = await vendor_db.create(db=db_session, name="Bambu Lab")
    below = duplicates.SUGGEST_MIN_PROBABILITY - 0.01
    respx.post(_DECISION_URL).mock(
        return_value=Response(200, json=_answer_payload(f"v{bambu.id}", probabilities={f"v{bambu.id}": below})),
    )

    result = await duplicates.similar_vendor(db_session, "Bambu")

    assert result.suggestion is None


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_model_answers_none_gives_nothing(db_session: AsyncSession) -> None:
    await vendor_db.create(db=db_session, name="Bambu Lab")
    respx.post(_DECISION_URL).mock(return_value=Response(200, json=_answer_payload("none")))

    result = await duplicates.similar_vendor(db_session, "Totally Different Co")

    assert result.suggestion is None


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_model_http_500_gives_nothing_and_logs_a_warning(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await vendor_db.create(db=db_session, name="Bambu Lab")
    respx.post(_DECISION_URL).mock(return_value=Response(500))

    with caplog.at_level("WARNING"):
        result = await duplicates.similar_vendor(db_session, "Bambu")

    assert result.suggestion is None
    assert "Duplicate check" in caplog.text


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_exact_match_short_circuits_with_no_http_call(db_session: AsyncSession) -> None:
    await vendor_db.create(db=db_session, name="eSUN")
    route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_answer_payload("none")))

    result = await duplicates.similar_vendor(db_session, "ESUN")

    assert result.exact is not None
    assert route.call_count == 0


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_missing_probabilities_falls_back_to_confidence(db_session: AsyncSession) -> None:
    bambu = await vendor_db.create(db=db_session, name="Bambu Lab")
    respx.post(_DECISION_URL).mock(
        return_value=Response(200, json=_answer_payload(f"v{bambu.id}", confidence=0.8)),
    )

    result = await duplicates.similar_vendor(db_session, "Bambu")

    assert result.suggestion is not None
    assert result.suggestion.probability == 0.8


# --- Shortlisting: more than 50 vendors ---------------------------------------------


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_more_than_fifty_vendors_only_offers_fifty_including_the_closest(
    db_session: AsyncSession,
) -> None:
    closest = await vendor_db.create(db=db_session, name="Bambu Laboratory")
    for i in range(60):
        await vendor_db.create(db=db_session, name=f"Unrelated Co {i}")
    route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_answer_payload("none")))

    await duplicates.similar_vendor(db_session, "Bambu Lab")

    question = json.loads(route.calls.last.request.content)["questions"]["vendor"]
    offered_ids = [key for key in question["criteria"] if key != "none"]
    assert len(offered_ids) == duplicates._SHORTLIST  # noqa: SLF001
    assert f"v{closest.id}" in offered_ids


# --- _colours -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("color_hex", "multi_color_hexes", "expected"),
    [
        ("ff0000", None, ("ff0000",)),
        ("#FF0000", None, ("ff0000",)),
        ("ff0000ff", None, ("ff0000",)),  # RRGGBBAA: alpha is dropped
        (None, "ff0000,00ff00", ("ff0000", "00ff00")),
        (None, "ff0000, 00ff00", ("ff0000", "00ff00")),  # spaces around the comma
    ],
)
def test_colours_reads_known_formats(
    color_hex: str | None,
    multi_color_hexes: str | None,
    expected: tuple[str, ...],
) -> None:
    assert duplicates._colours(color_hex, multi_color_hexes) == expected  # noqa: SLF001


@pytest.mark.parametrize("color_hex", ["zz0000", "fff", ""])
def test_colours_invalid_hex_is_none(color_hex: str) -> None:
    assert duplicates._colours(color_hex, None) is None  # noqa: SLF001


def test_colours_nothing_given_is_none() -> None:
    assert duplicates._colours(None, None) is None  # noqa: SLF001


# --- colour_relation --------------------------------------------------------------------


def test_colour_relation_same_within_delta_e() -> None:
    assert duplicates.colour_relation(("ff0000",), ("fe0101",)) == "same colour"


def test_colour_relation_different_beyond_delta_e() -> None:
    assert duplicates.colour_relation(("ff0000",), ("00ff00",)) == "different colour"


@pytest.mark.parametrize(("a", "b"), [(None, ("ff0000",)), (("ff0000",), None), (None, None)])
def test_colour_relation_unknown_when_either_side_is_none(
    a: tuple[str, ...] | None,
    b: tuple[str, ...] | None,
) -> None:
    assert duplicates.colour_relation(a, b) == "colour unknown"


def test_colour_relation_different_lengths_are_different() -> None:
    assert duplicates.colour_relation(("ff0000",), ("ff0000", "00ff00")) == "different colour"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (("ff0000",), ("fe0101",)),
        (("ff0000",), ("00ff00",)),
        (("ff0000",), ("ff0000", "00ff00")),
        (None, ("ff0000",)),
        # CIE94 weights by the first colour's chroma; this pair falls either side of 3 by order.
        (("176cc5",), ("1566c8",)),
    ],
)
def test_colour_relation_is_symmetric(a: tuple[str, ...] | None, b: tuple[str, ...] | None) -> None:
    assert duplicates.colour_relation(a, b) == duplicates.colour_relation(b, a)


# --- similar_filament: exact tier -----------------------------------------------------


async def test_similar_filament_exact_match_ignores_case_punctuation_and_material_case(
    db_session: AsyncSession,
) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id,
        name="poly-lite pla!",
        material="pla",
        diameter=1.75,
        color_hex="fe0101",  # within delta E of ff0000: same colour
    )
    result = await duplicates.similar_filament(db_session, draft)

    assert result.exact is not None
    assert result.source == "exact"
    assert result.suggestion is None


async def test_similar_filament_no_match_when_colour_differs(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="00ff00"
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is None


async def test_similar_filament_no_match_when_material_differs(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PETG", diameter=1.75, color_hex="ff0000"
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is None


async def test_similar_filament_no_match_when_size_differs(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=2.85, color_hex="ff0000"
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is None


async def test_similar_filament_no_match_when_vendor_differs(db_session: AsyncSession) -> None:
    polymaker = await vendor_db.create(db=db_session, name="Polymaker")
    other = await vendor_db.create(db=db_session, name="eSUN")
    await _create_filament(
        db_session, vendor_id=polymaker.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=other.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is None


async def test_similar_filament_unknown_diameter_matches_either_size(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=None, color_hex="ff0000"
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is not None


async def test_similar_filament_both_colours_unknown_matches(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex=None
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex=None
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is not None


async def test_similar_filament_one_colour_known_one_unknown_does_not_match(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex=None
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is None


async def test_similar_filament_typed_vendor_name_matches_by_exact_key(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="E-Sun")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(vendor_name="ESUN", name="PLA", material="PLA", diameter=1.75, color_hex="ff0000")

    assert (await duplicates.similar_filament(db_session, draft)).exact is not None


async def test_similar_filament_no_vendor_on_either_side_matches(db_session: AsyncSession) -> None:
    await _create_filament(
        db_session, vendor_id=None, name="Generic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(name="Generic PLA", material="PLA", diameter=1.75, color_hex="ff0000")

    assert (await duplicates.similar_filament(db_session, draft)).exact is not None


async def test_similar_filament_blank_name_and_material_never_matches(db_session: AsyncSession) -> None:
    await _create_filament(db_session, vendor_id=None, name="", material="", diameter=1.75, color_hex="ff0000")

    draft = duplicates.FilamentDraft(name="", material="", diameter=1.75, color_hex="ff0000")

    result = await duplicates.similar_filament(db_session, draft)

    assert result.exact is None
    assert result.suggestion is None


async def test_similar_filament_needs_a_name_before_an_exact_match(db_session: AsyncSession) -> None:
    """Picking the material first must not flag every unnamed filament of that material."""
    await _create_filament(db_session, vendor_id=None, name=None, material="PLA", diameter=1.75, color_hex=None)
    await _create_filament(db_session, vendor_id=None, name="-", material="PETG", diameter=1.75, color_hex="000000")

    assert (await duplicates.similar_filament(db_session, duplicates.FilamentDraft(material="pla"))).exact is None
    punctuation_only = duplicates.FilamentDraft(name="  -- ", material="PETG", color_hex="000000")
    assert (await duplicates.similar_filament(db_session, punctuation_only)).exact is None


async def test_similar_filament_punctuation_only_vendor_name_matches_nothing(db_session: AsyncSession) -> None:
    await _create_filament(
        db_session, vendor_id=None, name="Generic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_name="--", name="Generic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    assert (await duplicates.similar_filament(db_session, draft)).exact is None


async def test_similar_filament_exact_match_oldest_wins(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    first = await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    result = await duplicates.similar_filament(db_session, draft)

    assert result.exact is not None
    assert result.exact.id == first.id


async def test_similar_filament_exact_match_excludes_the_edited_filament(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Polymaker")
    edited = await _create_filament(
        db_session, vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="PolyLite PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    result = await duplicates.similar_filament(db_session, draft, exclude_id=edited.id)

    assert result.exact is None


# --- similar_filament: the model tier is gated on both settings ----------------------


async def test_filament_model_not_called_when_toggle_off_even_with_url_set(db_session: AsyncSession) -> None:
    await _set_decision_base_url(db_session, "https://api.typesafe.ai")
    await _create_filament(db_session, name="Bambu PLA Basic", material="PLA")

    with respx.mock:
        route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))
        draft = duplicates.FilamentDraft(name="Bambu PLA", material="PLA", diameter=1.75, color_hex="ff0000")
        result = await duplicates.similar_filament(db_session, draft)

    assert route.call_count == 0
    assert result.suggestion is None


async def test_filament_model_not_called_when_url_unset_even_with_toggle_on(db_session: AsyncSession) -> None:
    await _enable_duplicate_check(db_session)
    await _create_filament(db_session, name="Bambu PLA Basic", material="PLA")

    with respx.mock:
        route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))
        draft = duplicates.FilamentDraft(name="Bambu PLA", material="PLA", diameter=1.75, color_hex="ff0000")
        result = await duplicates.similar_filament(db_session, draft)

    assert route.call_count == 0
    assert result.suggestion is None


@pytest.mark.parametrize("name", ["-", "a"])
async def test_filament_model_not_called_for_a_name_too_short_once_normalized(
    db_session: AsyncSession,
    name: str,
) -> None:
    await _enable_duplicate_check(db_session)
    await _set_decision_base_url(db_session, "https://api.typesafe.ai")
    await _create_filament(db_session, name="Bambu PLA Basic", material="PLA")

    with respx.mock:
        route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))
        draft = duplicates.FilamentDraft(name=name, material="PLA", diameter=1.75, color_hex="ff0000")
        result = await duplicates.similar_filament(db_session, draft)

    assert route.call_count == 0
    assert result.suggestion is None


# --- similar_filament: model tier, both settings on -----------------------------------


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_model_question_options_state_colour_relation(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    same_colour = await _create_filament(
        db_session,
        vendor_id=vendor.id,
        name="Bambu PLA Basic",
        material="PLA",
        diameter=1.75,
        color_hex="ff0000",
    )
    unknown_colour = await _create_filament(
        db_session,
        vendor_id=vendor.id,
        name="Bambu PLA Basic White",
        material="PLA",
        diameter=1.75,
        color_hex=None,
    )
    route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))

    # Word order differs from both candidates' names, so this is not an exact match and the
    # model tier runs; the words themselves are the same, so it still scores as a candidate.
    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="Bambu Basic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    await duplicates.similar_filament(db_session, draft)

    sent = json.loads(route.calls.last.request.content)
    assert "color_hex" not in sent["state"]
    assert not any("colour" in key or "color" in key for key in sent["state"])
    question = sent["questions"]["filament"]
    assert question["criteria"][f"f{same_colour.id}"].endswith("; same colour")
    assert question["criteria"][f"f{unknown_colour.id}"].endswith("; colour unknown")
    assert question["criteria"]["none"] == "None of these: a different product."


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_model_never_offers_a_different_colour_candidate(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    same_colour = await _create_filament(
        db_session,
        vendor_id=vendor.id,
        name="Bambu PLA Basic",
        material="PLA",
        diameter=1.75,
        color_hex="ff0000",
    )
    different_colour = await _create_filament(
        db_session,
        vendor_id=vendor.id,
        name="Bambu PLA Basic",
        material="PLA",
        diameter=1.75,
        color_hex="00ff00",
    )
    route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="Bambu Basic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    await duplicates.similar_filament(db_session, draft)

    offered_ids = set(json.loads(route.calls.last.request.content)["questions"]["filament"]["criteria"])
    assert f"f{same_colour.id}" in offered_ids
    assert f"f{different_colour.id}" not in offered_ids


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_model_never_suggested_when_only_colour_differs_even_with_an_identical_name(
    db_session: AsyncSession,
) -> None:
    """Same wording, different colour: never even asked, let alone suggested."""
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    await _create_filament(
        db_session,
        vendor_id=vendor.id,
        name="Bambu PLA Basic",
        material="PLA",
        diameter=1.75,
        color_hex="00ff00",
    )
    route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="Bambu PLA Basic", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    result = await duplicates.similar_filament(db_session, draft)

    assert route.call_count == 0
    assert result.suggestion is None


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_model_pick_at_or_above_threshold_is_suggested(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    bambu = await _create_filament(
        db_session, vendor_id=vendor.id, name="Bambu PLA Basic", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    respx.post(_DECISION_URL).mock(
        return_value=Response(
            200,
            json=_filament_answer_payload(
                f"f{bambu.id}",
                probabilities={f"f{bambu.id}": duplicates.SUGGEST_MIN_PROBABILITY},
            ),
        ),
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="Bambu Basic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    result = await duplicates.similar_filament(db_session, draft)

    assert result.suggestion is not None
    assert result.suggestion.id == bambu.id
    assert result.suggestion.probability == duplicates.SUGGEST_MIN_PROBABILITY
    assert result.source == "model"


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_model_pick_below_threshold_gives_nothing(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    bambu = await _create_filament(
        db_session, vendor_id=vendor.id, name="Bambu PLA Basic", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    below = duplicates.SUGGEST_MIN_PROBABILITY - 0.01
    respx.post(_DECISION_URL).mock(
        return_value=Response(
            200, json=_filament_answer_payload(f"f{bambu.id}", probabilities={f"f{bambu.id}": below})
        ),
    )

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="Bambu Basic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    result = await duplicates.similar_filament(db_session, draft)

    assert result.suggestion is None


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_model_answers_none_gives_nothing(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="Bambu PLA Basic", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="Totally Different Product", material="ABS", diameter=1.75, color_hex="0000ff"
    )
    result = await duplicates.similar_filament(db_session, draft)

    assert result.suggestion is None


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_model_http_500_gives_nothing_and_logs_a_warning(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="Bambu PLA Basic", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    respx.post(_DECISION_URL).mock(return_value=Response(500))

    with caplog.at_level("WARNING"):
        draft = duplicates.FilamentDraft(
            vendor_id=vendor.id, name="Bambu Basic PLA", material="PLA", diameter=1.75, color_hex="ff0000"
        )
        result = await duplicates.similar_filament(db_session, draft)

    assert result.suggestion is None
    assert "Duplicate check" in caplog.text


@respx.mock
@pytest.mark.usefixtures("_model_ready")
async def test_filament_exact_match_short_circuits_with_no_http_call(db_session: AsyncSession) -> None:
    vendor = await vendor_db.create(db=db_session, name="Bambu Lab")
    await _create_filament(
        db_session, vendor_id=vendor.id, name="Bambu PLA Basic", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    route = respx.post(_DECISION_URL).mock(return_value=Response(200, json=_filament_answer_payload("none")))

    draft = duplicates.FilamentDraft(
        vendor_id=vendor.id, name="Bambu PLA Basic", material="PLA", diameter=1.75, color_hex="ff0000"
    )
    result = await duplicates.similar_filament(db_session, draft)

    assert result.exact is not None
    assert route.call_count == 0
