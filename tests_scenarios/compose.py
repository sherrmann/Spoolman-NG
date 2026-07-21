"""Render a temporary docker-compose file for a scenario (v1 syntax)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from tests_scenarios.catalog import Proxy, Scenario

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "tests_integration"


def render(scenario: Scenario, *, host_port: int, project: str) -> Path:
    """Write a temp compose file for `scenario`, publishing the server on `host_port`."""
    if scenario.proxy is not Proxy.NONE:
        raise NotImplementedError("proxy overlays land in Phase 5")
    base = yaml.safe_load((BASE / f"docker-compose-{scenario.db}.yml").read_text())
    services = base["services"]
    spoolman = services["spoolman"]
    spoolman.setdefault("environment", {})
    if isinstance(spoolman["environment"], list):  # normalize KEY=VAL list -> dict
        spoolman["environment"] = dict(kv.split("=", 1) for kv in spoolman["environment"])
    spoolman["environment"].update(scenario.env())
    spoolman["ports"] = [f"{host_port}:8000"]
    # Drop the internal tester service -- the scenario harness asserts from the host.
    services.pop("tester", None)
    out = {"services": {"spoolman": spoolman}}
    # Keep any db service the base defined (postgres/mariadb/cockroachdb); sqlite has none.
    for name, svc in services.items():
        if name != "spoolman":
            out["services"][name] = svc
    with tempfile.NamedTemporaryFile(
            prefix=f"{project}-", suffix=".yml", delete=False, mode="w",
            dir=tempfile.gettempdir()) as fd:
        fd.write(yaml.safe_dump(out))
    return Path(fd.name)
