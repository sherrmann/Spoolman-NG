"""Scenario definitions: the axes, the curated core set, and expansion."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# A fixed, non-secret token is fine — these stacks are throwaway and never exposed.
_STATIC_TOKEN = "sk_scenario_local_admin"  # noqa: S105
_USER = "tester"
_PASSWORD = "tester-pass"  # noqa: S105
_SECRET = "scenario-signing-secret"  # noqa: S105


class Db(StrEnum):
    """Supported database backends for a scenario."""

    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MARIADB = "mariadb"
    COCKROACH = "cockroachdb"


class Auth(StrEnum):
    """Supported authentication modes for a scenario."""

    NONE = "none"
    TOKEN = "token"  # noqa: S105 -- enum member value, not a credential
    USERS = "users"


class Proxy(StrEnum):
    """Supported reverse-proxy fronting a scenario."""

    NONE = "none"
    NGINX = "nginx"
    TRAEFIK = "traefik"
    CADDY = "caddy"


class Arch(StrEnum):
    """Supported CPU architectures for a scenario's containers."""

    AMD64 = "amd64"
    ARM64 = "arm64"
    ARMV7 = "armv7"


_ARCH_WEIGHT = {Arch.AMD64: 1, Arch.ARM64: 4, Arch.ARMV7: 6}
_PLATFORM = {Arch.AMD64: "linux/amd64", Arch.ARM64: "linux/arm64", Arch.ARMV7: "linux/arm/v7"}


def platform_for(arch: Arch) -> str:
    """Docker `--platform` string for `arch` (module-level twin of `Scenario.platform()`).

    Used by `runner.ensure_image`, which only has an `Arch` in hand (not a full `Scenario`), to
    keep a single source of truth for the arch->platform mapping.
    """
    return _PLATFORM[arch]


@dataclass(frozen=True)
class Scenario:
    """A single deployment configuration to bring up and test."""

    name: str
    db: Db
    auth: Auth = Auth.NONE
    proxy: Proxy = Proxy.NONE
    subpath: str = ""
    arch: Arch = Arch.AMD64
    seed: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def platform(self) -> str:
        """Docker `--platform` string for this scenario's architecture."""
        return platform_for(self.arch)

    def weight(self) -> int:
        """Relative scheduling cost (heavier archs run fewer-at-a-time)."""
        return _ARCH_WEIGHT[self.arch]

    def env(self) -> dict[str, str]:
        """Server-container env for this scenario."""
        env: dict[str, str] = {}
        if self.subpath:
            env["SPOOLMAN_BASE_PATH"] = self.subpath
        if self.auth is Auth.TOKEN:
            env["SPOOLMAN_API_TOKEN"] = _STATIC_TOKEN
        elif self.auth is Auth.USERS:
            env["SPOOLMAN_AUTH_SECRET"] = _SECRET
        return env

    def test_env(self) -> dict[str, str]:
        """Env the assertion suites need to target this scenario (URL is added by the runner)."""
        env: dict[str, str] = {}
        if self.auth is Auth.TOKEN:
            env["SPOOLMAN_TEST_TOKEN"] = _STATIC_TOKEN
        elif self.auth is Auth.USERS:
            env["SPOOLMAN_TEST_LOGIN"] = f"{_USER}:{_PASSWORD}"
        return env


CORE: list[Scenario] = [
    Scenario("sqlite-bare", Db.SQLITE, tags=("core",)),
    Scenario("postgres-auth-nginx-subpath", Db.POSTGRES, Auth.TOKEN, Proxy.NGINX,
             subpath="spoolman", seed=True, tags=("core", "auth", "proxy")),
    Scenario("mariadb-traefik-root", Db.MARIADB, Auth.NONE, Proxy.TRAEFIK, tags=("core", "proxy")),
    Scenario("cockroach-users-caddy-subpath", Db.COCKROACH, Auth.USERS, Proxy.CADDY,
             subpath="spoolman", tags=("core", "auth", "proxy")),
    Scenario("armv7-sqlite", Db.SQLITE, arch=Arch.ARMV7, tags=("core", "arch")),
]


def expand(
    *,
    tags: Iterable[str] | None = None,
    dbs: Iterable[Db] | None = None,
    auths: Iterable[Auth] | None = None,
    proxies: Iterable[Proxy] | None = None,
    arches: Iterable[Arch] | None = None,
) -> list[Scenario]:
    """Cross-product the requested axes; unspecified axes take a single sensible default."""
    dbs = list(dbs) if dbs else [Db.SQLITE]
    auths = list(auths) if auths else [Auth.NONE]
    proxies = list(proxies) if proxies else [Proxy.NONE]
    arches = list(arches) if arches else [Arch.AMD64]
    out: list[Scenario] = []
    for db in dbs:
        for auth in auths:
            for proxy in proxies:
                for arch in arches:
                    sub = "spoolman" if proxy is not Proxy.NONE else ""
                    name = f"{db}-{auth}-{proxy}-{arch}"
                    out.append(Scenario(name, db, auth, proxy, subpath=sub, arch=arch,
                                        tags=tuple(tags or ())))
    return out
