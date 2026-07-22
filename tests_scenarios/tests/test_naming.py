"""Tests for the naming module (free_port and project_name helpers)."""

import re

from tests_scenarios.naming import free_port, project_name


def test_free_port_returns_distinct_usable_ports():
    a, b = free_port(), free_port()
    assert 1024 < a < 65536
    assert a != b


def test_project_name_is_docker_safe_and_unique():
    n1 = project_name("postgres-auth-nginx-subpath")
    n2 = project_name("postgres-auth-nginx-subpath")
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", n1)
    assert n1 != n2  # includes a random suffix
    assert n1.startswith("spoolman-scn-postgres-auth-nginx-subpath-")
