"""Integration tests for GET /info's external_db_name and POST /backup's created flag.

Ported from upstream: Info gained external_db_name (surfacing get_external_db_name()), and
backup_global_db() now returns a BackupResult with both .path and .created, threaded through to
BackupResponse.created. These two live on spoolman.api.v1.router.app directly (module-level
routes, not a separate APIRouter), so this drives the real app rather than the conftest client
fixture's partial one.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import create_async_engine

from spoolman.api.v1.router import app
from spoolman.database import database as db_module
from spoolman.database.models import Base


@pytest_asyncio.fixture
async def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """Yield an AsyncClient bound to the real, full application (spoolman.api.v1.router.app)."""
    monkeypatch.setenv("SPOOLMAN_DIR_DATA", str(tmp_path))

    db_path = tmp_path / "spoolman-test.db"
    url = URL.create("sqlite+aiosqlite", database=str(db_path))

    ddl_engine = create_async_engine(url)
    async with ddl_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ddl_engine.dispose()

    db_module.setup_db(url)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    app_db = getattr(db_module, "__db", None)
    if app_db is not None and app_db.engine is not None:
        await app_db.engine.dispose()


async def test_info_reports_default_external_db_name(app_client: AsyncClient):
    resp = await app_client.get("/info")
    assert resp.status_code == 200, resp.text
    assert resp.json()["external_db_name"] == "SpoolmanDB"


async def test_info_reports_overridden_external_db_name(
    app_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("EXTERNAL_DB_NAME", "My Filament Catalog")
    resp = await app_client.get("/info")
    assert resp.status_code == 200, resp.text
    assert resp.json()["external_db_name"] == "My Filament Catalog"


async def test_backup_response_has_path_and_created(app_client: AsyncClient):
    resp = await app_client.post("/backup")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"]
    assert body["created"] is True


async def test_repeated_backup_calls_do_not_each_rotate(app_client: AsyncClient):
    """Rate-limit guard, ported from upstream's backup-rotation hardening.

    Rapid repeated POST /backup calls must not each count as a fresh rotation.
    """
    first = (await app_client.post("/backup")).json()
    assert first["created"] is True

    second = (await app_client.post("/backup")).json()
    assert second["created"] is False
    assert second["path"] == first["path"]
