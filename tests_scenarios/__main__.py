"""CLI for the local deployment-scenario harness."""

# ruff: noqa: T201 -- this is a human-facing CLI; printing IS the interface.

from __future__ import annotations

import argparse
import json
import os
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
    from tests_scenarios.seed import seed_sample  # noqa: PLC0415

    stack = runner.bring_up(_by_name(args.name))
    seed_counts: dict[str, int] | None = None
    try:
        runner.wait_healthy(stack)
        runner.provision_users(stack)
        if stack.scenario.seed:
            seed_counts = seed_sample(stack)
    except Exception:
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
    _print_summary(stack, seed_counts)


def cmd_down(args: argparse.Namespace) -> None:
    """Tear down one running scenario, or every registered scenario with --all."""
    from tests_scenarios import runner  # noqa: PLC0415 -- keep `list`/`ps` free of docker imports
    from tests_scenarios.catalog import Db, Scenario  # noqa: PLC0415

    if not args.all and not args.name:
        raise SystemExit("specify a scenario name or --all (see `poe scenario ps`)")
    reg = _registry()
    names = list(reg) if args.all else [args.name]
    for name in names:
        info = reg.get(name)
        if not info:
            continue
        stack = runner.ScenarioStack(
            Scenario(name, Db.SQLITE),
            info["project"],
            info["port"],
            info["url"],
            Path(info["compose_file"]),
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
        runner.provision_users(stack)
        contract.run(stack)
        integration.run(stack)
        e2e.run(stack)
    finally:
        if stack is not None and not args.keep:
            runner.tear_down(stack)


def _parse_enum_list(value: str | None, enum_cls: type) -> list | None:
    """Parse a comma-separated `--flag` value into enum members, or None if the flag was omitted."""
    if not value:
        return None
    try:
        return [enum_cls(v.strip()) for v in value.split(",")]
    except ValueError as e:
        raise SystemExit(f"invalid filter value: {e}") from e


def _select_scenarios(args: argparse.Namespace) -> list[Scenario]:
    """Filter CORE down to scenarios matching every given `--tags/--db/--auth/--proxy/--arch` flag.

    An axis with no flag keeps every scenario on that axis; `--tags` keeps scenarios that have
    *any* of the listed tags. No filters at all means the full CORE set.
    """
    from tests_scenarios.catalog import Arch, Auth, Db, Proxy  # noqa: PLC0415

    scenarios = list(CORE)
    if args.tags:
        wanted_tags = set(args.tags.split(","))
        scenarios = [s for s in scenarios if wanted_tags & set(s.tags)]
    for flag_value, enum_cls, attr in (
        (args.db, Db, "db"),
        (args.auth, Auth, "auth"),
        (args.proxy, Proxy, "proxy"),
        (args.arch, Arch, "arch"),
    ):
        wanted = _parse_enum_list(flag_value, enum_cls)
        if wanted is not None:
            scenarios = [s for s in scenarios if getattr(s, attr) in wanted]
    return scenarios


def _run_scenario(scenario: Scenario, *, quick: bool) -> tuple[bool, str]:
    """Bring `scenario` up, assert against it, and always tear it down; never raises.

    Owns the stack's full lifecycle itself (bring_up -> wait_healthy -> provision_users ->
    assertions -> tear_down) rather than touching the `.state` registry -- that registry is
    for manually-managed `up`/`down`, not this fire-and-forget parallel sweep.
    """
    from tests_scenarios import runner  # noqa: PLC0415 -- keep `list`/`ps` free of docker imports
    from tests_scenarios.assertions import contract, e2e, integration  # noqa: PLC0415

    stack: ScenarioStack | None = None
    try:
        stack = runner.bring_up(scenario)
        runner.wait_healthy(stack)
        runner.provision_users(stack)
        contract.run(stack)
        if not quick:
            integration.run(stack)
            e2e.run(stack)
    except Exception as e:  # noqa: BLE001 -- turned into a per-scenario Result, never propagates
        return False, repr(e)
    else:
        return True, "passed"
    finally:
        if stack is not None:
            runner.tear_down(stack)


def _print_results_table(results: list, budget: int) -> bool:
    """Print a pass/fail table for a `test-all` run; return True if any scenario failed."""
    print("\n" + "=" * 60)
    print(f"{'SCENARIO':40} RESULT")
    print("-" * 60)
    failed = 0
    for r in results:
        if r.ok:
            print(f"{r.scenario.name:40} ok")
        else:
            failed += 1
            print(f"{r.scenario.name:40} FAIL  {r.detail}")
    print("=" * 60)
    print(f"{len(results) - failed}/{len(results)} passed (budget={budget})")
    return failed > 0


def cmd_test_all(args: argparse.Namespace) -> None:
    """Run every scenario matching the filters in parallel; print a pass/fail table and exit non-zero on failure."""
    import asyncio  # noqa: PLC0415 -- keep `list`/`ps` free of docker/async imports

    from tests_scenarios.scheduler import run_many  # noqa: PLC0415

    scenarios = _select_scenarios(args)
    if not scenarios:
        raise SystemExit("no scenarios matched the given filters")

    budget = args.jobs if args.jobs else (os.cpu_count() or 1)

    async def run_one(scenario: Scenario) -> tuple[bool, str]:
        # Offload the blocking docker/httpx/subprocess calls to a thread so scenarios genuinely
        # overlap on the event loop instead of serializing behind a single-threaded coroutine.
        return await asyncio.to_thread(_run_scenario, scenario, quick=args.quick)

    results = asyncio.run(run_many(scenarios, concurrency_budget=budget, run_one=run_one))
    if _print_results_table(results, budget):
        raise SystemExit(1)


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


def _print_summary(stack: ScenarioStack, seed_counts: dict[str, int] | None = None) -> None:
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
    if seed_counts is not None:
        counts = ", ".join(f"{n} {k}" for k, n in seed_counts.items())
        print(f"Seeded:    {counts}")
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

    ta = sub.add_parser("test-all")
    ta.add_argument("--tags", help="comma-separated tags; keep scenarios with any of them")
    ta.add_argument("--db", help="comma-separated db values (sqlite,postgres,mariadb,cockroachdb)")
    ta.add_argument("--auth", help="comma-separated auth values (none,token,users)")
    ta.add_argument("--proxy", help="comma-separated proxy values (none,nginx,traefik,caddy)")
    ta.add_argument("--arch", help="comma-separated arch values (amd64,arm64,armv7)")
    ta.add_argument("-j", "--jobs", type=int, help="concurrency budget (default: os.cpu_count())")
    mode = ta.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="contract + integration + e2e (default)")
    mode.add_argument("--quick", action="store_true", help="contract only")
    ta.set_defaults(func=cmd_test_all)

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
