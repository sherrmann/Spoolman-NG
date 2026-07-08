"""Unit tests for SPOOLMAN_DB_SCHEMA connect-args handling (issue #78).

Only PostgreSQL/CockroachDB (asyncpg) support a search_path; MySQL/SQLite must ignore the
setting with a warning rather than misapply it. Unset must be a no-op so default installs are
unaffected.
"""

import logging

import pytest

from spoolman.database.database import apply_schema_connect_args


@pytest.mark.parametrize("drivername", ["postgresql+asyncpg", "cockroachdb+asyncpg"])
def test_schema_sets_search_path_for_asyncpg(drivername: str):
    connect_args: dict = {}
    apply_schema_connect_args(connect_args, drivername, "myschema")
    assert connect_args == {"server_settings": {"search_path": "myschema"}}


def test_schema_merges_with_existing_server_settings():
    connect_args: dict = {"server_settings": {"application_name": "spoolman"}}
    apply_schema_connect_args(connect_args, "postgresql+asyncpg", "myschema")
    assert connect_args["server_settings"] == {"application_name": "spoolman", "search_path": "myschema"}


@pytest.mark.parametrize("drivername", ["sqlite+aiosqlite", "mysql+aiomysql"])
def test_schema_is_ignored_with_warning_for_non_schema_backends(
    drivername: str,
    caplog: pytest.LogCaptureFixture,
):
    connect_args: dict = {}
    with caplog.at_level(logging.WARNING):
        apply_schema_connect_args(connect_args, drivername, "myschema")
    assert connect_args == {}
    assert "no schema concept" in caplog.text


def test_no_schema_is_a_noop():
    connect_args: dict = {}
    apply_schema_connect_args(connect_args, "postgresql+asyncpg", None)
    assert connect_args == {}
