"""Render a temporary docker-compose file for a scenario (v1 syntax)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from tests_scenarios.catalog import Arch, Proxy

if TYPE_CHECKING:
    from tests_scenarios.catalog import Scenario

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "tests_integration"
PROXIES = Path(__file__).resolve().parent / "proxies"

# Image + in-container config path for each proxy kind.
_PROXY_IMAGE = {
    Proxy.NGINX: "nginx:alpine",
    Proxy.TRAEFIK: "traefik:v3",
    Proxy.CADDY: "caddy:2-alpine",
}
_PROXY_CONFIG_TARGET = {
    Proxy.NGINX: "/etc/nginx/conf.d/default.conf",
    Proxy.TRAEFIK: "/etc/traefik/dynamic.yml",
    Proxy.CADDY: "/etc/caddy/Caddyfile",
}


def _render_proxy_config(scenario: Scenario) -> str:
    """Render the config-file text for `scenario`'s proxy, filling in the sub-path placeholder."""
    subpath = scenario.subpath
    if scenario.proxy is Proxy.NGINX:
        tmpl = PROXIES / "nginx" / ("subpath.conf.tmpl" if subpath else "root.conf.tmpl")
        return tmpl.read_text().replace("{{SUBPATH}}", subpath)
    if scenario.proxy is Proxy.CADDY:
        tmpl = PROXIES / "caddy" / ("Caddyfile.tmpl" if subpath else "root.Caddyfile.tmpl")
        return tmpl.read_text().replace("{{SUBPATH}}", subpath)
    if scenario.proxy is Proxy.TRAEFIK:
        tmpl = PROXIES / "traefik" / "dynamic.yml.tmpl"
        # ROUTE is the bare sub-path (e.g. "spoolman"), or "" for root -- the template's leading
        # "/" then yields "PathPrefix(`/`)" for root and "PathPrefix(`/spoolman`)" for the sub-path.
        return tmpl.read_text().replace("{{ROUTE}}", subpath)
    raise AssertionError(f"unhandled proxy kind: {scenario.proxy!r}")  # pragma: no cover


def _build_proxy_service(scenario: Scenario, *, host_port: int, config_path: Path) -> dict:
    """Build the compose service dict for `scenario`'s proxy, fronting the internal `spoolman`."""
    proxy = scenario.proxy
    target = _PROXY_CONFIG_TARGET[proxy]
    service: dict = {
        "image": _PROXY_IMAGE[proxy],
        "ports": [f"{host_port}:80"],
        "depends_on": ["spoolman"],
        "volumes": [f"{config_path}:{target}:ro"],
    }
    if proxy is Proxy.TRAEFIK:
        # File provider (no docker socket needed): static config lives on the command line,
        # dynamic (routing) config is the bind-mounted file above.
        service["command"] = [
            "--entrypoints.web.address=:80",
            "--providers.file.filename=/etc/traefik/dynamic.yml",
            "--providers.file.watch=true",
        ]
    return service


def render(scenario: Scenario, *, host_port: int, project: str, image: str = "spoolman:test") -> Path:
    """Write a temp compose file for `scenario`, publishing the server on `host_port`.

    With no proxy, `spoolman` itself publishes `host_port:8000`. With a proxy, `spoolman` stays
    internal (no published port) and a `proxy` service publishes `host_port:80`, forwarding to
    `spoolman:8000` per the scenario's sub-path (or root) via a rendered, bind-mounted config.

    `image` sets the `spoolman` service's image (defaults to the standing `spoolman:test`, the
    amd64-only path used by every scenario before the arch axis existed). For non-amd64 arches, a
    `platform:` key pinning `scenario.platform()` is also set on `spoolman` -- and only `spoolman`;
    the db and proxy services stay on their published (amd64) images regardless of the scenario's
    arch. The amd64 path is otherwise untouched, so existing scenarios render byte-identical output.
    """
    base = yaml.safe_load((BASE / f"docker-compose-{scenario.db}.yml").read_text())
    services = base["services"]
    spoolman = services["spoolman"]
    spoolman["image"] = image
    if scenario.arch is not Arch.AMD64:
        spoolman["platform"] = scenario.platform()
    spoolman.setdefault("environment", {})
    if isinstance(spoolman["environment"], list):  # normalize KEY=VAL list -> dict
        spoolman["environment"] = dict(kv.split("=", 1) for kv in spoolman["environment"])
    spoolman["environment"].update(scenario.env())
    # Drop the internal tester service -- the scenario harness asserts from the host.
    services.pop("tester", None)

    out = {"services": {"spoolman": spoolman}}
    # Keep any db service the base defined (postgres/mariadb/cockroachdb); sqlite has none.
    for name, svc in services.items():
        if name != "spoolman":
            out["services"][name] = svc

    tmp_dir = Path(tempfile.gettempdir())
    if scenario.proxy is Proxy.NONE:
        spoolman["ports"] = [f"{host_port}:8000"]
    else:
        spoolman.pop("ports", None)  # internal only -- the proxy is the only published port
        config_text = _render_proxy_config(scenario)
        # Written next to the (about-to-be-created) temp compose file, with an absolute path, so
        # the bind mount below never depends on the compose file's own directory.
        config_path = tmp_dir / f"{project}-proxy.conf"
        config_path.write_text(config_text)
        out["services"]["proxy"] = _build_proxy_service(scenario, host_port=host_port, config_path=config_path)

    with tempfile.NamedTemporaryFile(
            prefix=f"{project}-", suffix=".yml", delete=False, mode="w", dir=tmp_dir) as fd:
        fd.write(yaml.safe_dump(out))
    return Path(fd.name)
