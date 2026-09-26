"""Decision-model client (prototype): typed questions answered with probabilities.

A decision model such as TypeSafe's Jev does not generate text. It takes a *state* (the data
to judge) and a set of typed questions, and returns one typed answer per question with
probabilities. Spoolman uses it only for choices among options it already has, such as
which of five candidate filaments a spool label describes.

The wire format is TypeSafe's System One API, ``POST {base_url}/v1/systemone``. TypeSafe
serves it at ``https://api.typesafe.ai`` and OpenRouter at ``https://openrouter.ai/api``
(model ``jev-1.13``); a LiteLLM proxy passes it through under ``/typesafe``. Requests
through an OpenAI-style ``/chat/completions`` router cannot carry typed questions, so this is
deliberately separate from :mod:`spoolman.ai`.

It is configured in Settings -> AI, or by environment variables, which win field by field
(the storage and env-over-DB resolution live in :mod:`spoolman.ai`):

* ``SPOOLMAN_AI_DECISION_BASE_URL`` (required to enable), e.g. ``https://api.typesafe.ai``
* ``SPOOLMAN_AI_DECISION_API_KEY``
* ``SPOOLMAN_AI_DECISION_MODEL`` (default ``jev-latest``)

Every failure raises :class:`DecisionError`; callers treat that as "no opinion" and keep their
own heuristic result, so a slow or broken endpoint can never break a feature that works
without it.
"""

import asyncio
import logging
import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai

logger = logging.getLogger(__name__)

ENV_BASE_URL = ai.ENV_DECISION_BASE_URL
ENV_API_KEY = ai.ENV_DECISION_API_KEY
ENV_MODEL = ai.ENV_DECISION_MODEL
DEFAULT_MODEL = "jev-latest"

#: The model answers in about 100 ms. Anything much slower costs the user more than the
#: better ordering is worth, so give up early and keep the heuristic order.
_TIMEOUT = 5.0
#: How many options a Choice question may have (System One API limits).
MIN_CHOICE_OPTIONS = 2
MAX_CHOICE_OPTIONS = 255


class DecisionError(Exception):
    """A decision request failed or was not configured; the message is safe to log."""


@dataclass(frozen=True)
class DecisionConfig:
    """Effective decision-model configuration."""

    base_url: str
    model: str
    #: Left out of repr so an accidental ``%r`` in a log line cannot print it.
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ChoiceAnswer:
    """One answered Choice question."""

    choice: str
    probabilities: dict[str, float]
    confidence: float | None


def _env(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value or None


def validated_config(
    base_url: str | None,
    api_key: str | None,
    model: str | None,
    *,
    source: str = "the decision-model base URL",
) -> DecisionConfig | None:
    """Return a usable config from raw values, or None when unset or unusable.

    ``source`` names where the base URL came from, for the log line that says why it was ignored.
    """
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        _ = parts.port  # raises ValueError for a port that is not a number
    except ValueError:
        logger.warning("Ignoring %s: it is not a valid URL.", source)
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        logger.warning("Ignoring %s: the URL must start with http:// or https:// and name a host.", source)
        return None
    api_key = (api_key or "").strip() or None
    if api_key is not None and not api_key.isascii():
        # An HTTP header cannot carry it, so every request would fail; say why here instead.
        # The key's name is spelt out rather than passed in: code scanning treats any value
        # named like a key as the secret itself.
        logger.warning("Ignoring the decision endpoint: its API key contains non-ASCII characters.")
        return None
    return DecisionConfig(base_url=base_url, model=(model or "").strip() or DEFAULT_MODEL, api_key=api_key)


def resolve_env_config() -> DecisionConfig | None:
    """Return the endpoint set by environment variables alone, without opening the database.

    For the evaluation scripts; the server uses :func:`resolve_config`.
    """
    return validated_config(_env(ENV_BASE_URL), _env(ENV_API_KEY), _env(ENV_MODEL), source=ENV_BASE_URL)


def from_ai_config(config: ai.AIConfig) -> DecisionConfig | None:
    """Return the decision endpoint from a resolved AI config, or None when unset or unusable."""
    source = ENV_BASE_URL if config.sources.get("decision_base_url") == "env" else "the decision-model base URL setting"
    return validated_config(config.decision_base_url, config.decision_api_key, config.decision_model, source=source)


async def resolve_config(db: AsyncSession) -> DecisionConfig | None:
    """Return the configured decision endpoint (env over Settings), or None when unset or unusable."""
    return from_ai_config(await ai.resolve_config(db))


def choice_question(instructions: str, options: dict[str, str]) -> dict:
    """Build a Choice question: ``options`` maps each answer key to what that answer means."""
    if not MIN_CHOICE_OPTIONS <= len(options) <= MAX_CHOICE_OPTIONS:
        msg = f"A choice question needs {MIN_CHOICE_OPTIONS} to {MAX_CHOICE_OPTIONS} options, got {len(options)}."
        raise ValueError(msg)
    return {"type": "choice", "instructions": instructions, "criteria": options}


def _unit_interval(value: object) -> float | None:
    """Return ``value`` as a float if it is a finite number in [0, 1], else None.

    JSON parsing accepts ``NaN`` and ``1e400``; neither may reach a sort key or the API response.
    """
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _parse_choice(raw: object, options: dict[str, str]) -> ChoiceAnswer:
    if not isinstance(raw, dict) or raw.get("type") != "choice":
        raise DecisionError("The decision endpoint returned an answer that is not a choice.")
    choice = raw.get("choice")
    if not isinstance(choice, str) or choice not in options:
        raise DecisionError("The decision endpoint chose an option that was not offered.")
    raw_probs = raw.get("probabilities")
    probabilities: dict[str, float] = {}
    if isinstance(raw_probs, dict):
        for key, value in raw_probs.items():
            number = _unit_interval(value)
            if key in options and number is not None:
                probabilities[key] = number
    return ChoiceAnswer(choice=choice, probabilities=probabilities, confidence=_unit_interval(raw.get("confidence")))


async def ask_choices(
    config: DecisionConfig,
    state: str | dict | list,
    questions: dict[str, dict],
    *,
    timeout: float = _TIMEOUT,
) -> dict[str, ChoiceAnswer]:
    """Ask several Choice questions about one state in a single request.

    ``questions`` maps a local id to a question built with :func:`choice_question`. Returns
    one :class:`ChoiceAnswer` per id. Raises DecisionError on any failure, including an answer
    that names an option that was not offered. ``timeout`` bounds the whole request, not
    each phase of it.
    """
    payload = {"state": state, "model": config.model, "questions": questions}
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    url = f"{config.base_url}/v1/systemone"

    async def _post() -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            return await client.post(url, json=payload)

    try:
        response = await asyncio.wait_for(_post(), timeout)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise DecisionError(f"The decision endpoint timed out after {timeout:g} s.") from exc
    except (httpx.HTTPError, httpx.InvalidURL, UnicodeError) as exc:
        # InvalidURL is not an HTTPError; UnicodeError covers a header or URL httpx cannot encode.
        raise DecisionError(f"The decision endpoint is unreachable: {exc.__class__.__name__}.") from exc

    if response.status_code != httpx.codes.OK:
        raise DecisionError(f"The decision endpoint returned HTTP {response.status_code}.")
    try:
        answers = response.json()["answers"]
    except (ValueError, KeyError, TypeError) as exc:  # ValueError covers JSON and UTF-8 decode errors
        raise DecisionError("The decision endpoint returned an unexpected response shape.") from exc
    if not isinstance(answers, dict):
        raise DecisionError("The decision endpoint returned an unexpected response shape.")

    result: dict[str, ChoiceAnswer] = {}
    for qid, question in questions.items():
        if qid not in answers:
            raise DecisionError(f"The decision endpoint did not answer '{qid}'.")
        result[qid] = _parse_choice(answers[qid], question["criteria"])
    return result
