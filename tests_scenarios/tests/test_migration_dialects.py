"""Alembic chain up / anchor round-trip / re-upgrade on real Postgres, MariaDB and CockroachDB.

tests/test_migrations.py proves the chain + reversibility on SQLite only; the CI matrix
only ever migrates forward on an empty DB. This runs the same contract against the real
dialects (same images as tests_integration), including a data-preservation check across
the anchor downgrade/upgrade cycle. Local-only: skips without docker.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

from tests.migration_checks import assert_schema_matches_metadata

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")

REPO = Path(__file__).resolve().parent.parent.parent

# Last revision below the merge diamond; a relative "-1" is ambiguous there
# (see tests/test_migrations.py for the full rationale).
_ANCHOR = "d4e7a1b9c6f2"

_DIALECTS: dict[str, dict] = {
    "postgres": {
        "image": "postgres:11-alpine",
        "docker_env": {"POSTGRES_PASSWORD": "abc"},
        "container_port": 5432,
        "spoolman_env": {
            "SPOOLMAN_DB_TYPE": "postgres",
            "SPOOLMAN_DB_NAME": "postgres",
            "SPOOLMAN_DB_USERNAME": "postgres",
            "SPOOLMAN_DB_PASSWORD": "abc",
        },
        "drivername": "postgresql+asyncpg",
    },
    "mariadb": {
        "image": "mariadb:latest",
        "docker_env": {
            "MARIADB_USER": "john",
            "MARIADB_PASSWORD": "abc",
            "MARIADB_RANDOM_ROOT_PASSWORD": "yes",
            "MARIADB_DATABASE": "spoolman",
        },
        "container_port": 3306,
        "spoolman_env": {
            "SPOOLMAN_DB_TYPE": "mysql",
            "SPOOLMAN_DB_NAME": "spoolman",
            "SPOOLMAN_DB_USERNAME": "john",
            "SPOOLMAN_DB_PASSWORD": "abc",
        },
        "drivername": "mysql+aiomysql",
    },
    "cockroachdb": {
        "image": "cockroachdb/cockroach:v23.1.2",
        "docker_env": {"COCKROACH_USER": "john", "COCKROACH_DATABASE": "spoolman"},
        "container_port": 26257,
        "command": ["start-single-node", "--insecure"],
        "spoolman_env": {
            "SPOOLMAN_DB_TYPE": "cockroachdb",
            "SPOOLMAN_DB_NAME": "spoolman",
            "SPOOLMAN_DB_USERNAME": "john",
        },
        "drivername": "cockroachdb+asyncpg",
    },
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _dialect_db(cfg: dict) -> Iterator[dict[str, str]]:
    """Run the dialect's DB container, yielding the SPOOLMAN_DB_* env pointing at it."""
    port = _free_port()
    cmd = ["docker", "run", "-d", "--rm", "-p", f"{port}:{cfg['container_port']}"]
    for key, value in cfg["docker_env"].items():
        cmd += ["-e", f"{key}={value}"]
    cmd.append(cfg["image"])
    cmd += cfg.get("command", [])
    container = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()
    env = {**cfg["spoolman_env"], "SPOOLMAN_DB_HOST": "127.0.0.1", "SPOOLMAN_DB_PORT": str(port)}
    try:
        yield env
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)  # noqa: S607


def _async_url(cfg: dict, env: dict[str, str]) -> sqlalchemy.URL:
    return sqlalchemy.URL.create(
        drivername=cfg["drivername"],
        username=env.get("SPOOLMAN_DB_USERNAME"),
        password=env.get("SPOOLMAN_DB_PASSWORD"),
        host=env["SPOOLMAN_DB_HOST"],
        port=int(env["SPOOLMAN_DB_PORT"]),
        database=env.get("SPOOLMAN_DB_NAME"),
    )


async def _wait_ready(url: sqlalchemy.URL, timeout: int = 120) -> None:
    """Poll SELECT 1 until the DB accepts authenticated queries (image init can be slow)."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.execute(sqlalchemy.text("SELECT 1"))
        except Exception as e:  # noqa: BLE001 -- any driver/refused/init error means "not ready yet"
            last = str(e)
            await asyncio.sleep(1)
        else:
            return
        finally:
            await engine.dispose()
    raise TimeoutError(f"database not ready in {timeout}s: {last}")


def _alembic(env: dict[str, str], *args: str) -> None:
    subprocess.run(["alembic", *args], check=True, cwd=REPO, env={**os.environ, **env})  # noqa: S607


async def _assert_schema_and_count(engine: AsyncEngine, name: str) -> int:
    async with engine.connect() as conn:
        await conn.run_sync(assert_schema_matches_metadata)
        result = await conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM vendor WHERE name = :name"), {"name": name})
        return result.scalar_one()


@pytest.mark.parametrize("dialect", ["postgres", "mariadb", "cockroachdb"])
async def test_migration_chain_upgrades_round_trips_and_preserves_data(dialect: str):
    cfg = _DIALECTS[dialect]
    with _dialect_db(cfg) as env:
        url = _async_url(cfg, env)
        await _wait_ready(url)
        _alembic(env, "upgrade", "head")

        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(assert_schema_matches_metadata)
                insert = "INSERT INTO vendor (registered, name) VALUES ('2024-01-01 00:00:00', 'dialect-check')"
                await conn.execute(sqlalchemy.text(insert))
            # Round-trip every revision above the anchor (both merge branches) and back.
            _alembic(env, "downgrade", _ANCHOR)
            _alembic(env, "upgrade", "head")
            count = await _assert_schema_and_count(engine, "dialect-check")
            assert count == 1, "vendor row lost across the downgrade/upgrade cycle"
        finally:
            await engine.dispose()
