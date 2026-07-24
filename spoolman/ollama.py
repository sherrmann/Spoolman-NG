"""Managed Ollama model pull (#364, F2).

When the configured endpoint is an Ollama server, Spoolman can help get the right models
onto it: list what is installed and drive Ollama's own streaming pull API with progress.
The principle from #364 is **provision, don't embed** — Spoolman never runs inference and
never manages the Ollama runtime; it only calls Ollama's HTTP API to list and pull models,
exactly what a person could do with ``ollama pull`` themselves.

Ollama serves its OpenAI-compatible surface under ``/v1`` but its native model API (tags,
pull) lives at the origin root, so both helpers derive that origin from the configured base
URL — reusing the same rule the capability probe uses.
"""

import json
import logging
from collections.abc import AsyncIterator

import httpx

from spoolman.ai import AIConfig, AIRequestError, _ollama_origin

logger = logging.getLogger(__name__)

#: Listing tags is quick; a pull can take many minutes, so it gets no overall deadline —
#: only a generous connect timeout, with the read stream left open for the download.
_LIST_TIMEOUT = 15.0
_PULL_TIMEOUT = httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0)


def ollama_origin(config: AIConfig) -> str | None:
    """Return the Ollama origin for the configured endpoint, or None if it isn't one."""
    if not config.base_url:
        return None
    return _ollama_origin(config.base_url)


def _auth_headers(config: AIConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}


async def list_installed_models(config: AIConfig) -> list[str] | None:
    """List models installed on the configured Ollama server, or None if it isn't one.

    ``_ollama_origin`` only strips ``/v1`` — it can't tell Ollama from any other
    OpenAI-compatible endpoint — so the real test is whether ``/api/tags`` answers with
    Ollama's shape. A non-Ollama endpoint (a 4xx, or a 200 that isn't Ollama-shaped)
    returns None; a genuine outage or server error (5xx / connection failure) raises
    AIRequestError so the caller can surface it.
    """
    origin = ollama_origin(config)
    if origin is None:
        return None
    async with httpx.AsyncClient(timeout=_LIST_TIMEOUT, headers=_auth_headers(config)) as client:
        try:
            response = await client.get(f"{origin}/api/tags")
        except httpx.HTTPError as exc:
            raise AIRequestError(f"Ollama is unreachable: {exc.__class__.__name__}.") from exc
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise AIRequestError(f"Ollama returned HTTP {response.status_code} for the model list.")
        if response.status_code != httpx.codes.OK:
            return None
        try:
            models = response.json().get("models")
        except (json.JSONDecodeError, AttributeError):
            return None
    if not isinstance(models, list):
        return None
    return sorted(model["name"] for model in models if isinstance(model, dict) and "name" in model)


async def pull_model(config: AIConfig, model: str) -> AsyncIterator[dict]:
    """Stream progress dicts from Ollama's ``/api/pull`` while it downloads ``model``.

    Yields Ollama's own progress objects verbatim (``status`` plus ``total``/``completed``
    for the active layer). Raises AIRequestError on a bad endpoint or HTTP error; a
    mid-stream drop simply ends the iterator.
    """
    origin = ollama_origin(config)
    if origin is None:
        raise AIRequestError("The configured endpoint is not an Ollama server.")
    async with httpx.AsyncClient(timeout=_PULL_TIMEOUT, headers=_auth_headers(config)) as client:
        try:
            async with client.stream(
                "POST",
                f"{origin}/api/pull",
                json={"model": model, "stream": True},
            ) as response:
                if response.status_code != httpx.codes.OK:
                    raise AIRequestError(f"Ollama returned HTTP {response.status_code} for the pull.")
                async for line in response.aiter_lines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        parsed = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        yield parsed
        except httpx.HTTPError as exc:
            raise AIRequestError(f"Ollama is unreachable: {exc.__class__.__name__}.") from exc
