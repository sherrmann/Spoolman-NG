"""Main entrypoint to the server."""

import logging
import subprocess
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from prometheus_client import generate_latest
from scheduler.asyncio.scheduler import Scheduler

from spoolman import env, externaldb, tigertagdb, updatecheck
from spoolman.api.v1.router import app as v1_app
from spoolman.assetlinks import register_assetlinks_route
from spoolman.auth import auth_state, initialize_auth_state
from spoolman.client import (
    CONFIG_CACHE_HEADERS,
    SinglePageApplication,
    build_configjs,
    get_ingress_base_path,
)
from spoolman.database import database
from spoolman.prometheus.metrics import BUILD_INFO, registry

# Define a console logger
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(name)-26s %(levelname)-8s %(message)s"))

# Setup the spoolman logger, which all spoolman modules will use
log_level = env.get_logging_level()
root_logger = logging.getLogger()
root_logger.setLevel(log_level)
root_logger.addHandler(console_handler)

# Fix uvicorn logging
logging.getLogger("uvicorn").setLevel(log_level)
if logging.getLogger("uvicorn").handlers:
    logging.getLogger("uvicorn").removeHandler(logging.getLogger("uvicorn").handlers[0])
logging.getLogger("uvicorn").addHandler(console_handler)

logging.getLogger("uvicorn.error").setLevel(log_level)

access_handlers = logging.getLogger("uvicorn.access").handlers
if access_handlers:
    logging.getLogger("uvicorn.access").setLevel(log_level)
    logging.getLogger("uvicorn.access").removeHandler(access_handlers[0])
    logging.getLogger("uvicorn.access").addHandler(console_handler)

# Get logger instance for this module
logger = logging.getLogger(__name__)


# Setup FastAPI
app = FastAPI(
    debug=env.is_debug_mode(),
    title="Spoolman NG",
    version=env.get_version(),
)
app.add_middleware(GZipMiddleware)
app.mount(env.get_base_path() + "/api/v1", v1_app)


# WA for prometheus /metrics bind with SinglePageApp at root
@app.get(
    env.get_base_path() + "/metrics",
    response_class=PlainTextResponse,
    name="Get metrics for prometheus",
    description=(
        "Get app metrics for prometheusIf enabled SPOOLMAN_METRICS_ENABLED returned metrics by Spools and Filaments"
    ),
)
def get_metrics() -> bytes:
    """Return prometheus metrics."""
    return generate_latest(registry)


base_path = env.get_base_path()
ha_ingress = env.is_ha_ingress()
if ha_ingress:
    logger.info("Home Assistant ingress support is enabled.")
if base_path != "":
    logger.info("Base path is: %s", base_path)

    # If base path is set, add a redirect from non-slash suffix to slash
    # suffix. Otherwise it won't work.
    @app.get(base_path)
    def root_redirect() -> Response:
        """Redirect to base path."""
        return RedirectResponse(base_path + "/")


# Return a dynamic js config file
# This is so that the client side can access the base path variable.
# Under HA ingress mode the base is resolved per-request from the validated
# X-Ingress-Path header (HA's rotating per-session prefix); without the header
# the output is byte-identical to the static one (#211).
@app.get(env.get_base_path() + "/config.js")
def get_configjs(request: Request) -> Response:
    """Return a dynamic js config file."""
    ingress_base = get_ingress_base_path(request.headers) if ha_ingress else None
    return Response(
        content=build_configjs(base_path, ingress_base),
        media_type="text/javascript",
        headers=CONFIG_CACHE_HEADERS,
    )


# Android Digital Asset Links for companion-app passkeys. Like /metrics, this
# must be registered before the SPA catch-all below; unlike every other route
# it lives at the true domain root (Android ignores SPOOLMAN_BASE_PATH).
register_assetlinks_route(app)

# Mount the client side app
app.mount(
    base_path,
    app=SinglePageApplication(directory="client/dist", base_path=env.get_base_path(), ha_ingress=ha_ingress),
)


def add_cors_middleware() -> None:
    """Add CORS middleware to the FastAPI app based on environment settings."""
    origins = []
    if env.is_debug_mode():
        logger.warning("Running in debug mode, allowing all origins.")
        origins = ["*"]
    elif env.is_cors_defined():
        cors_origins = env.get_cors_origin()
        if cors_origins:
            logger.info("CORS origins defined: %s", cors_origins)
            origins = cors_origins
        else:
            logger.warning("CORS origins are not defined, no CORS will be applied.")

    if not origins:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],
    )


add_cors_middleware()


def add_file_logging() -> None:
    """Add file logging to the root logger."""
    # Define a file logger with log rotation
    log_file = env.get_logs_dir().joinpath("spoolman.log")
    file_handler = TimedRotatingFileHandler(log_file, when="midnight", backupCount=5)
    file_handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(message)s", "%Y-%m-%d %H:%M:%S"))
    root_logger.addHandler(file_handler)

    logging.getLogger("uvicorn").addHandler(file_handler)
    access_handlers = logging.getLogger("uvicorn.access").handlers
    if access_handlers:
        logging.getLogger("uvicorn.access").addHandler(file_handler)


@app.on_event("startup")
async def startup() -> None:
    """Run the service's startup sequence."""
    # Check that the data directory is writable
    env.check_write_permissions()

    # Don't add file logging until we have verified that the data directory is writable
    add_file_logging()

    version = app.version
    commit = env.get_commit_hash() or ""
    build_date = env.get_build_date()

    logger.info(
        "Starting Spoolman v%s (commit: %s) (built: %s)",
        version,
        commit,
        build_date,
    )

    BUILD_INFO.info(
        {
            "version": version,
            "commit": commit,
            "build_date": str(build_date) if build_date else "",
        }
    )

    logger.info("Using data directory: %s", env.get_data_dir().resolve())
    logger.info("Using logs directory: %s", env.get_logs_dir().resolve())
    logger.info("Using backups directory: %s", env.get_backups_dir().resolve())

    logger.info("Setting up database...")
    database.setup_db(database.get_connection_url())

    logger.info("Performing migrations...")
    # Run alembic in a subprocess.
    # There is some issue with the uvicorn worker that causes the process to hang when running alembic directly.
    # See: https://github.com/sqlalchemy/alembic/discussions/1155
    project_root = Path(__file__).parent.parent
    subprocess.run(["alembic", "upgrade", "head"], check=True, cwd=project_root)  # noqa: ASYNC221, S607

    # Initialize auth state now that the schema exists (#48/#52): static token, signing secret and
    # whether any accounts exist. Kept in sync afterwards by the account endpoints.
    session_gen = database.get_db_session()
    session = await session_gen.__anext__()
    try:
        await initialize_auth_state(session)
    finally:
        await session_gen.aclose()

    # Deliberate (#232): /metrics is served from the root app and is NOT behind the API
    # auth middleware — Prometheus scrapers conventionally run without credentials. Make
    # that visible when both features are on, since the gauges include inventory + prices.
    if env.is_metrics_enabled() and auth_state.auth_required():
        logger.info(
            "Metrics are enabled: /metrics is intentionally unauthenticated even though API "
            "auth is configured - keep it on a trusted network or restrict it at the proxy.",
        )

    # Setup scheduler
    schedule = Scheduler()
    database.schedule_tasks(schedule)
    externaldb.schedule_tasks(schedule)
    tigertagdb.schedule_tasks(schedule)
    updatecheck.schedule_tasks(schedule)

    # Initialize NFC service if enabled
    if env.is_nfc_enabled():
        try:
            from spoolman.nfc_service import nfc_service  # noqa: PLC0415

            nfc_service.initialize()
            logger.info("NFC service initialized: %s", nfc_service.get_status())
        except Exception:
            logger.exception("Failed to initialize NFC service")

    logger.info("Startup complete.")

    if env.is_docker() and not env.is_data_dir_mounted():
        logger.warning("!!!! WARNING !!!!")
        logger.warning("!!!! WARNING !!!!")
        logger.warning("The data directory is not mounted.")
        logger.warning(
            'Spoolman stores its database in the container directory "%s". '
            "If this directory isn't mounted to the host OS, the database will be lost when the container is stopped.",
            env.get_data_dir(),
        )
        logger.warning(
            "Please carefully read the docker part of the README.md file, "
            "and ensure your docker-compose file matches the example.",
        )
        logger.warning("!!!! WARNING !!!!")
        logger.warning("!!!! WARNING !!!!")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
