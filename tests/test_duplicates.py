"""Tests for the manufacturer duplicate check (spoolman/duplicates.py).

Oracle strategy:
  * The exact tier is pure code -- normalize_name/exact_key/_exact_vendor are asserted
    directly, and similar_vendor's exact path through a throwaway DB session.
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

    with respx.mock:
        result = await duplicates.similar_vendor(db_session, "Bambu")

    assert result.suggestion is None


async def test_model_not_called_when_url_unset_even_with_toggle_on(db_session: AsyncSession) -> None:
    await _enable_duplicate_check(db_session)
    await vendor_db.create(db=db_session, name="Bambu Lab")

    with respx.mock:
        result = await duplicates.similar_vendor(db_session, "Bambu")

    assert result.suggestion is None


@pytest.mark.parametrize("name", ["---", "a-"])
async def test_model_not_called_for_a_name_too_short_once_normalized(db_session: AsyncSession, name: str) -> None:
    await _enable_duplicate_check(db_session)
    await _set_decision_base_url(db_session, "https://api.typesafe.ai")
    await vendor_db.create(db=db_session, name="Bambu Lab")

    with respx.mock:
        result = await duplicates.similar_vendor(db_session, name)

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
