"""AI provider foundation (#359).

Spoolman never runs inference itself; every AI feature talks to a user-configured
OpenAI-compatible endpoint (Ollama, LM Studio, OpenAI, Anthropic's compatibility
endpoint, OpenRouter, Requesty, Groq, ...). This module owns three things:

* **Config resolution** — environment variables are authoritative, DB settings are
  the UI-editable fallback (docs/llm-integration-brainstorm.md §2). A field set via
  env is reported as env-locked so the client can disable its input.
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

# Registered (non-secret) DB settings — see the registrations in spoolman/settings.py.
SETTING_BASE_URL = "ai_base_url"
SETTING_MODEL = "ai_model"
SETTING_VISION_MODEL = "ai_vision_model"

#: Feature-toggle setting key -> feature name as reported by /ai/status. All default off:
#: AI must be invisible unless explicitly enabled (brainstorm decision #7).
FEATURE_SETTINGS = {
    "ai_feature_chat": "chat",
    "ai_feature_scan_to_spool": "scan_to_spool",
    "ai_feature_nl_search": "nl_search",
    "ai_feature_voice": "voice",
}

#: Unregistered settings-table key for the write-only API key. Kept out of the settings
#: registry on purpose; tests/test_ai.py asserts it never gets registered.
API_KEY_DB_KEY = "ai_api_key"

_PROBE_TIMEOUT = 10.0

TriState = Literal["yes", "no", "unknown"]


@dataclass
class AIConfig:
    """Effective provider configuration after env-over-DB resolution."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    vision_model: str | None = None
    #: field name -> "env" | "db" for every field that has a value.
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        """Whether the minimum viable configuration (endpoint + chat model) is present."""
        return bool(self.base_url and self.model)


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


async def get_stored_api_key(db: AsyncSession) -> str | None:
    """Read the stored API key (raw, not JSON-encoded). None when unset."""
    row = await db.get(models.Setting, API_KEY_DB_KEY)
    if row is None:
        return None
    return row.value or None


async def set_stored_api_key(db: AsyncSession, value: str | None) -> None:
    """Set or clear the stored API key.

    Deliberately does NOT go through spoolman.database.setting.update: that helper
    broadcasts the new value to websocket subscribers, which must never happen for
    a secret.
    """
    if value:
        await db.merge(
            models.Setting(
                key=API_KEY_DB_KEY,
                value=value,
                last_updated=datetime.utcnow().replace(microsecond=0),
            ),
        )
    else:
        row = await db.get(models.Setting, API_KEY_DB_KEY)
        if row is not None:
            await db.delete(row)
    await db.commit()
    logger.info("AI API key has been %s.", "updated" if value else "cleared")


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

    env_key = _env(ENV_API_KEY)
    if env_key is not None:
        config.api_key = env_key
        config.sources["api_key"] = "env"
    else:
        stored = await get_stored_api_key(db)
        if stored is not None:
            config.api_key = stored
            config.sources["api_key"] = "db"

    config.base_url = normalize_base_url(config.base_url)
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
