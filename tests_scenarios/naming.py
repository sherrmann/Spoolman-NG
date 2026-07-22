"""Pure, docker-free helpers: free ports and unique compose project names."""

from __future__ import annotations

import secrets
import socket


def free_port() -> int:
    """Ask the OS for an unused TCP port (bind :0, read it back, release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def project_name(scenario_name: str) -> str:
    """Return a unique, docker-compose-safe project name so parallel stacks never collide."""
    suffix = secrets.token_hex(3)
    return f"spoolman-scn-{scenario_name}-{suffix}".lower()
