"""Router setup for the v1 version of the API."""

# ruff: noqa: D103

import asyncio
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from spoolman import env, updateaction, updatecheck
from spoolman.api.v1.bodylimit import BodyLimitMiddleware
from spoolman.api.v1.errors import install_exception_handlers
from spoolman.auth import Principal, install_auth
from spoolman.client import resolve_client_serving, select_client
from spoolman.database.database import backup_global_db
from spoolman.externaldb import get_external_db_name
from spoolman.updateaction import InstallType
from spoolman.ws import websocket_manager

from . import (
    ai,
    auth,
    calibration,
    export,
    externaldb,
    field,
    filament,
    import_,
    location,
    models,
    nfc,
    order,
    other,
    printer,
    search,
    setting,
    shop,
    spool,
    stats,
    tag,
    vendor,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Spoolman NG REST API v1",
    version="1.0.0",
    description="""
    REST API for Spoolman NG.

    The API is served on the path `/api/v1/`.

    Some endpoints also serve a websocket on the same path. The websocket is used to listen for changes to the data
    that the endpoint serves. The websocket messages are JSON objects. Additionally, there is a root-level websocket
    endpoint that listens for changes to any data in the database.
    """,
)


install_exception_handlers(app)


# Add a general info endpoint
@app.get("/info")
async def info(request: Request) -> models.Info:
    """Return general info about the API."""
    update_status = updatecheck.get_status()
    gate = updateaction.evaluate_gate()
    # Resolved from this request's own cookie, the same way the mount that served the page
    # resolved it -- so a client asking "which one am I?" gets the answer for itself rather
    # than for whoever the server would serve by default.
    client_serving = resolve_client_serving(
        legacy_default=env.is_legacy_client_enabled(),
        switching_requested=env.is_client_switching_enabled(),
    )
    return models.Info(
        version=env.get_version(),
        debug_mode=env.is_debug_mode(),
        automatic_backups=env.is_automatic_backup_enabled(),
        data_dir=str(env.get_data_dir().resolve()),
        logs_dir=str(env.get_logs_dir().resolve()),
        backups_dir=str(env.get_backups_dir().resolve()),
        db_type=str(env.get_database_type() or "sqlite"),
        git_commit=env.get_commit_hash(),
        build_date=env.get_build_date(),
        update_check_enabled=env.is_update_check_enabled(),
        latest_version=update_status.latest_version,
        update_available=update_status.update_available,
        release_url=update_status.release_url,
        install_type=gate.install_type.value,
        update_action_available=gate.action_available,
        external_db_name=get_external_db_name(),
        clients_available=list(client_serving.available),
        client_active=select_client(request.headers, client_serving),
        client_switch_enabled=client_serving.switching_enabled,
    )


# Add health check endpoint
@app.get("/health")
async def health() -> models.HealthCheck:
    """Return a health check."""
    return models.HealthCheck(status="healthy")


# Add endpoint for triggering a db backup
@app.post(
    "/backup",
    description="Trigger a database backup. Only applicable for SQLite databases.",
    response_model=models.BackupResponse,
    responses={500: {"model": models.Message}},
)
async def backup():  # noqa: ANN201
    """Trigger a database backup."""
    result = await backup_global_db()
    if result.path is None:
        return JSONResponse(
            status_code=500,
            content={"message": "Backup failed. See server logs for more information."},
        )
    return models.BackupResponse(path=str(result.path), created=result.created)


# Trigger a native self-update (#294). This runs bundled code (scripts/update.sh), so it is
# admin-gated (require_admin) *and* refused on an open, no-auth instance unless
# SPOOLMAN_ALLOW_UI_UPDATE=TRUE — see spoolman/updateaction.py for the full security rationale.
# Only native installs expose it; Docker/HA callers get a 409 pointing at their own tooling.
@app.post(
    "/update",
    status_code=202,
    description=(
        "Trigger the bundled native updater (scripts/update.sh). Admin-only; only available on native "
        "installs, and disabled on an open (no-auth) instance unless SPOOLMAN_ALLOW_UI_UPDATE=TRUE."
    ),
    response_model=models.UpdateResponse,
    responses={403: {"model": models.Message}, 409: {"model": models.Message}},
)
async def trigger_update(
    body: models.UpdateRequest,
    _admin: Annotated[Principal, Depends(auth.require_admin)],
) -> models.UpdateResponse:
    """Launch the native updater in the background (see spoolman/updateaction.py)."""
    gate = updateaction.evaluate_gate()

    if gate.install_type is not InstallType.NATIVE:
        # No bundled updater to run; the client shows the right instructions per install type.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Self-update from the UI is not available for a '{gate.install_type.value}' install. "
                "Update via your platform's own tooling instead."
            ),
        )
    if not gate.gate_open:
        raise HTTPException(
            status_code=403,
            detail=(
                "UI-triggered updates are disabled on this instance. Configure authentication, or set "
                "SPOOLMAN_ALLOW_UI_UPDATE=TRUE to enable the update action on an open instance."
            ),
        )

    try:
        updateaction.trigger_update(body.tag)
    except ValueError as exc:
        # Belt-and-braces: the request model already rejects a malformed tag with 422.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return models.UpdateResponse(
        status="started",
        target=body.tag,
        restart_managed=updateaction.restart_is_managed(),
    )


@app.websocket(
    "/",
    name="Listen to any changes",
)
async def notify(
    websocket: WebSocket,
) -> None:
    await websocket.accept()
    websocket_manager.connect((), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect((), websocket)


# Add routers
app.include_router(calibration.router)
app.include_router(filament.router)
app.include_router(spool.router)
app.include_router(vendor.router)
app.include_router(shop.router)
app.include_router(order.router)
app.include_router(location.router)
app.include_router(printer.router)
app.include_router(setting.router)
app.include_router(field.router)
app.include_router(other.router)
app.include_router(externaldb.router)
app.include_router(nfc.router)
app.include_router(export.router)
app.include_router(import_.router)
app.include_router(stats.router)
app.include_router(ai.router)
app.include_router(auth.router)
app.include_router(tag.router)
app.include_router(search.router)

# Opt-in bearer-token auth (#48): installed only when SPOOLMAN_API_TOKEN is set, so the default
# deployment is unchanged. Guards this sub-app's HTTP routes and the websocket handshake uniformly.
install_auth(app)

# Body-size caps for the AI media uploads. Added last so it wraps outermost and rejects an
# oversize upload before auth, routing or body parsing buffers any of it.
app.add_middleware(BodyLimitMiddleware)
