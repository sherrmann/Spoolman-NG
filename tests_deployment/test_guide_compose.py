"""Boot the wizard-generated database-sidecar compose files (#341).

The `guide-tests` CI job validates every wizard-generated compose file with
`docker compose config` — that proves *syntax*, not that the stack *boots*. The
Postgres/MariaDB sidecar recipes (`postgres:16-alpine` / `mariadb:lts` with
healthchecks, a named volume, `depends_on: condition: service_healthy`, and the full
`SPOOLMAN_DB_*` wiring) are new content that exists nowhere else in the docs, so —
unlike the SQLite quick start — they aren't proven by the integration matrix or by
real-user mileage.

This suite renders the guide's preset matrix (single source of truth — the same
`npm run render-matrix` CI uses) and, for the Postgres and MariaDB compose presets,
actually brings the stack up with the published image, waits out the healthcheck
chain, and asserts the server is really talking to the sidecar database: `/info`
reports the right `db_type`, and a spool created through the API lands as a row in
the Postgres/MariaDB container itself (not an accidental SQLite fallback).

Only deployment-environment specifics are overridden — the server image
(`SPOOLMAN_IMAGE`, like the other suites), the fixed `7912` host port (rebound to an
ephemeral loopback port so presets can't collide), the USB device passthrough of the
NFC preset (absent on a headless harness), and the documented ``change-me`` secret.
The database sidecar wiring under test is booted exactly as generated.

Rendering needs Node (the guide is a standalone npm/Vite project); set
``SPOOLMAN_GUIDE_MATRIX`` to a pre-rendered matrix directory to skip it, or the suite
skips cleanly when Node is unavailable. Nightly/release cadence — not PR-blocking.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from tests_deployment.helpers import DOCKER_LABEL, http_get, http_request, keep_resources, run, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.usefixtures("docker")

DOCKER = shutil.which("docker") or "docker"
GUIDE_DIR = Path(__file__).parent.parent / "guide"
#: The documented secret the wizard prints for the user to replace (guide placeholders).
DB_PASSWORD_PLACEHOLDER = "change-me"  # noqa: S105 - a placeholder to substitute, not a real secret

#: (preset id rendered by the guide, expected /info db_type). The Postgres preset also
#: exercises a `/spoolman` sub-path deploy; the MariaDB preset the PUID/PGID + TZ path.
DB_PRESETS = [
    ("compose-postgres-traefik-subpath-klipper", "postgres"),
    ("compose-mysql-nfc-puid-tz", "mysql"),
]


@pytest.fixture(scope="module")
def guide_matrix(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Directory holding every preset's rendered artifacts.

    Prefer a pre-rendered matrix (``SPOOLMAN_GUIDE_MATRIX``); otherwise render it here
    with the guide's own ``render-matrix`` script so the compose files under test are
    byte-for-byte what the wizard emits. Skips when Node isn't available.
    """
    prebuilt = os.environ.get("SPOOLMAN_GUIDE_MATRIX", "")
    if prebuilt:
        path = Path(prebuilt).resolve()
        if not path.is_dir():
            pytest.exit(f"SPOOLMAN_GUIDE_MATRIX does not exist: {path}")
        return path

    npm = shutil.which("npm")
    if npm is None or shutil.which("node") is None:
        pytest.skip("node/npm not available to render the guide matrix (set SPOOLMAN_GUIDE_MATRIX instead)")

    if not (GUIDE_DIR / "node_modules").is_dir():
        run([npm, "ci", "--prefix", str(GUIDE_DIR)], timeout=600)
    out = tmp_path_factory.mktemp("guide-matrix")
    # `npm run render-matrix -- --out <dir>` writes <dir>/<preset-id>/<filename>.
    run([npm, "run", "--prefix", str(GUIDE_DIR), "render-matrix", "--", "--out", str(out)], timeout=300)
    return out


def _compose(project: str, compose_file: Path, *args: str, timeout: float = 300, check: bool = True):  # noqa: ANN202
    """Run `docker compose` for one project; relative binds resolve beside the file."""
    return run(
        [
            DOCKER,
            "compose",
            "--project-directory",
            str(compose_file.parent),
            "-p",
            project,
            "-f",
            str(compose_file),
            *args,
        ],
        timeout=timeout,
        check=check,
    )


def _prepare(source: str, *, image: str, db_password: str) -> tuple[str, str]:
    """Return (compose YAML ready to boot, base path) from a rendered compose file.

    Substitutes only deployment-environment specifics; the DB sidecar service is left
    structurally intact. Also tags every service with the harness leak-cleanup label.
    """
    doc = yaml.safe_load(source)
    services = doc["services"]
    spoolman = services["spoolman"]
    spoolman["image"] = image
    spoolman["ports"] = ["127.0.0.1::8000"]  # ephemeral loopback; the fixed 7912 would collide
    spoolman.pop("devices", None)  # NFC USB passthrough — irrelevant here, absent on the harness

    base_path = ""
    for svc in services.values():
        env = svc.get("environment")
        if isinstance(env, list):
            svc["environment"] = [
                e.replace(DB_PASSWORD_PLACEHOLDER, db_password) if "PASSWORD=" in e else e for e in env
            ]
            for entry in env:
                if entry.startswith("SPOOLMAN_BASE_PATH="):
                    base_path = entry.split("=", 1)[1].split(" #", 1)[0].strip()
        labels = svc.get("labels")
        if isinstance(labels, list):
            labels.append(f"{DOCKER_LABEL}=1")
        elif isinstance(labels, dict):
            labels[DOCKER_LABEL] = "1"
        else:
            svc["labels"] = [f"{DOCKER_LABEL}=1"]

    return yaml.safe_dump(doc, sort_keys=False), base_path


def _sidecar_spool_count(project: str, compose_file: Path, db: str, password: str) -> int:
    """Count rows in the `spool` table inside the sidecar DB container itself."""
    if db == "postgres":
        proc = _compose(
            project,
            compose_file,
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "spoolman",
            "-d",
            "spoolman",
            "-tAc",
            "SELECT count(*) FROM spool",
        )
    else:
        proc = _compose(
            project,
            compose_file,
            "exec",
            "-T",
            "db",
            "mariadb",
            "-uspoolman",
            f"-p{password}",
            "-N",
            "-e",
            "SELECT count(*) FROM spool",
            "spoolman",
        )
    return int(proc.stdout.strip().splitlines()[-1])


@dataclass(frozen=True)
class Stack:
    """A booted preset stack, addressed through `docker compose -p <project>`."""

    project: str
    compose_file: Path
    base_path: str
    db_type: str
    db_password: str


@pytest.fixture
def _stack(request: pytest.FixtureRequest, guide_matrix: Path, tmp_path: Path) -> Iterator[Stack]:
    """Bring one preset's stack up (fresh volume) and tear it down afterwards."""
    preset_id, db_type = request.param
    source = (guide_matrix / preset_id / "docker-compose.yml").read_text()
    image = os.environ.get("SPOOLMAN_IMAGE", "ghcr.io/sherrmann/spoolman-ng:latest")
    db_password = secrets.token_hex(16)
    prepared, base_path = _prepare(source, image=image, db_password=db_password)

    (tmp_path / "data").mkdir()
    (tmp_path / "data").chmod(0o777)  # entrypoint chowns it, but be forgiving of the bind
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(prepared)

    project = f"spoolman-deploy-guide-{preset_id.replace('compose-', '')}"
    up = _compose(project, compose_file, "up", "-d", timeout=600, check=False)
    try:
        if up.returncode != 0:
            logs = _compose(project, compose_file, "logs", "--tail", "80", check=False)
            pytest.fail(
                f"`docker compose up` failed for {preset_id}:\n{up.stderr[-1500:]}\nlogs:\n{logs.stdout[-2000:]}"
            )
        yield Stack(project, compose_file, base_path, db_type, db_password)
    finally:
        if not keep_resources():
            _compose(project, compose_file, "down", "-v", "--remove-orphans", timeout=120, check=False)


@pytest.mark.parametrize("_stack", DB_PRESETS, ids=[p[0] for p in DB_PRESETS], indirect=True)
def test_database_sidecar_stack_boots(_stack: Stack) -> None:
    project, compose_file, expected_db = _stack.project, _stack.compose_file, _stack.db_type

    port = _compose(project, compose_file, "port", "spoolman", "8000").stdout.strip().splitlines()[0]
    base = f"http://{port}{_stack.base_path}"

    # depends_on: service_healthy gates the server on the DB healthcheck; then the
    # server runs its startup migrations against Postgres/MariaDB before serving.
    wait_for(
        lambda: http_get(f"{base}/api/v1/health", timeout=5)[0] == 200,
        timeout=180,
        what=f"the {expected_db} sidecar stack to serve",
    )

    status, body = http_get(f"{base}/api/v1/info", timeout=10)
    assert status == 200, f"/info returned {status}: {body[:300]}"
    # Soft signal (the published image reports this as the `DatabaseType.POSTGRES` enum
    # repr, not a bare "postgres"); the hard proof is the sidecar row check below.
    db_type = json.loads(body)["db_type"].lower()
    assert expected_db in db_type, f"unexpected db_type {db_type!r} for {expected_db}: {body[:300]}"

    # A round-trip through the API proves the server can actually read/write the DB.
    filament = json.loads(
        http_request(
            f"{base}/api/v1/filament",
            method="POST",
            json_body={"name": "sidecar PLA", "material": "PLA", "density": 1.24, "diameter": 1.75, "weight": 1000},
        )[1]
    )
    spool_status, spool_body = http_request(
        f"{base}/api/v1/spool", method="POST", json_body={"filament_id": filament["id"]}
    )
    assert spool_status == 200, f"spool create failed: {spool_status} {spool_body[:300]}"

    # ...and the row is really in the sidecar DB, not a silent SQLite fallback.
    assert _sidecar_spool_count(project, compose_file, expected_db, _stack.db_password) >= 1, (
        f"spool did not land in the {expected_db} sidecar database"
    )
