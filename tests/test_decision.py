"""Unit tests for the decision-model client prototype (spoolman.decision).

Oracle strategy: exercised through its only boundary -- the outbound HTTP request to
``{base_url}/v1/systemone`` -- mocked with respx at the transport layer, exactly like
tests/test_ai.py. Assertions are on the observable request body/headers and on the parsed
ChoiceAnswer, never on internals.
"""

import asyncio
import json
import time

import httpx
import pytest
import respx
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import decision
from spoolman.database import setting as setting_db
from spoolman.decision import ChoiceAnswer, DecisionConfig, DecisionError
from spoolman.settings import SETTINGS

_ENV_NAMES = (decision.ENV_BASE_URL, decision.ENV_API_KEY, decision.ENV_MODEL)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the SPOOLMAN_AI_DECISION_* env between tests."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


# --- resolve_env_config ----------------------------------------------------------------


def test_resolve_env_config_unset_is_none() -> None:
    assert decision.resolve_env_config() is None


def test_resolve_env_config_blank_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "   ")
    assert decision.resolve_env_config() is None


def test_resolve_env_config_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai/")
    config = decision.resolve_env_config()
    assert config is not None
    assert config.base_url == "https://api.typesafe.ai"


def test_resolve_env_config_rejects_non_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "ftp://api.typesafe.ai")
    assert decision.resolve_env_config() is None


def test_resolve_env_config_defaults_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    config = decision.resolve_env_config()
    assert config is not None
    assert config.model == decision.DEFAULT_MODEL
    assert config.api_key is None


def test_resolve_env_config_reads_model_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    monkeypatch.setenv(decision.ENV_MODEL, "jev-1.13")
    monkeypatch.setenv(decision.ENV_API_KEY, "sk-secret")
    config = decision.resolve_env_config()
    assert config is not None
    assert config.model == "jev-1.13"
    assert config.api_key == "sk-secret"


def test_resolve_env_config_rejects_invalid_ipv6_host(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "http://[::1")
    with caplog.at_level("WARNING"):
        assert decision.resolve_env_config() is None
    assert "not a valid URL" in caplog.text


@pytest.mark.parametrize("base_url", ["http://a:notaport", "http://a:99999"])
def test_resolve_env_config_rejects_an_unparsable_port(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    base_url: str,
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, base_url)
    with caplog.at_level("WARNING"):
        assert decision.resolve_env_config() is None
    assert "not a valid URL" in caplog.text


def test_resolve_env_config_rejects_a_url_with_no_host(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "http://")
    with caplog.at_level("WARNING"):
        assert decision.resolve_env_config() is None
    assert "name a host" in caplog.text


def test_resolve_env_config_rejects_a_non_ascii_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    monkeypatch.setenv(decision.ENV_API_KEY, "kéy")
    with caplog.at_level("WARNING"):
        assert decision.resolve_env_config() is None
    assert "non-ASCII" in caplog.text
    assert "kéy" not in caplog.text


# --- validated_config --------------------------------------------------------------------


def test_validated_config_names_the_given_source_in_the_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        assert decision.validated_config("ftp://host", None, None, source="the decision-model base URL setting") is None
    assert "the decision-model base URL setting" in caplog.text


def test_validated_config_strips_the_api_key() -> None:
    config = decision.validated_config("https://api.typesafe.ai", "  sk-secret  ", None)
    assert config is not None
    assert config.api_key == "sk-secret"


def test_validated_config_blank_model_uses_the_default() -> None:
    config = decision.validated_config("https://api.typesafe.ai", None, "   ")
    assert config is not None
    assert config.model == decision.DEFAULT_MODEL


def test_decision_config_repr_never_shows_the_api_key() -> None:
    assert "sk-x" not in repr(DecisionConfig(base_url="https://api.typesafe.ai", model="m", api_key="sk-x"))


# --- resolve_config: env-over-DB, via ai.resolve_config ---------------------------------


async def _store_decision_setting(db_session: AsyncSession, key: str, value: str) -> None:
    await setting_db.update(db=db_session, definition=SETTINGS[key], value=json.dumps(value))


async def test_resolve_config_db_only(db_session: AsyncSession) -> None:
    await _store_decision_setting(db_session, "ai_decision_base_url", "https://db.example.com")
    await _store_decision_setting(db_session, "ai_decision_model", "jev-db")

    config = await decision.resolve_config(db_session)

    assert config is not None
    assert config.base_url == "https://db.example.com"
    assert config.model == "jev-db"


async def test_resolve_config_env_wins_per_field_over_db(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _store_decision_setting(db_session, "ai_decision_base_url", "https://db.example.com")
    await _store_decision_setting(db_session, "ai_decision_model", "jev-db")
    monkeypatch.setenv(decision.ENV_MODEL, "jev-env")

    config = await decision.resolve_config(db_session)

    assert config is not None
    # base_url still comes from the DB, model is overridden by the env var.
    assert config.base_url == "https://db.example.com"
    assert config.model == "jev-env"


async def test_resolve_config_an_invalid_db_url_returns_none_and_names_the_setting(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _store_decision_setting(db_session, "ai_decision_base_url", "ftp://db.example.com")

    with caplog.at_level("WARNING"):
        config = await decision.resolve_config(db_session)

    assert config is None
    assert "the decision-model base URL setting" in caplog.text
    assert decision.ENV_BASE_URL not in caplog.text


async def test_resolve_config_nothing_stored_is_none(db_session: AsyncSession) -> None:
    assert await decision.resolve_config(db_session) is None


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

    assert json.loads(request.content) == {
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


@respx.mock
async def test_ask_choices_drops_non_finite_and_out_of_range_probabilities_and_confidence() -> None:
    """NaN, +-inf, out-of-[0,1] numbers and booleans must never reach a sort key or the answer."""
    questions = {
        "q1": decision.choice_question(
            "Which?",
            {"a": "A", "b": "B", "c": "C", "d": "D", "e": "E", "f": "F"},
        ),
    }
    # A raw JSON string, since json.dumps() cannot be relied on to reproduce every one of these
    # (json.loads() accepts both NaN and out-of-range exponents such as 1e400, which becomes inf).
    body = (
        '{"model": "jev-1.13.0", "answers": {"q1": {"type": "choice", "choice": "a", '
        '"probabilities": {"a": NaN, "b": 1e400, "c": -0.1, "d": 1.5, "e": true, "f": 0.5}, '
        '"confidence": NaN}}, "usage": {}}'
    )
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, content=body, headers={"content-type": "application/json"}),
    )

    answers = await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, questions)

    assert answers["q1"].probabilities == {"f": 0.5}
    assert answers["q1"].confidence is None


# --- ask_choices: failure modes ---------------------------------------------------------


@pytest.mark.parametrize("status", [401, 422, 429, 529])
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
async def test_ask_choices_raises_when_the_whole_request_overruns_the_timeout() -> None:
    """``timeout`` bounds the whole request, via asyncio.wait_for, not just the HTTP phase."""

    async def _slow(request: httpx.Request) -> Response:  # noqa: ARG001
        await asyncio.sleep(1)
        return Response(200, json=_answer_payload())

    respx.post("https://api.typesafe.ai/v1/systemone").mock(side_effect=_slow)

    start = time.monotonic()
    with pytest.raises(DecisionError, match="timed out"):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS, timeout=0.05)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5


@respx.mock
async def test_ask_choices_raises_on_invalid_url_from_the_transport() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(side_effect=httpx.InvalidURL("bad url"))
    with pytest.raises(DecisionError):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_a_unicode_encode_error_from_the_transport() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        side_effect=UnicodeEncodeError("ascii", "café", 0, 1, "ordinal not in range(128)"),
    )
    with pytest.raises(DecisionError):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_non_json_body() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(200, text="<html>hi</html>"))
    with pytest.raises(DecisionError):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)


@respx.mock
async def test_ask_choices_raises_on_undecodable_bytes() -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(200, content=b"\xff\xfe\xfa"))
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


@pytest.mark.parametrize("choice", [["c1"], {"a": 1}])
@respx.mock
async def test_ask_choices_raises_on_a_choice_of_the_wrong_type(choice: object) -> None:
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(200, json=_answer_payload(choice=choice)),
    )
    with pytest.raises(DecisionError):
        await decision.ask_choices(_CONFIG, {"vendor": "Prusa"}, _QUESTIONS)
