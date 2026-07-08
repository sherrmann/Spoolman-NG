"""Alembic environment file."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection

from spoolman.database.database import Database, get_connection_url
from spoolman.database.models import Base
from spoolman.env import DatabaseType, get_database_type, get_db_schema

# Backends that support a schema/search_path (#78). MySQL and SQLite have no schema concept.
_SCHEMA_DIALECTS = {"postgresql", "cockroachdb"}


def _configured_schema() -> str | None:
    """Return the configured SPOOLMAN_DB_SCHEMA, guarding against SQL-breaking quote chars."""
    schema = get_db_schema()
    if schema and '"' in schema:
        raise ValueError("SPOOLMAN_DB_SCHEMA must not contain double-quote characters.")
    return schema


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    schema = _configured_schema()
    # Offline mode only emits SQL, so it cannot CREATE the schema; it just qualifies the version
    # table when a schema-capable backend is selected.
    schema_capable = get_database_type() in (DatabaseType.POSTGRES, DatabaseType.COCKROACHDB)
    version_table_schema = schema if schema and schema_capable else None

    context.configure(
        url=get_connection_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        version_table_schema=version_table_schema,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations in 'online' mode."""
    schema = _configured_schema()
    version_table_schema = None
    if schema and connection.dialect.name in _SCHEMA_DIALECTS:
        # The engine's search_path already points here (see database.connect), but create the schema
        # first so a fresh shared database works, and qualify the alembic version table explicitly.
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        version_table_schema = schema

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=version_table_schema,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine and associate a connection with the context."""
    db = Database(get_connection_url())
    db.connect()

    if db.engine is None:
        raise RuntimeError("Engine not created.")

    async with db.engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await db.engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
