"""AI provider foundation (#359).

Spoolman never runs inference itself; every AI feature talks to a user-configured
OpenAI-compatible endpoint (Ollama, LM Studio, OpenAI, Anthropic's compatibility
endpoint, OpenRouter, Requesty, Groq, ...). This module owns three things:

* **Config resolution** — environment variables are authoritative, DB settings are
  the UI-editable fallback, so an operator who manages config in their own secret
  store keeps it. A field set via env is reported as env-locked so the client can
  disable its input.
* **Write-only API-key storage** — the key is deliberately *not* a registered
  setting: the generic ``/setting`` API returns every registered key's value and
  broadcasts changes over websockets, either of which would leak a secret. Instead
  it is stored under an unregistered key in the same table (the generic endpoints
  404/skip unregistered keys) and is only ever reported as set/not set.
* **The capability probe** — reachability plus ``/v1/models``, with Ollama-specific
  enrichment: Ollama's ``/api/show`` reports per-model ``tools``/``vision``
  capabilities. Generic OpenAI-compatible endpoints cannot be queried for
  capabilities, so those report ``"unknown"`` rather than a guess.

No AI feature ships in this module — it is the shared plumbing (#360-#363 consume
it). Everything is inert until the user configures an endpoint.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import models
from spoolman.settings import SETTINGS

logger = logging.getLogger(__name__)

# Environment variables (authoritative over the DB settings below).
ENV_BASE_URL = "SPOOLMAN_AI_BASE_URL"
ENV_API_KEY = "SPOOLMAN_AI_API_KEY"
ENV_MODEL = "SPOOLMAN_AI_MODEL"
ENV_VISION_MODEL = "SPOOLMAN_AI_VISION_MODEL"
# Speech-to-text (#363) lives on its own endpoint: chat providers like Ollama have no STT,
# so voice points at a separate OpenAI-compatible transcription server (whisper.cpp, Speaches,
# Groq whisper, ...). Its own base URL, model and (write-only) key.
ENV_STT_BASE_URL = "SPOOLMAN_AI_STT_BASE_URL"
ENV_STT_API_KEY = "SPOOLMAN_AI_STT_API_KEY"
ENV_STT_MODEL = "SPOOLMAN_AI_STT_MODEL"

# Registered (non-secret) DB settings — see the registrations in spoolman/settings.py.
SETTING_BASE_URL = "ai_base_url"
SETTING_MODEL = "ai_model"
SETTING_VISION_MODEL = "ai_vision_model"
SETTING_STT_BASE_URL = "ai_stt_base_url"
SETTING_STT_MODEL = "ai_stt_model"

#: Feature-toggle setting key -> feature name as reported by /ai/status. All default off:
#: AI must be invisible unless explicitly enabled.
FEATURE_SETTINGS = {
    "ai_feature_chat": "chat",
    "ai_feature_scan_to_spool": "scan_to_spool",
    "ai_feature_nl_search": "nl_search",
    "ai_feature_mcp": "mcp",
    "ai_feature_voice": "voice",
}

#: Unregistered settings-table keys for the write-only API keys. Kept out of the settings
#: registry on purpose; tests/test_ai.py asserts they never get registered.
API_KEY_DB_KEY = "ai_api_key"
STT_API_KEY_DB_KEY = "ai_stt_api_key"

_PROBE_TIMEOUT = 10.0
#: Vision inference on local hardware is legitimately slow; give it room.
_CHAT_TIMEOUT = 120.0
#: Photo extraction is a bigger, slower request than a chat turn: a 1568 px label costs roughly
#: 1,800 image tokens to decode before generation even starts, and Spoolman targets CPU-only
#: NASes and Pis where that is far slower than on a GPU box. The failure mode of getting this
#: wrong is a hard timeout with nothing to show the user, so it is generous by design.
_VISION_TIMEOUT = 300.0

TriState = Literal["yes", "no", "unknown"]


class AIRequestError(Exception):
    """A chat-completion request failed; the message is safe to surface to the user."""


@dataclass
class AIConfig:
    """Effective provider configuration after env-over-DB resolution."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    vision_model: str | None = None
    #: Speech-to-text endpoint (#363), independent of the chat endpoint above.
    stt_base_url: str | None = None
    stt_api_key: str | None = None
    stt_model: str | None = None
    #: field name -> "env" | "db" for every field that has a value.
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        """Whether the minimum viable configuration (endpoint + chat model) is present."""
        return bool(self.base_url and self.model)

    @property
    def stt_configured(self) -> bool:
        """Whether a speech-to-text endpoint and model are present (voice input needs both)."""
        return bool(self.stt_base_url and self.stt_model)


@dataclass
class ProbeResult:
    """Outcome of one capability probe against the configured endpoint."""

    ok: bool
    error: str | None = None
    latency_ms: int | None = None
    models: list[str] = field(default_factory=list)
    #: Whether the configured chat model is usable ("yes"), definitely not ("no"),
    #: or can't be verified against this endpoint ("unknown").
    chat: TriState = "unknown"
    tools: TriState = "unknown"
    vision: TriState = "unknown"
    is_ollama: bool = False
    checked_at: datetime | None = None


@dataclass
class _AIState:
    """Module-level cache of the most recent probe, read by /ai/status.

    Mirrors the updatecheck.py pattern: mutated in place on the event loop, read-only
    consumers, no lock needed.
    """

    last_probe: ProbeResult | None = None
    #: (ollama origin, model) -> advertised capability set, memoised so the request path pays
    #: at most one /api/show per model per process. Only successful lookups are stored; a
    #: transient failure must not permanently disable the tuning below.
    capabilities: dict[tuple[str, str], set[str]] = field(default_factory=dict)


_state = _AIState()


def get_cached_probe() -> ProbeResult | None:
    """Return the most recent probe result, or None if no probe has run."""
    return _state.last_probe


def _env(name: str) -> str | None:
    """Read an env var, treating unset and empty/whitespace-only as absent."""
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


async def _setting_string(db: AsyncSession, key: str) -> str | None:
    """Read a registered STRING setting's decoded value; empty string reads as absent."""
    definition = SETTINGS[key]
    row = await db.get(models.Setting, definition.key)
    raw = row.value if row is not None else definition.default
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, str):
        return None
    return decoded.strip() or None


async def _setting_bool(db: AsyncSession, key: str) -> bool:
    """Read a registered BOOLEAN setting's decoded value."""
    definition = SETTINGS[key]
    row = await db.get(models.Setting, definition.key)
    raw = row.value if row is not None else definition.default
    try:
        return bool(json.loads(raw))
    except json.JSONDecodeError:
        return False


async def get_feature_flags(db: AsyncSession) -> dict[str, bool]:
    """Return {feature name: enabled} for all AI feature toggles."""
    return {name: await _setting_bool(db, key) for key, name in FEATURE_SETTINGS.items()}


# --- Write-only API-key storage ---------------------------------------------------


async def _get_stored_key(db: AsyncSession, db_key: str) -> str | None:
    """Read a stored write-only key (raw, not JSON-encoded). None when unset."""
    row = await db.get(models.Setting, db_key)
    if row is None:
        return None
    return row.value or None


async def _set_stored_key(db: AsyncSession, db_key: str, value: str | None, label: str) -> None:
    """Set or clear a stored write-only key.

    Deliberately does NOT go through spoolman.database.setting.update: that helper
    broadcasts the new value to websocket subscribers, which must never happen for
    a secret.
    """
    if value:
        await db.merge(
            models.Setting(
                key=db_key,
                value=value,
                last_updated=datetime.utcnow().replace(microsecond=0),
            ),
        )
    else:
        row = await db.get(models.Setting, db_key)
        if row is not None:
            await db.delete(row)
    await db.commit()
    logger.info("%s has been %s.", label, "updated" if value else "cleared")


async def get_stored_api_key(db: AsyncSession) -> str | None:
    """Read the stored chat-provider API key. None when unset."""
    return await _get_stored_key(db, API_KEY_DB_KEY)


async def set_stored_api_key(db: AsyncSession, value: str | None) -> None:
    """Set or clear the stored chat-provider API key."""
    await _set_stored_key(db, API_KEY_DB_KEY, value, "AI API key")


async def get_stored_stt_api_key(db: AsyncSession) -> str | None:
    """Read the stored speech-to-text API key (#363). None when unset."""
    return await _get_stored_key(db, STT_API_KEY_DB_KEY)


async def set_stored_stt_api_key(db: AsyncSession, value: str | None) -> None:
    """Set or clear the stored speech-to-text API key (#363)."""
    await _set_stored_key(db, STT_API_KEY_DB_KEY, value, "AI speech-to-text API key")


# --- Config resolution -------------------------------------------------------------


def normalize_base_url(value: str | None) -> str | None:
    """Strip trailing slashes so path concatenation is uniform."""
    if value is None:
        return None
    return value.rstrip("/") or None


async def resolve_config(db: AsyncSession) -> AIConfig:
    """Resolve the effective provider config: env vars win over DB settings."""
    config = AIConfig()
    for attr, env_name, setting_key in (
        ("base_url", ENV_BASE_URL, SETTING_BASE_URL),
        ("model", ENV_MODEL, SETTING_MODEL),
        ("vision_model", ENV_VISION_MODEL, SETTING_VISION_MODEL),
        ("stt_base_url", ENV_STT_BASE_URL, SETTING_STT_BASE_URL),
        ("stt_model", ENV_STT_MODEL, SETTING_STT_MODEL),
    ):
        env_value = _env(env_name)
        if env_value is not None:
            setattr(config, attr, env_value)
            config.sources[attr] = "env"
        else:
            db_value = await _setting_string(db, setting_key)
            if db_value is not None:
                setattr(config, attr, db_value)
                config.sources[attr] = "db"

    for attr, env_name, getter in (
        ("api_key", ENV_API_KEY, get_stored_api_key),
        ("stt_api_key", ENV_STT_API_KEY, get_stored_stt_api_key),
    ):
        env_key = _env(env_name)
        if env_key is not None:
            setattr(config, attr, env_key)
            config.sources[attr] = "env"
        else:
            stored = await getter(db)
            if stored is not None:
                setattr(config, attr, stored)
                config.sources[attr] = "db"

    config.base_url = normalize_base_url(config.base_url)
    config.stt_base_url = normalize_base_url(config.stt_base_url)
    return config


# --- Capability probe --------------------------------------------------------------


def _validate_base_url(base_url: str | None) -> str | None:
    """Return a human-readable rejection reason, or None when the URL is probeable."""
    if not base_url:
        return "No base URL configured."
    scheme = urlsplit(base_url).scheme
    if scheme not in ("http", "https"):
        return f"Unsupported base URL scheme '{scheme}' — must be http or https."
    return None


def _ollama_origin(base_url: str) -> str | None:
    """Derive the Ollama server origin from an OpenAI-compat base URL.

    Ollama serves the OpenAI-compatible surface under ``/v1``; its native API
    (which is what exposes capabilities) lives at the origin root.
    """
    if base_url.endswith("/v1"):
        return base_url[: -len("/v1")].rstrip("/")
    return None


async def _fetch_models(client: httpx.AsyncClient, base_url: str, result: ProbeResult) -> None:
    """Hit /models: sets ok, latency, and the model list, or a failure reason."""
    started = time.perf_counter()
    try:
        response = await client.get(f"{base_url}/models")
    except httpx.HTTPError as exc:
        result.error = f"Endpoint unreachable: {exc.__class__.__name__}: {exc}"
        return
    result.latency_ms = int((time.perf_counter() - started) * 1000)

    if response.status_code == httpx.codes.UNAUTHORIZED:
        result.error = "Endpoint rejected the API key (HTTP 401)."
        return
    if response.status_code != httpx.codes.OK:
        result.error = f"Endpoint returned HTTP {response.status_code} for /models."
        return

    try:
        payload = response.json()
    except json.JSONDecodeError:
        result.error = "Endpoint did not return JSON for /models — is this an OpenAI-compatible URL?"
        return
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        result.models = sorted(str(entry["id"]) for entry in data if isinstance(entry, dict) and "id" in entry)
    result.ok = True


async def _detect_ollama(client: httpx.AsyncClient, base_url: str) -> str | None:
    """Return the Ollama origin when the endpoint is an Ollama server, else None."""
    origin = _ollama_origin(base_url)
    if origin is None:
        return None
    try:
        tags = await client.get(f"{origin}/api/tags")
        if tags.status_code == httpx.codes.OK and "models" in tags.json():
            return origin
    except (httpx.HTTPError, json.JSONDecodeError):
        return None
    return None


async def _ollama_capabilities(client: httpx.AsyncClient, origin: str, model: str) -> set[str] | None:
    """Ask Ollama which capabilities a local model has; None when unanswerable.

    A 404 means the model is not pulled — reported as an empty set so callers can
    distinguish "definitely unusable" from "could not check".
    """
    try:
        response = await client.post(f"{origin}/api/show", json={"model": model})
    except httpx.HTTPError:
        return None
    if response.status_code == httpx.codes.NOT_FOUND:
        return set()
    if response.status_code != httpx.codes.OK:
        return None
    try:
        capabilities = response.json().get("capabilities", [])
    except json.JSONDecodeError:
        return None
    return {str(capability) for capability in capabilities}


async def _collect_capabilities(
    client: httpx.AsyncClient,
    origin: str,
    config: AIConfig,
) -> tuple[set[str] | None, set[str] | None]:
    """Fetch Ollama capability sets for the chat model and the vision candidate."""
    capabilities = await _ollama_capabilities(client, origin, config.model) if config.model else None
    vision_candidate = config.vision_model or config.model
    if not vision_candidate:
        vision_capabilities = None
    elif vision_candidate == config.model:
        vision_capabilities = capabilities
    else:
        vision_capabilities = await _ollama_capabilities(client, origin, vision_candidate)
    return capabilities, vision_capabilities


def _tri_from_capability(capabilities: set[str] | None, capability: str) -> TriState:
    if capabilities is None:
        return "unknown"
    return "yes" if capability in capabilities else "no"


def _derive_verdicts(
    config: AIConfig,
    result: ProbeResult,
    capabilities: set[str] | None,
    vision_capabilities: set[str] | None,
) -> None:
    """Turn raw probe data into per-capability verdicts on the result."""
    if not config.model:
        result.chat = "no"
    elif result.is_ollama:
        result.chat = _tri_from_capability(capabilities, "completion")
        result.tools = _tri_from_capability(capabilities, "tools")
    elif result.models and config.model in result.models:
        result.chat = "yes"
    else:
        # Model not in the listing: many gateways alias model names, so this is not a "no".
        result.chat = "unknown"

    if not (config.vision_model or config.model):
        result.vision = "no"
    elif result.is_ollama:
        result.vision = _tri_from_capability(vision_capabilities, "vision")


async def probe(config: AIConfig) -> ProbeResult:
    """Probe the endpoint: reachability, model list, and capabilities where knowable.

    Never raises on network/HTTP problems — failures come back as ``ok=False`` with a
    human-readable ``error`` so the settings UI can render them directly.
    """
    result = ProbeResult(ok=False, checked_at=datetime.now(tz=timezone.utc))

    rejection = _validate_base_url(config.base_url)
    if rejection is not None or config.base_url is None:
        result.error = rejection
        return _remember(result)

    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    capabilities: set[str] | None = None
    vision_capabilities: set[str] | None = None
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, headers=headers) as client:
        await _fetch_models(client, config.base_url, result)
        if result.ok:
            origin = await _detect_ollama(client, config.base_url)
            result.is_ollama = origin is not None
            if origin is not None:
                capabilities, vision_capabilities = await _collect_capabilities(client, origin, config)

    if result.ok:
        _derive_verdicts(config, result, capabilities, vision_capabilities)
    return _remember(result)


def _remember(result: ProbeResult) -> ProbeResult:
    """Cache the probe result for /ai/status and return it."""
    _state.last_probe = result
    return result


# --- Ollama request tuning ---------------------------------------------------------
#
# Ollama turns thinking *on* for any model whose capabilities include "thinking" when the request
# carries no reasoning control. Measured against the curated tool layer, that default costs 15-21
# points of tool-selection accuracy and runs 3-7x slower, and on the photo path it pushes every
# extraction past the request timeout. `reasoning_effort: "none"` is the only control that reaches
# Ollama's OpenAI-compatible surface -- the native `think` flag and chat_template_kwargs are
# accepted and ignored there.
#
# Both keys below are Ollama-specific, so they are gated on positively identifying an Ollama
# endpoint *and* on the model's own advertised capabilities. A generic OpenAI-compatible server
# keeps receiving exactly the body it receives today: it is entitled to reject an unknown key, and
# a setup that works must not start failing because we guessed.


async def _ollama_capability_set(config: AIConfig, model: str) -> set[str]:
    """Best-effort capability set for one model; empty when not Ollama or unanswerable.

    Every failure resolves to the empty set, which means "send today's payload". This lookup is
    an optimisation on the request path and must never be able to fail a real chat request --
    hence the broad except, which also covers test transports that reject unmocked requests.
    """
    origin = _ollama_origin(config.base_url or "")
    if origin is None:
        return set()
    cached = _state.capabilities.get((origin, model))
    if cached is not None:
        return cached
    try:
        headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, headers=headers) as client:
            if await _detect_ollama(client, config.base_url or "") is None:
                capabilities: set[str] | None = set()
            else:
                capabilities = await _ollama_capabilities(client, origin, model)
    except Exception:  # noqa: BLE001 - never let a capability sniff break a real request
        return set()
    if capabilities is None:  # could not check; retry next time rather than caching a guess
        return set()
    _state.capabilities[(origin, model)] = capabilities
    return capabilities


async def _ollama_tuning(config: AIConfig, model: str, *, want_json: bool) -> dict:
    """Extra payload keys for a known Ollama model; empty dict for everything else."""
    capabilities = await _ollama_capability_set(config, model)
    if not capabilities:
        return {}
    tuning: dict = {}
    if "thinking" in capabilities:
        tuning["reasoning_effort"] = "none"
    if want_json:
        tuning["response_format"] = {"type": "json_object"}
    return tuning


# --- Chat completions --------------------------------------------------------------


async def _post_chat(config: AIConfig, payload: dict, timeout: float) -> dict:
    """POST one chat-completion request and return the assistant message object.

    The single outbound HTTP path shared by every text and tool-calling caller. Raises
    AIRequestError with a user-safe message on any failure (unreachable, HTTP error,
    unexpected shape). The returned dict is the raw ``choices[0].message`` — it carries
    ``content`` and, when the model called tools, ``tool_calls``.
    """
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            response = await client.post(f"{config.base_url}/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise AIRequestError(f"The AI endpoint timed out after {int(timeout)} s.") from exc
        except httpx.HTTPError as exc:
            raise AIRequestError(f"The AI endpoint is unreachable: {exc.__class__.__name__}.") from exc

    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise AIRequestError("The AI endpoint rejected the API key (HTTP 401).")
    if response.status_code != httpx.codes.OK:
        detail = ""
        try:
            detail = str(response.json().get("error", {}).get("message", ""))[:200]
        except (json.JSONDecodeError, AttributeError):
            detail = response.text[:200]
        raise AIRequestError(f"The AI endpoint returned HTTP {response.status_code}. {detail}".strip())

    try:
        message = response.json()["choices"][0]["message"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise AIRequestError("The AI endpoint returned an unexpected response shape.") from exc
    if not isinstance(message, dict):
        raise AIRequestError("The AI endpoint returned an unexpected response shape.")
    return message


async def chat_completion(
    config: AIConfig,
    messages: list[dict],
    *,
    use_vision_model: bool = False,
    want_json: bool = False,
    max_tokens: int = 2000,
    timeout: float | None = None,
) -> str:
    """Run one chat completion against the configured endpoint and return the reply text.

    Raises AIRequestError with a user-safe message on any failure (unconfigured,
    unreachable, HTTP error, unexpected response shape).

    ``want_json`` asks the endpoint to constrain the reply to a JSON object where we know it
    is supported (see _ollama_tuning). It is a hint, not a guarantee: generic endpoints get no
    such key, so callers must still instruct the model in the prompt and parse defensively.
    """
    if not config.base_url:
        raise AIRequestError("No AI endpoint is configured.")
    model = (config.vision_model or config.model) if use_vision_model else config.model
    if not model:
        raise AIRequestError("No model is configured.")

    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    payload.update(await _ollama_tuning(config, model, want_json=want_json))
    if timeout is None:
        timeout = _VISION_TIMEOUT if use_vision_model else _CHAT_TIMEOUT
    message = await _post_chat(config, payload, timeout)
    content = message.get("content")
    if not isinstance(content, str):
        raise AIRequestError("The AI endpoint returned no text content.")
    return content


async def chat_completion_tools(
    config: AIConfig,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    max_tokens: int = 1500,
    timeout: float = _CHAT_TIMEOUT,
) -> dict:
    """Run one tool-enabled chat completion and return the raw assistant message.

    The agent loop (spoolman.aichat) drives this: it feeds the message history plus the
    curated tool schemas, and reads back either ``content`` (a final answer) or
    ``tool_calls`` (the model wants to call one of the tools). ``tools`` is only attached
    when non-empty, so a read-only caller with no write tools — or any caller on a
    pure-conversation turn — still sends a valid request to endpoints that reject an
    empty tools array.
    """
    if not config.base_url:
        raise AIRequestError("No AI endpoint is configured.")
    if not config.model:
        raise AIRequestError("No model is configured.")

    payload: dict = {"model": config.model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    payload.update(await _ollama_tuning(config, config.model, want_json=False))
    return await _post_chat(config, payload, timeout)
