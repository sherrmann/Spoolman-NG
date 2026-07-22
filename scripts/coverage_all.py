"""Combined backend coverage: fast suite + tests_integration against an instrumented server.

The per-PR CI unit job only measures what ``pytest tests/`` executes (~63%); the Docker
matrix and the e2e journeys exercise the API/DB layer uninstrumented. This script produces
the real combined number locally:

1. ``pytest tests/`` with pytest-cov  -> .coverage.unit
2. a coverage-instrumented ``uvicorn spoolman.main:app`` on temp SQLite, with the full
   ``tests_integration/tests`` suite pointed at it via the SPOOLMAN_TEST_URL seam
   -> .coverage.server
3. ``coverage combine`` + report, failing under the ratchet.

Run with ``poe coverage-all``.
"""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
# Ratchet: combined coverage may not drop below this. Raise it as coverage grows;
# never lower it to make a run pass. Observed 70% on 2026-07-22.
FAIL_UNDER = 68

UNIT_DATA = REPO / ".coverage.unit"
SERVER_DATA = REPO / ".coverage.server"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_unit_suite() -> None:
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--cov=spoolman", "--cov-branch", "--cov-report="],
        check=True,
        cwd=REPO,
        env={**os.environ, "COVERAGE_FILE": str(UNIT_DATA)},
    )


def _wait_healthy(url: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{url}/api/v1/health", timeout=2)
            if r.is_success:
                return
            last = f"{r.status_code}"
        except httpx.HTTPError as e:
            last = str(e)
        time.sleep(0.5)
    raise TimeoutError(f"instrumented server not healthy in {timeout}s: {last}")


def _run_integration_against_instrumented_server() -> None:
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="spoolman-cov-") as data_dir:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--branch",
                "--source=spoolman",
                "-m",
                "uvicorn",
                "spoolman.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=REPO,
            env={
                **os.environ,
                "COVERAGE_FILE": str(SERVER_DATA),
                "SPOOLMAN_DB_TYPE": "sqlite",
                "SPOOLMAN_DIR_DATA": data_dir,
                "SPOOLMAN_LOGGING_LEVEL": "WARNING",
            },
        )
        try:
            _wait_healthy(url)
            subprocess.run(
                [sys.executable, "-m", "pytest", "tests_integration/tests", "-q"],
                check=True,
                cwd=REPO,
                env={**os.environ, "SPOOLMAN_TEST_URL": url, "DB_TYPE": "sqlite"},
            )
        finally:
            server.send_signal(signal.SIGTERM)
            server.wait(timeout=30)


def _combine_and_report() -> int:
    subprocess.run(
        [sys.executable, "-m", "coverage", "combine", str(UNIT_DATA), str(SERVER_DATA)],
        check=True,
        cwd=REPO,
    )
    result = subprocess.run(
        [sys.executable, "-m", "coverage", "report", f"--fail-under={FAIL_UNDER}"],
        check=False,
        cwd=REPO,
    )
    return result.returncode


def main() -> int:
    """Run both suites, combine their coverage, and report against the ratchet."""
    for stale in (UNIT_DATA, SERVER_DATA, REPO / ".coverage"):
        stale.unlink(missing_ok=True)
    _run_unit_suite()
    _run_integration_against_instrumented_server()
    return _combine_and_report()


if __name__ == "__main__":
    sys.exit(main())
