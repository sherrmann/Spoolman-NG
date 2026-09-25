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

Configuration is environment-only while this is a prototype:

* ``SPOOLMAN_AI_DECISION_BASE_URL`` (required to enable), e.g. ``https://api.typesafe.ai``
* ``SPOOLMAN_AI_DECISION_API_KEY``
* ``SPOOLMAN_AI_DECISION_MODEL`` (default ``jev-latest``)

Every failure raises :class:`DecisionError`; callers treat that as "no opinion" and keep their
own heuristic result, so a slow or broken endpoint can never break a feature that works
without it.
"""

import json
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

ENV_BASE_URL = "SPOOLMAN_AI_DECISION_BASE_URL"
ENV_API_KEY = "SPOOLMAN_AI_DECISION_API_KEY"
ENV_MODEL = "SPOOLMAN_AI_DECISION_MODEL"
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
    api_key: str | None = None


@dataclass(frozen=True)
class ChoiceAnswer:
    """One answered Choice question."""

    choice: str
    probabilities: dict[str, float]
    confidence: float | None


def _env(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value or None


def resolve_config() -> DecisionConfig | None:
    """Return the configured decision endpoint, or None when it is not configured or unusable."""
    base_url = _env(ENV_BASE_URL)
    if base_url is None:
        return None
    base_url = base_url.rstrip("/")
    if urlsplit(base_url).scheme not in ("http", "https"):
        logger.warning("Ignoring %s: the URL must start with http:// or https://.", ENV_BASE_URL)
        return None
    return DecisionConfig(base_url=base_url, model=_env(ENV_MODEL) or DEFAULT_MODEL, api_key=_env(ENV_API_KEY))


def choice_question(instructions: str, options: dict[str, str]) -> dict:
    """Build a Choice question: ``options`` maps each answer key to what that answer means."""
    if not MIN_CHOICE_OPTIONS <= len(options) <= MAX_CHOICE_OPTIONS:
        msg = f"A choice question needs {MIN_CHOICE_OPTIONS} to {MAX_CHOICE_OPTIONS} options, got {len(options)}."
        raise ValueError(msg)
    return {"type": "choice", "instructions": instructions, "criteria": options}


def _parse_choice(raw: object, options: dict[str, str]) -> ChoiceAnswer:
    if not isinstance(raw, dict) or raw.get("type") != "choice":
        raise DecisionError("The decision endpoint returned an answer that is not a choice.")
    choice = raw.get("choice")
    if choice not in options:
        raise DecisionError("The decision endpoint chose an option that was not offered.")
    raw_probs = raw.get("probabilities")
    probabilities: dict[str, float] = {}
    if isinstance(raw_probs, dict):
        for key, value in raw_probs.items():
            if key in options and isinstance(value, int | float) and not isinstance(value, bool):
                probabilities[key] = float(value)
    confidence = raw.get("confidence")
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        confidence = None
    return ChoiceAnswer(choice=choice, probabilities=probabilities, confidence=confidence)


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
    that names an option that was not offered.
    """
    payload = {"state": state, "model": config.model, "questions": questions}
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    url = f"{config.base_url}/v1/systemone"
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise DecisionError(f"The decision endpoint timed out after {timeout:g} s.") from exc
    except httpx.HTTPError as exc:
        raise DecisionError(f"The decision endpoint is unreachable: {exc.__class__.__name__}.") from exc

    if response.status_code != httpx.codes.OK:
        raise DecisionError(f"The decision endpoint returned HTTP {response.status_code}.")
    try:
        answers = response.json()["answers"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DecisionError("The decision endpoint returned an unexpected response shape.") from exc
    if not isinstance(answers, dict):
        raise DecisionError("The decision endpoint returned an unexpected response shape.")

    result: dict[str, ChoiceAnswer] = {}
    for qid, question in questions.items():
        if qid not in answers:
            raise DecisionError(f"The decision endpoint did not answer '{qid}'.")
        result[qid] = _parse_choice(answers[qid], question["criteria"])
    return result
