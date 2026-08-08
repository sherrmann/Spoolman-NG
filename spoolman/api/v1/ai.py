"""AI foundation endpoints (#359): status, capability probe, write-only key config.

Three endpoints, all inert until the user configures an endpoint:

* ``GET /ai/status`` — everything the client needs to render Settings -> AI and (later)
  to decide which AI affordances may render at all: effective config (never the key
  itself), env-locked fields, feature toggles, and the cached capability probe.
* ``POST /ai/probe`` — run a capability probe, optionally overriding fields from the
  request body so "Test connection" can check unsaved form values. Admin-gated: the
  server performs an outbound request to a caller-influenced URL.
* ``POST /ai/config`` — set or clear the write-only API key. Admin-gated. The key is
  never echoed back by any endpoint; responses only ever say whether one is set.
"""

import asyncio
import base64
import binascii
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai, ai_tools, aichat, nlsearch, ollama, spoolintake, voice
from spoolman.api.v1 import bodylimit
from spoolman.api.v1.auth import _principal, require_admin
from spoolman.api.v1.models import Message
from spoolman.auth import Principal
from spoolman.database.database import get_db_session, get_session_maker
from spoolman.users import ROLE_ADMIN

router = APIRouter(
    prefix="/ai",
    tags=["ai"],
)

# ruff: noqa: D103

logger = logging.getLogger(__name__)


class AIProbeResult(BaseModel):
    ok: bool = Field(description="Whether the endpoint answered /models successfully.")
    error: str | None = Field(default=None, description="Human-readable failure reason when ok is false.")
    latency_ms: int | None = Field(default=None, description="Round-trip time of the /models request.")
    models: list[str] = Field(default_factory=list, description="Model ids listed by the endpoint.")
    chat: ai.TriState = Field(description="Whether the configured chat model is usable.")
    tools: ai.TriState = Field(description="Whether the chat model supports tool calls (known for Ollama only).")
    vision: ai.TriState = Field(description="Whether the vision model supports image input (known for Ollama only).")
    is_ollama: bool = Field(description="Whether the endpoint was identified as an Ollama server.")
    checked_at: datetime | None = Field(default=None, description="When this probe ran.")

    @staticmethod
    def from_result(result: ai.ProbeResult) -> "AIProbeResult":
        """Build the API model from the internal probe dataclass."""
        return AIProbeResult(
            ok=result.ok,
            error=result.error,
            latency_ms=result.latency_ms,
            models=result.models,
            chat=result.chat,
            tools=result.tools,
            vision=result.vision,
            is_ollama=result.is_ollama,
            checked_at=result.checked_at,
        )


class AIStatus(BaseModel):
    configured: bool = Field(description="Whether a base URL and chat model are configured.")
    base_url: str | None = Field(default=None, description="Effective base URL (env wins over the DB setting).")
    model: str | None = Field(default=None, description="Effective chat/tool model.")
    vision_model: str | None = Field(default=None, description="Effective vision model (falls back to the chat model).")
    api_key_set: bool = Field(description="Whether an API key is configured. The key itself is never returned.")
    stt_configured: bool = Field(
        default=False,
        description="Whether a speech-to-text endpoint and model are configured (voice input needs both).",
    )
    stt_base_url: str | None = Field(default=None, description="Effective speech-to-text base URL.")
    stt_model: str | None = Field(default=None, description="Effective speech-to-text model.")
    stt_api_key_set: bool = Field(default=False, description="Whether a speech-to-text API key is configured.")
    env_locked: list[str] = Field(
        default_factory=list,
        description="Fields set via SPOOLMAN_AI_* env vars; the UI disables these inputs.",
    )
    features: dict[str, bool] = Field(
        default_factory=dict,
        description="Per-feature enable flags (all default off; features render no UI until enabled).",
    )
    capabilities: AIProbeResult | None = Field(
        default=None,
        description="Most recent capability probe, if one has run since startup.",
    )


class AIProbeRequest(BaseModel):
    """Overrides for 'Test connection' with unsaved form values; omitted fields use the saved config."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    vision_model: str | None = None


class AIKeyRequest(BaseModel):
    # Both optional so each key can be set independently; only fields actually present in the
    # request body are acted on (a present null clears that key).
    api_key: str | None = Field(default=None, description="The chat API key to store, or null to clear it.")
    stt_api_key: str | None = Field(default=None, description="The speech-to-text API key to store, or null to clear.")


class AIKeyResponse(BaseModel):
    api_key_set: bool = Field(description="Whether a chat API key is now in effect (env or stored).")
    env_locked: bool = Field(description="True when SPOOLMAN_AI_API_KEY is set, which overrides the stored key.")
    stt_api_key_set: bool = Field(default=False, description="Whether a speech-to-text API key is now in effect.")


@router.get(
    "/status",
    name="Get AI status",
    description=(
        "Get the effective AI provider configuration, feature toggles, and the most recent "
        "capability probe. The API key is never returned, only whether one is set. Only an "
        "administrator sees the provider configuration; everyone else gets the feature flags "
        "and readiness booleans the UI needs to decide what to render."
    ),
)
async def status(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIStatus:
    config = await ai.resolve_config(db)
    features = await ai.get_feature_flags(db)
    # Non-admins drive UI affordances off `features`/`configured`/`stt_configured` alone
    # (see chatDrawer.tsx). Endpoint URLs, model names and the probe's error text are
    # operator detail, so they stay with the operator — the Settings panel is admin-only
    # anyway, and /ai/probe and /ai/config already require admin.
    if _principal(request).role != ROLE_ADMIN:
        return AIStatus(
            configured=config.configured,
            api_key_set=config.api_key is not None,
            stt_configured=config.stt_configured,
            stt_api_key_set=config.stt_api_key is not None,
            features=features,
        )

    cached = ai.get_cached_probe()
    return AIStatus(
        configured=config.configured,
        base_url=config.base_url,
        model=config.model,
        vision_model=config.vision_model,
        api_key_set=config.api_key is not None,
        stt_configured=config.stt_configured,
        stt_base_url=config.stt_base_url,
        stt_model=config.stt_model,
        stt_api_key_set=config.stt_api_key is not None,
        env_locked=sorted(attr for attr, source in config.sources.items() if source == "env"),
        features=features,
        capabilities=AIProbeResult.from_result(cached) if cached is not None else None,
    )


@router.post(
    "/probe",
    name="Probe the AI endpoint",
    description=(
        "Run a capability probe (reachability, model list, capabilities where knowable) against "
        "the configured endpoint, with optional overrides for unsaved form values. Failures are "
        "reported in the response body, not as HTTP errors."
    ),
)
async def run_probe(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[Principal, Depends(require_admin)],
    body: AIProbeRequest,
) -> AIProbeResult:
    config = await ai.resolve_config(db)
    provided = body.model_dump(exclude_unset=True)
    for attr in ("base_url", "model", "vision_model", "api_key"):
        if attr in provided:
            value = provided[attr]
            setattr(config, attr, value.strip() or None if isinstance(value, str) else None)
    config.base_url = ai.normalize_base_url(config.base_url)
    return AIProbeResult.from_result(await ai.probe(config))


@router.post(
    "/config",
    name="Set the AI API keys",
    description=(
        "Store or clear the AI provider API key and/or the speech-to-text API key. Write-only: no "
        "endpoint ever returns a key. Only fields present in the request are changed (a present "
        "null clears that key). The SPOOLMAN_AI_*_API_KEY env vars override whatever is stored here."
    ),
)
async def set_key(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[Principal, Depends(require_admin)],
    body: AIKeyRequest,
) -> AIKeyResponse:
    provided = body.model_dump(exclude_unset=True)
    if "api_key" in provided:
        await ai.set_stored_api_key(db, body.api_key.strip() if body.api_key else None)
    if "stt_api_key" in provided:
        await ai.set_stored_stt_api_key(db, body.stt_api_key.strip() if body.stt_api_key else None)
    config = await ai.resolve_config(db)
    return AIKeyResponse(
        api_key_set=config.api_key is not None,
        env_locked=config.sources.get("api_key") == "env",
        stt_api_key_set=config.stt_api_key is not None,
    )


# --- Scan-to-Spool intake (#361) ---------------------------------------------------

#: ~15 MB of image after base64 decoding; photos should be client-downscaled anyway. The
#: request body is already capped at the same figure by BodyLimitMiddleware before it is
#: buffered — this check stays as the precise, per-field message.
_MAX_IMAGE_B64_CHARS = bodylimit.MAX_IMAGE_BODY_BYTES
_ALLOWED_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})


class AIExtraction(BaseModel):
    """The extraction JSON contract, shared with future on-device extractors."""

    model_config = ConfigDict(extra="ignore")

    vendor: str | None = None
    name: str | None = None
    material: str | None = None
    color_hex: str | None = None
    weight_g: float | None = None
    spool_weight_g: float | None = None
    diameter_mm: float | None = None
    extruder_temp_c: float | None = None
    bed_temp_c: float | None = None
    lot_nr: str | None = None
    article_number: str | None = None
    confidence: str | None = None


class SpoolIntakeExtractRequest(BaseModel):
    image_base64: str = Field(description="The photo, base64-encoded. Held in memory only, never persisted.")
    mime: str = Field(default="image/jpeg", description="Image MIME type: image/jpeg, image/png or image/webp.")


class SpoolIntakeResponse(BaseModel):
    extraction: AIExtraction
    matches: dict[str, list[dict]] = Field(
        description="Ranked candidates: 'library' (the user's own filaments — preferred) and 'catalog' (SpoolmanDB).",
    )


async def _require_scan_feature(db: AsyncSession) -> None:
    """Reject with 404 while the feature is disabled - the endpoints stay invisible."""
    flags = await ai.get_feature_flags(db)
    if not flags.get("scan_to_spool"):
        raise HTTPException(status_code=404, detail="Scan-to-Spool is not enabled.")


@router.post(
    "/spool-intake/extract",
    name="Extract spool data from a photo",
    description=(
        "Send a label/box photo to the configured vision model and get a structured extraction "
        "plus ranked matches (own library first, then the SpoolmanDB catalog). The image exists "
        "in memory for the duration of the request only — it is never persisted or logged."
    ),
    responses={
        400: {"model": Message},
        404: {"model": Message},
        409: {"model": Message},
        413: {"model": Message},
        502: {"model": Message},
    },
)
async def spool_intake_extract(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: SpoolIntakeExtractRequest,
) -> SpoolIntakeResponse:
    await _require_scan_feature(db)
    if body.mime not in _ALLOWED_IMAGE_MIMES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type '{body.mime}'.")
    if len(body.image_base64) > _MAX_IMAGE_B64_CHARS:
        raise HTTPException(status_code=413, detail="Image too large - downscale it before uploading.")
    try:
        base64.b64decode(body.image_base64, validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail="image_base64 is not valid base64.") from exc

    config = await ai.resolve_config(db)
    if not config.configured:
        raise HTTPException(status_code=409, detail="No AI endpoint and model are configured.")
    try:
        extraction = await spoolintake.extract(config, body.image_base64, body.mime)
    except ai.AIRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except spoolintake.ExtractionParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    matches = await spoolintake.build_matches(db, extraction)
    return SpoolIntakeResponse(extraction=AIExtraction(**extraction), matches=matches)


@router.post(
    "/spool-intake/match",
    name="Match an extraction against library and catalog",
    description=(
        "Run the matching stages over a client-supplied extraction (no image involved): the "
        "user's own filament library first, then the locally-synced SpoolmanDB catalog. This is "
        "the same second stage /spool-intake/extract runs, kept callable on its own so "
        "extraction can happen elsewhere (e.g. on-device in the companion app)."
    ),
    responses={404: {"model": Message}},
)
async def spool_intake_match(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: AIExtraction,
) -> SpoolIntakeResponse:
    await _require_scan_feature(db)
    extraction = spoolintake.normalize_extraction(body.model_dump())
    matches = await spoolintake.build_matches(db, extraction)
    return SpoolIntakeResponse(extraction=AIExtraction(**extraction), matches=matches)


# --- Chat assistant (#362, B1) -----------------------------------------------------


class ChatRequest(BaseModel):
    """One turn of the stateless chat protocol.

    ``messages`` is the whole transcript so far in OpenAI shape (user/assistant/tool
    turns, including any assistant ``tool_calls`` and their ``tool`` results), held by the
    client and round-tripped every turn. ``decision`` resolves the write tool calls left
    pending by a previous ``confirm`` event.
    """

    messages: list[dict] = Field(default_factory=list)
    context: str | None = Field(default=None, description="What the user is currently viewing, for context.")
    locale: str = Field(default="en", description="UI locale; the assistant replies in this language.")
    decision: Literal["confirm", "cancel"] | None = Field(
        default=None,
        description="Resolve pending write(s): 'confirm' executes them, 'cancel' declines them.",
    )


async def _require_chat_feature(db: AsyncSession) -> None:
    if not (await ai.get_feature_flags(db)).get("chat"):
        raise HTTPException(status_code=404, detail="The chat assistant is not enabled.")


#: How many chat turns may be in flight at once across the whole install. A turn holds a DB
#: session for the life of its SSE stream and can spend minutes waiting on the provider, so
#: without a cap a handful of clients (read-only accounts included — /ai/chat is one of the
#: two POSTs they may make) could hold every session in the pool. Turns over the cap are
#: refused immediately with 503 rather than queued behind a multi-minute wait.
_MAX_CONCURRENT_CHATS = 4
_chat_slots = asyncio.Semaphore(_MAX_CONCURRENT_CHATS)


@router.post(
    "/chat",
    name="Chat with the assistant",
    description=(
        "Stream one turn of the chat agent as Server-Sent Events. Read tools run automatically; a "
        "mutation stops the stream with a confirm-card carrying before/after values, which the client "
        "resolves by re-posting with decision='confirm' or 'cancel'. Read-only callers are offered no "
        "write tools. 404 until the feature is enabled; 409 until an endpoint is configured; "
        "503 when too many turns are already in flight."
    ),
    responses={404: {"model": Message}, 409: {"model": Message}, 503: {"model": Message}},
)
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    # Gate on a short-lived session that is released BEFORE streaming begins, so its read
    # transaction can't deadlock the stream's own writes on single-writer backends (SQLite).
    session_maker = get_session_maker()
    async with session_maker() as gate:
        await _require_chat_feature(gate)
        config = await ai.resolve_config(gate)
        if not config.configured:
            raise HTTPException(status_code=409, detail="No AI endpoint and model are configured.")

    can_write = _principal(request).role == ROLE_ADMIN
    context = (body.context or "").strip()[:200] or None
    locale = (body.locale or "en").strip()[:20] or "en"

    # Claim a slot before the response starts, so an overloaded server answers with a clean
    # 503 instead of opening a stream it has no capacity to serve.
    if _chat_slots.locked():
        raise HTTPException(status_code=503, detail="The assistant is busy. Try again in a moment.")
    await _chat_slots.acquire()

    async def stream() -> AsyncIterator[str]:
        try:
            async with session_maker() as session:
                async for frame in aichat.run_chat(
                    db=session,
                    config=config,
                    messages=body.messages,
                    context=context,
                    locale=locale,
                    can_write=can_write,
                    decision=body.decision,
                ):
                    yield frame
        finally:
            # Released however the stream ends, including a client disconnect mid-turn.
            _chat_slots.release()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ChatActionRequest(BaseModel):
    tool: str = Field(description="The curated write tool to run (e.g. from an undo descriptor).")
    args: dict = Field(default_factory=dict)


class ChatActionResponse(BaseModel):
    summary: str
    data: dict = Field(default_factory=dict)
    undo: dict | None = None


#: This endpoint is reached ONLY by the one-click Undo button, which replays a previously-returned
#: undo descriptor — never an arbitrary model-chosen call, and never previewed. Restricting it to
#: exactly the tool names that a write's own `undo=` descriptor can ever name keeps it from also
#: accepting, say, delete_filament with arbitrary caller-supplied arguments and no confirm-card at
#: all (that was C1: create_filament's undo descriptor named delete_filament, this endpoint called
#: delete_filament's execute() directly with no preview, and filament delete cascades to every spool
#: -- three individually-correct pieces composing into a silent, unconfirmed cascading delete).
#: tests/integration/test_ai_chat_endpoints.py asserts this set equals the union of tool names every
#: WRITE_TOOLS.execute actually emits in an undo descriptor, so the two cannot drift apart.
_CHAT_ACTION_ALLOWLIST = frozenset(
    {
        "update_spool",
        "update_filament",
        "set_spool_used_weight",
        "delete_spool",
        "delete_filament",
        "delete_filament_and_vendor",
        "delete_location",
        "delete_vendor",
        "delete_order",
    },
)


@router.post(
    "/chat/action",
    name="Run a curated write action",
    description=(
        "Execute one of the curated write tools that an undo descriptor can name (e.g. "
        "set_spool_used_weight, an undo-only primitive the chat model is never offered) — this is "
        "how one-click undo runs, "
        "and it is the only caller of this endpoint. Restricted to that fixed allowlist: it is never a "
        "general-purpose tool invoker. Admin only, gated by the same write permission as chat."
    ),
    responses={400: {"model": Message}, 404: {"model": Message}, 422: {"model": Message}},
)
async def chat_action(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[Principal, Depends(require_admin)],
    body: ChatActionRequest,
) -> ChatActionResponse:
    await _require_chat_feature(db)
    if body.tool not in _CHAT_ACTION_ALLOWLIST:
        raise HTTPException(status_code=400, detail=f"Unknown action '{body.tool}'.")
    tool = ai_tools.WRITE_TOOLS.get(body.tool)
    if tool is None:
        raise HTTPException(status_code=400, detail=f"Unknown action '{body.tool}'.")
    ctx = ai_tools.ToolContext(db=db, can_write=True)  # require_admin guarantees write eligibility
    try:
        result = await tool.execute(ctx, body.args)
    except ai_tools.ToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ChatActionResponse(summary=result.summary, data=result.data, undo=result.undo)


# --- Natural-language search (#362, B2) --------------------------------------------


class NLSearchRequest(BaseModel):
    query: str = Field(description="The user's free-text search, e.g. 'matte black PETG in shelf B'.")
    locale: str = Field(default="en")


class NLSearchFilter(BaseModel):
    field: str = Field(description="A spool-list filter field, e.g. 'filament.material' or 'location'.")
    values: list[str] = Field(description="Grounded values (verified to exist in the database).")


class NLSearchResponse(BaseModel):
    filters: list[NLSearchFilter] = Field(default_factory=list)
    search: str | None = Field(default=None, description="Leftover free-text terms for the normal search box.")
    color_hex: str | None = Field(default=None, description="A colour to apply to the colour-similarity filter.")
    sort: dict | None = Field(default=None, description="{field, direction} to sort by, or null.")


@router.post(
    "/nl-search",
    name="Translate a natural-language spool search",
    description=(
        "Translate free text into the spool list's existing filter model: grounded, editable filter "
        "values plus optional free-text, colour, and sort. Values are validated against the real "
        "vocabulary, so hallucinated ones are dropped. 404 until enabled; 409 until configured."
    ),
    responses={404: {"model": Message}, 409: {"model": Message}},
)
async def nl_search(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: NLSearchRequest,
) -> NLSearchResponse:
    if not (await ai.get_feature_flags(db)).get("nl_search"):
        raise HTTPException(status_code=404, detail="Natural-language search is not enabled.")
    config = await ai.resolve_config(db)
    if not config.configured:
        raise HTTPException(status_code=409, detail="No AI endpoint and model are configured.")
    result = await nlsearch.translate(db, config, body.query, locale=(body.locale or "en").strip()[:20] or "en")
    return NLSearchResponse(**result)


# --- Voice input: speech-to-text (#363) --------------------------------------------

#: ~25 MB, matching the common Whisper upload ceiling; a push-to-talk clip is far smaller.
#: BodyLimitMiddleware refuses a larger request body before it is buffered; the read below
#: is still bounded so nothing here depends on that middleware being installed.
_MAX_AUDIO_BYTES = bodylimit.MAX_AUDIO_BODY_BYTES


class TranscriptionResponse(BaseModel):
    text: str = Field(description="The recognised text. The user reviews it before it is sent.")


@router.post(
    "/transcribe",
    name="Transcribe a voice clip",
    description=(
        "Forward a recorded audio clip to the configured speech-to-text endpoint and return the "
        "recognised text (the client reviews it before sending). 404 until the voice feature is "
        "enabled; 409 until a speech-to-text endpoint and model are configured; 502 on provider trouble."
    ),
    responses={
        400: {"model": Message},
        404: {"model": Message},
        409: {"model": Message},
        413: {"model": Message},
        502: {"model": Message},
    },
)
async def transcribe(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File(description="The recorded audio clip.")],
) -> TranscriptionResponse:
    if not (await ai.get_feature_flags(db)).get("voice"):
        raise HTTPException(status_code=404, detail="Voice input is not enabled.")
    config = await ai.resolve_config(db)
    if not config.stt_configured:
        raise HTTPException(status_code=409, detail="No speech-to-text endpoint and model are configured.")

    # Read one byte past the cap rather than the whole upload: an oversize clip is
    # rejected without ever materialising it.
    audio = await file.read(_MAX_AUDIO_BYTES + 1)
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio clip is too large.")
    if not audio:
        raise HTTPException(status_code=400, detail="No audio was uploaded.")

    try:
        text = await voice.transcribe(
            config,
            audio,
            filename=file.filename or "audio.webm",
            content_type=file.content_type or "audio/webm",
        )
    except ai.AIRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TranscriptionResponse(text=text)


# --- Managed Ollama model pull (#364, F2) ------------------------------------------


class OllamaModelsResponse(BaseModel):
    is_ollama: bool = Field(description="Whether the configured endpoint is an Ollama server.")
    installed: list[str] = Field(default_factory=list, description="Model names installed on the server.")


class OllamaPullRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200, description="The Ollama model to pull, e.g. 'qwen3:8b'.")


def _sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get(
    "/ollama/models",
    name="List installed Ollama models",
    description=(
        "When the configured endpoint is an Ollama server, list the models installed on it so the "
        "UI can show recommended-vs-installed. Admin only. 409 until an endpoint is configured."
    ),
    responses={409: {"model": Message}, 502: {"model": Message}},
)
async def ollama_models(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[Principal, Depends(require_admin)],
) -> OllamaModelsResponse:
    config = await ai.resolve_config(db)
    if not config.base_url:
        raise HTTPException(status_code=409, detail="No AI endpoint is configured.")
    try:
        installed = await ollama.list_installed_models(config)
    except ai.AIRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if installed is None:
        return OllamaModelsResponse(is_ollama=False)
    return OllamaModelsResponse(is_ollama=True, installed=installed)


@router.post(
    "/ollama/pull",
    name="Pull an Ollama model",
    description=(
        "Drive Ollama's streaming pull for one model, relaying its download progress as Server-Sent "
        "Events (progress/done/error). Admin only. Spoolman manages models, never the runtime."
    ),
    responses={409: {"model": Message}},
)
async def ollama_pull(
    body: OllamaPullRequest,
    _admin: Annotated[Principal, Depends(require_admin)],
) -> StreamingResponse:
    # Resolve config on a short session released before streaming (it does no DB work).
    session_maker = get_session_maker()
    async with session_maker() as gate:
        config = await ai.resolve_config(gate)
    if not config.base_url:
        raise HTTPException(status_code=409, detail="No AI endpoint is configured.")
    try:
        installed = await ollama.list_installed_models(config)
    except ai.AIRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if installed is None:
        raise HTTPException(status_code=409, detail="The configured endpoint is not an Ollama server.")
    model = body.model.strip()

    async def stream() -> AsyncIterator[str]:
        try:
            async for progress in ollama.pull_model(config, model):
                total = progress.get("total")
                completed = progress.get("completed")
                has_progress = isinstance(total, (int, float)) and total and completed
                percent = int(completed / total * 100) if has_progress else None
                yield _sse_frame(
                    "progress",
                    {"status": progress.get("status", ""), "total": total, "completed": completed, "percent": percent},
                )
        except ai.AIRequestError as exc:
            # Log the specific cause server-side; the streamed body carries a curated,
            # non-exception-derived message so no internal detail can reach the client
            # (this raw SSE body is a response sink, unlike HTTPException.detail).
            logger.warning("Ollama model pull failed for %r: %s", model, exc)
            yield _sse_frame("error", {"message": "The model pull failed. Check the Spoolman server logs for details."})
        yield _sse_frame("done", {})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
