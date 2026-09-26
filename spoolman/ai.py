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
from spoolman.database.utils import utc_now
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
# Decision model (a typed-question endpoint such as TypeSafe's Jev; see spoolman/decision.py).
# It is not OpenAI-compatible, so it has its own base URL, model and (write-only) key. This
# module only stores and resolves them; spoolman/decision.py validates and uses them.
ENV_DECISION_BASE_URL = "SPOOLMAN_AI_DECISION_BASE_URL"
ENV_DECISION_API_KEY = "SPOOLMAN_AI_DECISION_API_KEY"
ENV_DECISION_MODEL = "SPOOLMAN_AI_DECISION_MODEL"

# Registered (non-secret) DB settings — see the registrations in spoolman/settings.py.
SETTING_BASE_URL = "ai_base_url"
SETTING_MODEL = "ai_model"
SETTING_VISION_MODEL = "ai_vision_model"
SETTING_STT_BASE_URL = "ai_stt_base_url"
SETTING_STT_MODEL = "ai_stt_model"
SETTING_DECISION_BASE_URL = "ai_decision_base_url"
SETTING_DECISION_MODEL = "ai_decision_model"

#: Feature-toggle setting key -> feature name as reported by /ai/status. All default off:
#: AI must be invisible unless explicitly enabled.
FEATURE_SETTINGS = {
    "ai_feature_chat": "chat",
    "ai_feature_scan_to_spool": "scan_to_spool",
    "ai_feature_nl_search": "nl_search",
    "ai_feature_mcp": "mcp",
    "ai_feature_voice": "voice",
    "ai_feature_duplicate_check": "duplicate_check",
}

#: Unregistered settings-table keys for the write-only API keys. Kept out of the settings
#: registry on purpose; tests/test_ai.py asserts they never get registered.
API_KEY_DB_KEY = "ai_api_key"
STT_API_KEY_DB_KEY = "ai_stt_api_key"
#: Unlike the two keys above, its row holds JSON: the key and the decision base URL it was saved
#: for, in one row so they are written together. The key is only used with that URL, so
#: changing the URL in Settings can never send the old key to a new host.
DECISION_API_KEY_DB_KEY = "ai_decision_api_key"

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
    #: Decision-model endpoint, independent of both endpoints above. The model may be left
    #: unset; spoolman/decision.py then uses its default.
    decision_base_url: str | None = None
    decision_api_key: str | None = None
    decision_model: str | None = None
    #: Whether each key is stored, even one not in use because the base URL changed since it
    #: was saved. The UI needs these to offer Clear for such a key.
    api_key_stored: bool = False
    stt_api_key_stored: bool = False
    decision_api_key_stored: bool = False
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

    @property
    def decision_configured(self) -> bool:
        """Whether a decision-model endpoint is set (the model has a default)."""
        return bool(self.decision_base_url)


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
    #: Key attribute -> the last "not using this key" reason logged, so each warning is logged
    #: once per change rather than on every resolve_config call.
    key_warnings: dict[str, str] = field(default_factory=dict)


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
                last_updated=utc_now().replace(microsecond=0),
            ),
        )
    else:
        row = await db.get(models.Setting, db_key)
        if row is not None:
            await db.delete(row)
    await db.commit()
    logger.info("%s has been %s.", label, "updated" if value else "cleared")


@dataclass(frozen=True)
class _KeySpec:
    """One write-only key and the base URL it may be sent to."""

    key_attr: str
    url_attr: str
    db_key: str
    env_key: str
    label: str
    #: A key set by environment variable is only used with a base URL set the same way. Off for
    #: the chat and speech-to-text keys, which operators already combine with a URL entered in
    #: Settings; on for the decision key, which never supported that.
    env_key_needs_env_url: bool


_KEY_SPECS = (
    _KeySpec("api_key", "base_url", API_KEY_DB_KEY, ENV_API_KEY, "AI API key", env_key_needs_env_url=False),
    _KeySpec(
        "stt_api_key",
        "stt_base_url",
        STT_API_KEY_DB_KEY,
        ENV_STT_API_KEY,
        "AI speech-to-text API key",
        env_key_needs_env_url=False,
    ),
    _KeySpec(
        "decision_api_key",
        "decision_base_url",
        DECISION_API_KEY_DB_KEY,
        ENV_DECISION_API_KEY,
        "AI decision-model API key",
        env_key_needs_env_url=True,
    ),
)
_KEY_SPEC = {spec.key_attr: spec for spec in _KEY_SPECS}


@dataclass(frozen=True)
class _StoredKey:
    """A stored key and the base URL it was saved for."""

    key: str
    bound_url: str | None
    #: False for a row written before keys were tied to their URL: plain text, no URL.
    bound: bool


#: Marks a stored key row as the bound format. Before it, any string was accepted as a key, so a
#: key that is itself JSON with a "key" member must not be mistaken for a bound record.
_KEY_RECORD_VERSION = 1


def _key_record(bound_url: str | None, key: str) -> str:
    return json.dumps({"v": _KEY_RECORD_VERSION, "base_url": bound_url, "key": key})


def _is_key_record(record: object, spec: _KeySpec) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("v") == _KEY_RECORD_VERSION:
        return True
    # Decision keys were stored as {"base_url", "key"} without the marker for a while; nothing
    # else was ever stored under that row, so the exact shape is unambiguous there.
    return spec.key_attr == "decision_api_key" and set(record) == {"base_url", "key"}


async def _read_stored_key(db: AsyncSession, spec: _KeySpec) -> _StoredKey | None:
    """Read a stored key row: a bound record (see _key_record), or plain text from before binding."""
    raw = await _get_stored_key(db, spec.db_key)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        record = None
    if not _is_key_record(record, spec):
        return _StoredKey(key=raw, bound_url=None, bound=False)
    key = record.get("key")
    if not isinstance(key, str) or not key:
        return None
    bound_url = record.get("base_url")
    return _StoredKey(
        key=key,
        bound_url=normalize_base_url(bound_url) if isinstance(bound_url, str) else None,
        bound=True,
    )


async def _store_key(db: AsyncSession, spec: _KeySpec, value: str | None) -> None:
    """Set or clear a stored key, bound to the base URL in effect now.

    Save the base URL first: the key is only ever sent to the URL it was saved with.
    """
    record = None
    if value:
        bound_url = getattr(await resolve_config(db), spec.url_attr)
        record = _key_record(bound_url, value)
    await _set_stored_key(db, spec.db_key, record, spec.label)


async def get_stored_api_key(db: AsyncSession) -> str | None:
    """Read the stored chat-provider API key, whichever base URL it belongs to. None when unset."""
    stored = await _read_stored_key(db, _KEY_SPEC["api_key"])
    return stored.key if stored else None


async def set_stored_api_key(db: AsyncSession, value: str | None) -> None:
    """Set or clear the stored chat-provider API key, bound to the chat base URL in effect now."""
    await _store_key(db, _KEY_SPEC["api_key"], value)


async def get_stored_stt_api_key(db: AsyncSession) -> str | None:
    """Read the stored speech-to-text API key (#363), whichever base URL it belongs to."""
    stored = await _read_stored_key(db, _KEY_SPEC["stt_api_key"])
    return stored.key if stored else None


async def set_stored_stt_api_key(db: AsyncSession, value: str | None) -> None:
    """Set or clear the stored speech-to-text API key, bound to the STT base URL in effect now."""
    await _store_key(db, _KEY_SPEC["stt_api_key"], value)


async def get_stored_decision_api_key(db: AsyncSession) -> str | None:
    """Read the stored decision-model API key, whichever base URL it belongs to. None when unset."""
    stored = await _read_stored_key(db, _KEY_SPEC["decision_api_key"])
    return stored.key if stored else None


async def set_stored_decision_api_key(db: AsyncSession, value: str | None) -> None:
    """Set or clear the stored decision-model API key, bound to the decision base URL in effect now."""
    await _store_key(db, _KEY_SPEC["decision_api_key"], value)


async def upgrade_stored_keys(db: AsyncSession) -> None:
    """Bind keys stored before keys were tied to their URL to the base URL in effect now.

    Run once at startup. A plain-text key row becomes ``{"base_url", "key"}`` for the URL that is
    configured now, so an existing install keeps working, and a later URL change no longer carries
    the key along. A key with no base URL in effect is left as it is: it is not used until it is
    entered again. Running it twice changes nothing.
    """
    # A failure only leaves the old keys unused (resolve_config never sends an unbound key), so
    # it is logged rather than allowed to stop Spoolman starting.
    try:
        config = await _resolve_values(db)
        for spec in _KEY_SPECS:
            stored = await _read_stored_key(db, spec)
            url = getattr(config, spec.url_attr)
            if stored is None or stored.bound or not url:
                continue
            await _set_stored_key(db, spec.db_key, _key_record(url, stored.key), spec.label)
            logger.info("%s is now tied to its base URL.", spec.label)
    except Exception:
        logger.exception("Could not tie stored AI keys to their base URLs; they stay unused until entered again.")


def _key_problem(spec: _KeySpec, config: AIConfig, stored: _StoredKey | None) -> str | None:
    """Why the key in ``config`` must not be sent to the base URL in effect, or None when it may."""
    source = config.sources.get(spec.key_attr)
    if source == "env":
        if spec.env_key_needs_env_url and config.sources.get(spec.url_attr) != "env":
            return "the base URL is not set by environment variable too"
        return None
    if source != "db" or stored is None:
        return None
    if not stored.bound:
        return "it was saved before keys were tied to their base URL; enter it again"
    if stored.bound_url is None or stored.bound_url != getattr(config, spec.url_attr):
        return "it was saved for a different base URL"
    return None


async def _keys_for_endpoints(db: AsyncSession, config: AIConfig) -> None:
    """Drop every key that belongs to a different endpoint than the one now in effect.

    Otherwise changing a base URL alone would send the old key to the new host.
    """
    for spec in _KEY_SPECS:
        stored = await _read_stored_key(db, spec)
        setattr(config, f"{spec.key_attr}_stored", stored is not None)
        reason = _key_problem(spec, config, stored)
        if reason is None:
            _state.key_warnings.pop(spec.key_attr, None)
            continue
        setattr(config, spec.key_attr, None)
        if config.sources.get(spec.key_attr) == "db":
            del config.sources[spec.key_attr]
        # Without a base URL nothing is sent anyway, so there is nothing to warn about.
        if getattr(config, spec.url_attr) and _state.key_warnings.get(spec.key_attr) != reason:
            _state.key_warnings[spec.key_attr] = reason
            logger.warning("Not using the %s: %s.", spec.label, reason)


# --- Config resolution -------------------------------------------------------------


def normalize_base_url(value: str | None) -> str | None:
    """Strip trailing slashes so path concatenation is uniform."""
    if value is None:
        return None
    return value.rstrip("/") or None


async def _resolve_values(db: AsyncSession) -> AIConfig:
    """Env-over-DB values with URLs normalised, before any key is checked against its URL."""
    config = AIConfig()
    for attr, env_name, setting_key in (
        ("base_url", ENV_BASE_URL, SETTING_BASE_URL),
        ("model", ENV_MODEL, SETTING_MODEL),
        ("vision_model", ENV_VISION_MODEL, SETTING_VISION_MODEL),
        ("stt_base_url", ENV_STT_BASE_URL, SETTING_STT_BASE_URL),
        ("stt_model", ENV_STT_MODEL, SETTING_STT_MODEL),
        ("decision_base_url", ENV_DECISION_BASE_URL, SETTING_DECISION_BASE_URL),
        ("decision_model", ENV_DECISION_MODEL, SETTING_DECISION_MODEL),
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

    for spec in _KEY_SPECS:
        env_key = _env(spec.env_key)
        if env_key is not None:
            setattr(config, spec.key_attr, env_key)
            config.sources[spec.key_attr] = "env"
        else:
            stored = await _read_stored_key(db, spec)
            if stored is not None:
                setattr(config, spec.key_attr, stored.key)
                config.sources[spec.key_attr] = "db"

    config.base_url = normalize_base_url(config.base_url)
    config.stt_base_url = normalize_base_url(config.stt_base_url)
    config.decision_base_url = normalize_base_url(config.decision_base_url)
    return config


async def resolve_config(db: AsyncSession) -> AIConfig:
    """Resolve the effective provider config: env vars win over DB settings.

    A stored key is only returned with the base URL it was saved for (see _keys_for_endpoints).
    """
    config = await _resolve_values(db)
    await _keys_for_endpoints(db, config)
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
