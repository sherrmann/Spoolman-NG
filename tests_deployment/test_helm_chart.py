"""Helm chart e2e (#274/#277): install charts/spoolman-ng into a throwaway k3d cluster.

Creates a single-node k3s cluster in docker (k3d), `helm install`s the chart from the
working tree with the published `latest` image, waits for readiness (which exercises
the probes, the PVC via k3s's local-path provisioner, and the non-root security
context), then talks to the API through a port-forward. Skips when helm/k3d/kubectl
are not installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests_deployment.helpers import http_get, run, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.usefixtures("docker")

CLUSTER = "spoolman-deploy-helm"
CHART = str(Path(__file__).parent.parent / "charts" / "spoolman-ng")
PORT = 18081


def _tools() -> dict[str, str] | None:
    tools = {name: shutil.which(name) for name in ("helm", "k3d", "kubectl")}
    return None if None in tools.values() else tools  # type: ignore[return-value]


@pytest.fixture(scope="module")
def cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, str]]:
    """Create a throwaway k3d cluster; yields the env (isolated KUBECONFIG) for kubectl/helm."""
    tools = _tools()
    if tools is None:
        pytest.skip("helm, k3d, and kubectl are required (see tests_deployment/README.md)")
    env = {**os.environ, "KUBECONFIG": str(tmp_path_factory.mktemp("kube") / "config")}
    run([tools["k3d"], "cluster", "delete", CLUSTER], check=False, timeout=120)
    # First run pulls the k3s node image (~250 MB).
    proc = subprocess.run(
        [tools["k3d"], "cluster", "create", CLUSTER, "--wait", "--timeout", "180s"],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"k3d cluster create failed:\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
    try:
        yield env
    finally:
        if not os.environ.get("SPOOLMAN_DEPLOY_KEEP"):
            subprocess.run(
                [tools["k3d"], "cluster", "delete", CLUSTER], env=env, capture_output=True, timeout=180, check=False
            )


def test_chart_installs_and_serves(cluster: dict[str, str]) -> None:
    tools = _tools()
    assert tools
    env = cluster

    # --wait exercises the readiness probe, the PVC bind, and the non-root context.
    proc = subprocess.run(
        [tools["helm"], "install", "e2e", CHART, "--set", "image.tag=latest", "--wait", "--timeout", "6m"],
        env=env,
        capture_output=True,
        text=True,
        timeout=420,
        check=False,
    )
    if proc.returncode != 0:
        events = subprocess.run(
            [tools["kubectl"], "get", "events", "--sort-by=.lastTimestamp"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        pytest.fail(f"helm install failed:\n{proc.stderr[-1500:]}\nevents:\n{events.stdout[-1500:]}")

    ready = subprocess.run(
        [tools["kubectl"], "get", "deployment", "e2e-spoolman-ng", "-o", "jsonpath={.status.readyReplicas}"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert ready.stdout.strip() == "1"

    forward = subprocess.Popen(
        [tools["kubectl"], "port-forward", "svc/e2e-spoolman-ng", f"{PORT}:80"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(
            lambda: http_get(f"http://127.0.0.1:{PORT}/api/v1/health", timeout=3)[0] == 200,
            timeout=60,
            what="the chart's service to answer through the port-forward",
        )
        status, body = http_get(f"http://127.0.0.1:{PORT}/api/v1/info", timeout=5)
        assert status == 200
        info = json.loads(body)
        assert info["version"], info
    finally:
        forward.terminate()
        forward.wait(timeout=10)
        time.sleep(0)  # yield so the terminate is processed before teardown logs
