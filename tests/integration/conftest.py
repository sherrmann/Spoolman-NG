"""In-process integration harness (no Docker).

Spins the FastAPI routers up against a throwaway file-backed SQLite database and
drives them through httpx's ASGI transport, so endpoint behavior — request →
DB → response — can be asserted here in the fast unit job. This complements the
Docker-based multi-DB suite in tests_integration/ (which these do not replace).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from spoolman import extra_field_registry
from spoolman.api.v1 import (
    auth,
    export,
    field,
    filament,
    import_,
    location,
    nfc,
    order,
    other,
    printer,
    setting,
    shop,
    spool,
    stats,
    vendor,
)
from spoolman.database import database as db_module
from spoolman.database.models import Base


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Yield an AsyncClient bound to the API routers over a temp SQLite DB."""
    db_path = tmp_path / "spoolman-test.db"
    url = URL.create("sqlite+aiosqlite", database=str(db_path))

    # Create the schema with our own engine, then point the app's global DB at the
    # same file so its endpoints see the tables.
    ddl_engine = create_async_engine(url)
    async with ddl_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ddl_engine.dispose()

    db_module.setup_db(url)

    # The extra-field registry keeps a module-level cache; clear it so a field
    # defined in one test's DB doesn't leak into the next.
    extra_field_registry.extra_field_cache.clear()

    app = FastAPI()
    app.include_router(filament.router, prefix="/api/v1")
    app.include_router(vendor.router, prefix="/api/v1")
    app.include_router(shop.router, prefix="/api/v1")
    app.include_router(order.router, prefix="/api/v1")
    app.include_router(location.router, prefix="/api/v1")
    app.include_router(printer.router, prefix="/api/v1")
    app.include_router(spool.router, prefix="/api/v1")
    app.include_router(nfc.router, prefix="/api/v1")
    app.include_router(field.router, prefix="/api/v1")
    app.include_router(setting.router, prefix="/api/v1")
    app.include_router(export.router, prefix="/api/v1")
    app.include_router(import_.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    # other.router carries the byte-identical string /location endpoints, included so the
    # location-entity test can assert the two coexist without collision.
    app.include_router(other.router, prefix="/api/v1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    # Dispose the app's engine so aiosqlite's worker thread doesn't outlive the
    # test's event loop (otherwise teardown warns "Event loop is closed").
    app_db = getattr(db_module, "__db", None)
    if app_db is not None and app_db.engine is not None:
        await app_db.engine.dispose()
