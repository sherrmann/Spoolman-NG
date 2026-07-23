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

import base64
import binascii
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai, spoolintake
from spoolman.api.v1.auth import require_admin
from spoolman.api.v1.models import Message
from spoolman.auth import Principal
from spoolman.database.database import get_db_session

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
    api_key: str | None = Field(description="The API key to store, or null to clear the stored key.")


class AIKeyResponse(BaseModel):
    api_key_set: bool = Field(description="Whether an API key is now in effect (env or stored).")
    env_locked: bool = Field(description="True when SPOOLMAN_AI_API_KEY is set, which overrides the stored key.")


@router.get(
    "/status",
    name="Get AI status",
    description=(
        "Get the effective AI provider configuration, feature toggles, and the most recent "
        "capability probe. The API key is never returned, only whether one is set."
    ),
)
async def status(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIStatus:
    config = await ai.resolve_config(db)
    cached = ai.get_cached_probe()
    return AIStatus(
        configured=config.configured,
        base_url=config.base_url,
        model=config.model,
        vision_model=config.vision_model,
        api_key_set=config.api_key is not None,
        env_locked=sorted(attr for attr, source in config.sources.items() if source == "env"),
        features=await ai.get_feature_flags(db),
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
    name="Set the AI API key",
    description=(
        "Store or clear the AI provider API key. Write-only: no endpoint ever returns the key. "
        "When SPOOLMAN_AI_API_KEY is set it overrides whatever is stored here."
    ),
)
async def set_key(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[Principal, Depends(require_admin)],
    body: AIKeyRequest,
) -> AIKeyResponse:
    await ai.set_stored_api_key(db, body.api_key.strip() if body.api_key else None)
    config = await ai.resolve_config(db)
    return AIKeyResponse(
        api_key_set=config.api_key is not None,
        env_locked=config.sources.get("api_key") == "env",
    )


# --- Scan-to-Spool intake (#361) ---------------------------------------------------

#: ~15 MB of image after base64 decoding; photos should be client-downscaled anyway.
_MAX_IMAGE_B64_CHARS = 20 * 1024 * 1024
_ALLOWED_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})


class AIExtraction(BaseModel):
    """The extraction JSON contract, shared with future on-device extractors (F5)."""

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
    responses={404: {"model": Message}, 409: {"model": Message}, 502: {"model": Message}},
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
