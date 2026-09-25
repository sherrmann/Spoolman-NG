"""Unit tests for the decision-model client prototype (spoolman.decision).

Oracle strategy: exercised through its only boundary -- the outbound HTTP request to
``{base_url}/v1/systemone`` -- mocked with respx at the transport layer, exactly like
tests/test_ai.py. Assertions are on the observable request body/headers and on the parsed
ChoiceAnswer, never on internals.
"""

import httpx
import pytest
import respx
from httpx import Response

from spoolman import decision
from spoolman.decision import ChoiceAnswer, DecisionConfig, DecisionError

_ENV_NAMES = (decision.ENV_BASE_URL, decision.ENV_API_KEY, decision.ENV_MODEL)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the SPOOLMAN_AI_DECISION_* env between tests."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


# --- resolve_config ------------------------------------------------------------------


def test_resolve_config_unset_is_none() -> None:
    assert decision.resolve_config() is None


def test_resolve_config_blank_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "   ")
    assert decision.resolve_config() is None


def test_resolve_config_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai/")
    config = decision.resolve_config()
    assert config is not None
    assert config.base_url == "https://api.typesafe.ai"


def test_resolve_config_rejects_non_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "ftp://api.typesafe.ai")
    assert decision.resolve_config() is None


def test_resolve_config_defaults_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    config = decision.resolve_config()
    assert config is not None
    assert config.model == decision.DEFAULT_MODEL
    assert config.api_key is None


def test_resolve_config_reads_model_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    monkeypatch.setenv(decision.ENV_MODEL, "jev-1.13")
    monkeypatch.setenv(decision.ENV_API_KEY, "sk-secret")
    config = decision.resolve_config()
    assert config is not None
    assert config.model == "jev-1.13"
    assert config.api_key == "sk-secret"


# --- choice_question -------------------------------------------------------------------


def test_choice_question_builds_the_expected_shape() -> None:
    question = decision.choice_question("Which one?", {"a": "A", "b": "B"})
    assert question == {"type": "choice", "instructions": "Which one?", "criteria": {"a": "A", "b": "B"}}


def test_choice_question_rejects_fewer_than_two_options() -> None:
    with pytest.raises(ValueError, match="2 to 255"):
        decision.choice_question("Which one?", {"a": "A"})


def test_choice_question_rejects_more_than_255_options() -> None:
    options = {f"o{i}": str(i) for i in range(256)}
    with pytest.raises(ValueError, match="2 to 255"):
        decision.choice_question("Which one?", options)


def test_choice_question_accepts_255_options() -> None:
    options = {f"o{i}": str(i) for i in range(255)}
    question = decision.choice_question("Which one?", options)
    assert len(question["criteria"]) == 255


# --- ask_choices: request shape -------------------------------------------------------


_CONFIG = DecisionConfig(base_url="https://api.typesafe.ai", model="jev-1.13")
_QUESTIONS = {"q1": decision.choice_question("Which?", {"a": "A", "b": "B"})}


def _answer_payload(qid: str = "q1", choice: str = "a", probabilities: dict | None = None) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {
            qid: {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities if probabilities is not None else {"a": 0.9, "b": 0.1},
                "confidence": 0.8,
            },
        },
        "usage": {},
    }


@respx.mock
async def test_ask_choices_sends_the_exact_body_and_bearer_header() -> None:
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(200, json=_answer_payload()))
    config = DecisionConfig(base_url="https://api.typesafe.ai", model="jev-1.13", api_key="sk-secret")

    await decision.ask_choices(config, {"vendor": "Prusa"}, _QUESTIONS)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-secret"
    import json as _json  # noqa: PLC0415

    assert _json.loads(request.content) == {
        "state": {"vendor": "Prusa"},
        "model": "jev-1.13",
        "questions": _QUESTIONS,
    }


@respx.mock
async def test_ask_choices_sends_no_authorization_header_without_a_key() -> None:
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(200, json=_answer_payload()))

    await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)

    assert "Authorization" not in route.calls.last.request.headers


# --- ask_choices: parsing --------------------------------------------------------------


@respx.mock
async def test_ask_choices_parses_choice_probabilities_and_confidence() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_answer_payload(choice="b", probabilities={"a": 0.2, "b": 0.8})),
    )

    answers = await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)

    assert answers == {"q1": ChoiceAnswer(choice="b", probabilities={"a": 0.2, "b": 0.8}, confidence=0.8)}


@respx.mock
async def test_ask_choices_ignores_probability_keys_not_offered() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_answer_payload(probabilities={"a": 0.9, "z": 0.1})),
    )

    answers = await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)

    assert answers["q1"].probabilities == {"a": 0.9}


@respx.mock
async def test_ask_choices_ignores_non_numeric_probability_values() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_answer_payload(probabilities={"a": "high", "b": 0.1})),
    )

    answers = await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)

    assert answers["q1"].probabilities == {"b": 0.1}


# --- ask_choices: failure modes ---------------------------------------------------------


@pytest.mark.parametrize("status", [401, 422, 529])
@respx.mock
async def test_ask_choices_raises_on_http_error_status(status: int) -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(status))
    with pytest.raises(DecisionError, match=str(status)):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_timeout() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(DecisionError, match="timed out"):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_non_json_body() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(200, text="<html>hi</html>"))
    with pytest.raises(DecisionError):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_missing_answers_key() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(200, json={"model": "jev-1.13.0"}))
    with pytest.raises(DecisionError):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_when_an_answer_id_is_missing() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json={"model": "jev-1.13.0", "answers": {}, "usage": {}}),
    )
    with pytest.raises(DecisionError, match="q1"):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_answer_of_the_wrong_type() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(
            200,
            json={"model": "jev-1.13.0", "answers": {"q1": {"type": "number", "value": 1}}, "usage": {}},
        ),
    )
    with pytest.raises(DecisionError, match="not a choice"):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_a_choice_that_was_not_offered() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_answer_payload(choice="z")),
    )
    with pytest.raises(DecisionError, match="not offered"):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)
