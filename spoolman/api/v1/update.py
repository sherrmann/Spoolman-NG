"""Update-related endpoints for triggering per-install-type update actions (#294).

Security considerations:
- The update endpoint only runs the bundled `scripts/update.sh` on native installs
- Admin-gated when accounts exist; disabled by default without auth unless SPOOLMAN_ALLOW_UI_UPDATE=TRUE
- The action is inherently racy with the running process (uvicorn keeps serving from deleted files)
"""

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.types import Scope

from spoolman import env
from spoolman.auth import ROLE_ADMIN, Principal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="",
    tags=["update"],
)


def _get_principal(request: Request) -> Principal | None:
    """Extract the authenticated principal from the request."""
    scope: Scope = request.scope
    return scope.get("state", {}).get("principal")


def _is_admin(request: Request) -> bool:
    """Check if the request is from an admin user."""
    principal = _get_principal(request)
    if principal is None:
        return False
    return principal.role == ROLE_ADMIN


def _is_auth_enabled() -> bool:
    """Check if authentication is enabled (token or accounts exist)."""
    from spoolman.auth import auth_state  # noqa: PLC0415

    return auth_state.auth_required()


def _is_update_allowed() -> bool:
    """Check if UI-triggered updates are allowed.

    When no auth is configured, the button stays disabled unless SPOOLMAN_ALLOW_UI_UPDATE=TRUE
    is set explicitly - an open LAN instance must not expose a code-swap endpoint by default.
    """
    return env.is_ui_update_allowed()


def _detect_install_type() -> str:
    """Detect the installation type.

    Returns:
        str: One of "native", "docker", "ha_addon", or "unknown"
    """
    # Check for HA add-on first (most specific)
    if os.getenv("SUPERVISOR_TOKEN") is not None:
        return "ha_addon"

    # Check for Docker
    if Path("/.dockerenv").exists():
        return "docker"

    # Check for native install (scripts/update.sh exists next to the app)
    project_root = Path(__file__).parent.parent.parent
    if (project_root / "scripts" / "update.sh").exists() and (project_root / "release_info.json").exists():
        return "native"

    return "unknown"


def _validate_tag(tag: str | None) -> str | None:
    """Validate a version tag against the pattern ^v[0-9.]+$.

    Args:
        tag: The tag to validate

    Returns:
        str: The validated tag, or None if invalid
    """
    if tag is None:
        return None
    # Strip leading v/V for validation
    normalized = tag.lstrip("vV")
    # Must match ^[0-9.]+$
    if not re.fullmatch(r"^[0-9.]+$", normalized):
        return None
    return tag


class InstallTypeInfo(BaseModel):
    """Information about the installation type and available update actions."""

    install_type: str = Field(
        description="The detected installation type: native, docker, ha_addon, or unknown.",
        examples=["native"],
    )
    update_available: bool = Field(
        description="Whether an update is available (from the update check).",
        examples=[True],
    )
    latest_version: str | None = Field(
        description="The latest version available, or null if not checked yet.",
        examples=["2026.7.20"],
    )
    can_update: bool = Field(
        description="Whether the UI can trigger an update for this install type.",
        examples=[True],
    )
    update_button_enabled: bool = Field(
        description="Whether the update button should be shown (depends on auth and SPOOLMAN_ALLOW_UI_UPDATE).",
        examples=[True],
    )
    instructions: str | None = Field(
        description="Tailored update instructions for the install type, or null for native installs.",
        examples=["docker compose pull && docker compose up -d"],
    )


class UpdateResponse(BaseModel):
    """Response from triggering an update."""

    status: str = Field(
        description="The status of the update request.",
        examples=["started", "instructions"],
    )
    message: str = Field(
        description="A human-readable message about the update status.",
        examples=["Update started in background."],
    )
    instructions: str | None = Field(
        description="Update instructions for non-native install types.",
        examples=["docker compose pull && docker compose up -d"],
    )


@router.get(
    "/update/info",
    name="Get update info",
    description="Get information about the installation type and available update actions.",
    response_model=InstallTypeInfo,
)
async def get_update_info(
    request: Request,
) -> InstallTypeInfo:
    """Get information about the installation type and available update actions."""
    from spoolman import updatecheck  # noqa: PLC0415

    install_type = _detect_install_type()
    update_status = updatecheck.get_status()

    # Determine if update button should be enabled
    # For native installs, check if update is allowed and user is admin
    # For other types, button is not applicable (instructions shown instead)
    is_admin_user = _is_admin(request)
    update_allowed = _is_update_allowed()

    can_update = install_type == "native"
    update_button_enabled = can_update and update_allowed and is_admin_user

    # Generate tailored instructions for non-native types
    instructions = None
    if install_type == "docker":
        instructions = "docker compose pull && docker compose up -d"
    elif install_type == "ha_addon":
        instructions = "Please use the Home Assistant Supervisor update UI"

    return InstallTypeInfo(
        install_type=install_type,
        update_available=update_status.update_available,
        latest_version=update_status.latest_version,
        can_update=can_update,
        update_button_enabled=update_button_enabled,
        instructions=instructions,
    )


@router.post(
    "/update",
    name="Trigger update",
    description="Trigger an update for native installations. For Docker/HA add-on, returns instructions.",
    response_model=UpdateResponse,
    responses={
        403: {"description": "Update not allowed - authentication required or not a native install"},
        400: {"description": "Invalid tag specified"},
    },
)
async def trigger_update(
    request: Request,
    tag: str | None = None,
) -> UpdateResponse:
    """Trigger an update for native installations.

    For native installs, this runs scripts/update.sh in the background.
    For Docker/HA add-on, returns tailored instructions.

    Args:
        tag: Optional specific tag to update to (must match ^v[0-9.]+$).
             If not specified, updates to the latest release.

    Returns:
        UpdateResponse: Status and any instructions

    Raises:
        HTTPException: 403 if update not allowed, 400 if invalid tag
    """
    install_type = _detect_install_type()

    # Check if update is allowed
    if not _is_update_allowed():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Update not allowed. Set SPOOLMAN_ALLOW_UI_UPDATE=TRUE to enable when no auth is configured.",
        )

    # Check if user is admin
    if not _is_admin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Update requires admin privileges.",
        )

    # Validate tag if provided
    if tag is not None:
        validated_tag = _validate_tag(tag)
        if validated_tag is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tag: {tag}. Must match ^v[0-9.]+$ pattern.",
            )

    # Handle non-native install types
    if install_type != "native":
        if install_type == "docker":
            return UpdateResponse(
                status="instructions",
                message="Docker update instructions",
                instructions="docker compose pull && docker compose up -d",
            )
        elif install_type == "ha_addon":
            return UpdateResponse(
                status="instructions",
                message="Home Assistant add-on update",
                instructions="Please use the Home Assistant Supervisor update UI",
            )
        else:
            return UpdateResponse(
                status="instructions",
                message="Update instructions",
                instructions="Please update manually according to your installation method",
            )

    # For native installs, run the update script in the background
    project_root = Path(__file__).parent.parent.parent
    update_script = project_root / "scripts" / "update.sh"

    if not update_script.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Update script not found. This may not be a native installation.",
        )

    # Build the command
    cmd = ["bash", str(update_script)]
    if tag is not None:
        cmd.extend(["--tag", tag])

    logger.info("Starting update to tag %s in background", tag or "latest")

    # Run in background using subprocess with detached process
    try:
        # Use setsid to create a new session, detaching from the parent
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Update script started in background")
        return UpdateResponse(
            status="started",
            message="Update started in background. The service will restart automatically if systemd is configured.",
            instructions=None,
        )
    except OSError as e:
        logger.error("Failed to start update script: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start update: {e}",
        )
