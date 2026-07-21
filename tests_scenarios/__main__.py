"""CLI for the local deployment-scenario harness."""

# ruff: noqa: T201 -- this is a human-facing CLI; printing IS the interface.

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from tests_scenarios.catalog import CORE

if TYPE_CHECKING:
    from typing import NoReturn

    from tests_scenarios.catalog import Scenario
    from tests_scenarios.runner import ScenarioStack

STATE = Path(__file__).resolve().parent / ".state" / "running.json"


def _registry() -> dict[str, dict[str, str | int]]:
    """Load the running-scenarios registry, or an empty dict if none exists yet."""
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _by_name(name: str) -> Scenario:
    """Look up a core scenario by name, or exit with a helpful error."""
    for s in CORE:
        if s.name == name:
            return s
    raise SystemExit(f"unknown scenario: {name} (see `poe scenario list`)")


def cmd_list(_args: argparse.Namespace) -> None:
    """Print every core scenario with its axis values and tags."""
    for s in CORE:
        tags = ",".join(s.tags)
        print(f"{s.name:34} db={s.db:11} auth={s.auth:6} proxy={s.proxy:8} arch={s.arch:6} [{tags}]")


def cmd_up(args: argparse.Namespace) -> None:
    """Bring a scenario up, wait for it to be healthy, and register it for ps/down/logs."""
    from tests_scenarios import runner  # noqa: PLC0415 -- keep `list`/`ps` free of docker imports

    # seeding is wired in by Task 14
    stack = runner.bring_up(_by_name(args.name))
    try:
        runner.wait_healthy(stack)
    except TimeoutError:
        runner.tear_down(stack)
        raise
    STATE.parent.mkdir(parents=True, exist_ok=True)
    reg = _registry()
    reg[stack.scenario.name] = {
        "project": stack.project,
        "port": stack.host_port,
        "url": stack.url,
        "compose_file": str(stack.compose_file),
    }
    STATE.write_text(json.dumps(reg, indent=2))
    _print_summary(stack)


def cmd_down(args: argparse.Namespace) -> None:
    """Tear down one running scenario, or every registered scenario with --all."""
    from tests_scenarios import runner  # noqa: PLC0415 -- keep `list`/`ps` free of docker imports
    from tests_scenarios.catalog import Db, Scenario  # noqa: PLC0415

    reg = _registry()
    names = list(reg) if args.all else [args.name]
    for name in names:
        info = reg.get(name)
        if not info:
            continue
        stack = runner.ScenarioStack(
            Scenario(name, Db.SQLITE), info["project"], info["port"], info["url"], Path(info["compose_file"]),
        )
        runner.tear_down(stack)
        reg.pop(name, None)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(reg, indent=2))


def cmd_test(args: argparse.Namespace) -> None:
    """Bring a scenario up, run the assertion suites against it, then tear down (unless --keep)."""
    from tests_scenarios import runner  # noqa: PLC0415 -- keep `list`/`ps` free of docker imports
    from tests_scenarios.assertions import contract, e2e, integration  # noqa: PLC0415

    stack: ScenarioStack | None = None
    try:
        stack = runner.bring_up(_by_name(args.name))
        runner.wait_healthy(stack)
        contract.run(stack)
        integration.run(stack)
        e2e.run(stack)
    finally:
        if stack is not None and not args.keep:
            runner.tear_down(stack)


def cmd_ps(_args: argparse.Namespace) -> None:
    """List every currently-registered running scenario."""
    for name, info in _registry().items():
        print(f"{name:34} {info['url']}  (project {info['project']})")


def cmd_logs(args: argparse.Namespace) -> None:
    """Stream docker-compose logs for one running scenario."""
    import subprocess  # noqa: PLC0415 -- keep `list`/`ps` free of docker imports

    from tests_scenarios import runner  # noqa: PLC0415

    info = _registry().get(args.name) or _raise(args.name)
    subprocess.run(
        [*runner.COMPOSE, "-p", info["project"], "-f", info["compose_file"], "logs", "-f"],
        check=False,
    )


def _raise(name: str) -> NoReturn:
    """Exit with a helpful error: `name` is not a currently-running scenario."""
    raise SystemExit(f"{name} is not running (see `poe scenario ps`)")


def _print_summary(stack: ScenarioStack) -> None:
    """Print a human-friendly summary of a freshly brought-up stack."""
    tenv = stack.scenario.test_env()
    print("\n" + "=" * 60)
    print(f"Scenario:  {stack.scenario.name}   [running]")
    print(f"URL:       {stack.url}/")
    if "SPOOLMAN_TEST_TOKEN" in tenv:
        print(f"API token: Bearer {tenv['SPOOLMAN_TEST_TOKEN']}")
    if "SPOOLMAN_TEST_LOGIN" in tenv:
        print(f"Login:     {tenv['SPOOLMAN_TEST_LOGIN']}  (POST /auth/login)")
    print(f"DB:        {stack.scenario.db} (project {stack.project})")
    print(f"Stop:      poe scenario down {stack.scenario.name}")
    print("=" * 60)


def build_parser() -> argparse.ArgumentParser:
    """Build the `scenario` CLI's argument parser: list/up/down/test/ps/logs."""
    p = argparse.ArgumentParser(prog="scenario")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    up = sub.add_parser("up")
    up.add_argument("name")
    up.set_defaults(func=cmd_up)

    dn = sub.add_parser("down")
    dn.add_argument("name", nargs="?")
    dn.add_argument("--all", action="store_true")
    dn.set_defaults(func=cmd_down)

    ts = sub.add_parser("test")
    ts.add_argument("name")
    ts.add_argument("--keep", action="store_true")
    ts.set_defaults(func=cmd_test)

    sub.add_parser("ps").set_defaults(func=cmd_ps)

    lg = sub.add_parser("logs")
    lg.add_argument("name")
    lg.set_defaults(func=cmd_logs)

    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args and dispatch to the matching cmd_* function."""
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
