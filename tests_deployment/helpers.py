"""Shared plumbing for the deployment-channel tests: subprocess, docker, and GitHub helpers.

Everything here shells out to the host `docker` CLI on purpose — the harness exercises the
same commands a user would run, and must not depend on the Python docker SDK.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: Label applied to every container/image the harness creates, so stale resources are
#: identifiable (and removable) even after an aborted run:
#:   docker ps -aq --filter label=spoolman-deploy-test | xargs -r docker rm -f
DOCKER_LABEL = "spoolman-deploy-test"

GITHUB_API = "https://api.github.com"


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"required tool '{name}' not found on PATH")
    return path


def run(
    args: list[str],
    *,
    timeout: float = 300,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with captured text output; on check failure include the output tail."""
    proc = subprocess.run(  # noqa: PLW1510 - check handled manually for a richer message
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout tail:\n{proc.stdout[-2000:]}\nstderr tail:\n{proc.stderr[-2000:]}"
        )
    return proc


def wait_for(
    probe: Callable[[], bool],
    *,
    timeout: float,
    interval: float = 2.0,
    what: str = "condition",
) -> None:
    """Poll ``probe`` until it returns True or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe():
            return
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout:.0f}s waiting for {what}")


def github_json(path: str, *, timeout: float = 30) -> dict:
    """GET a GitHub REST path (e.g. ``repos/o/r/releases/latest``) and parse the JSON body."""
    url = f"{GITHUB_API}/{path}"
    request = urllib.request.Request(url, headers=_github_headers())  # noqa: S310 - https literal above
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
        return json.load(resp)


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "spoolman-deploy-tests"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token and shutil.which("gh"):
        # Reuse the gh CLI login when present; keeps unauthenticated rate limits at bay.
        proc = subprocess.run([_tool("gh"), "auth", "token"], capture_output=True, text=True, check=False)
        token = proc.stdout.strip() if proc.returncode == 0 else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def download(url: str, dest: Path, *, timeout: float = 300) -> None:
    """Stream ``url`` to ``dest`` (https only)."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https download: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=_github_headers())  # noqa: S310 - checked https above
    with urllib.request.urlopen(request, timeout=timeout) as resp, dest.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(resp, out)


def http_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10) -> tuple[int, str]:
    """GET ``url`` returning (status, body); HTTP errors are returned, not raised."""
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
        raise ValueError(f"harness only talks to loopback, got: {url}")
    request = urllib.request.Request(url, headers=headers or {})  # noqa: S310 - loopback only, checked above
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")
    except OSError as err:
        # Connection refused/reset while a container is still booting — report as "not up"
        # (status 0) so polling probes can retry instead of crashing.
        return 0, str(err)


@dataclass
class Container:
    """A long-lived test container (``sleep infinity``) driven through ``docker exec``."""

    image: str
    name: str = field(default_factory=lambda: f"spoolman-deploy-{uuid.uuid4().hex[:8]}")
    publish: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)

    def start(self, *, command: list[str] | None = None, pull_timeout: float = 600) -> Container:
        """Create and start the container (defaults to an idle `sleep infinity`)."""
        args = [_tool("docker"), "run", "-d", "--label", DOCKER_LABEL, "--name", self.name]
        for spec in self.publish:
            args += ["-p", spec]
        for spec in self.volumes:
            args += ["-v", spec]
        args.append(self.image)
        args += command if command is not None else ["sleep", "infinity"]
        run(args, timeout=pull_timeout)
        return self

    def exec(
        self,
        script: str,
        *,
        workdir: str | None = None,
        timeout: float = 300,
        check: bool = True,
        input_text: str | None = None,
        detach: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``bash -c <script>`` inside the container."""
        args = [_tool("docker"), "exec"]
        if input_text is not None:
            args.append("-i")
        if detach:
            args.append("-d")
        if workdir:
            args += ["-w", workdir]
        args += [self.name, "bash", "-c", script]
        return run(args, timeout=timeout, check=check, input_text=input_text)

    def copy_in(self, src: Path, dest: str) -> None:
        """Copy a host file into the container."""
        run([_tool("docker"), "cp", str(src), f"{self.name}:{dest}"])

    def port(self, container_port: int) -> str:
        """Host ``ip:port`` that maps to ``container_port`` (requires a ``publish`` spec)."""
        proc = run([_tool("docker"), "port", self.name, f"{container_port}/tcp"])
        return proc.stdout.strip().splitlines()[0]

    def logs(self, *, tail: int = 100) -> str:
        """Return the last ``tail`` lines of container output."""
        proc = run([_tool("docker"), "logs", "--tail", str(tail), self.name], check=False)
        return proc.stdout + proc.stderr

    def remove(self) -> None:
        """Force-remove the container (kept alive when SPOOLMAN_DEPLOY_KEEP is set)."""
        if os.environ.get("SPOOLMAN_DEPLOY_KEEP"):
            return  # leave the container around for post-mortem debugging
        run([_tool("docker"), "rm", "-f", self.name], check=False)


def docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    return subprocess.run([docker, "info"], capture_output=True, check=False).returncode == 0
