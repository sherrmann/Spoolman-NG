"""Seeded performance harness (#300). Run on demand, never in normal CI.

Seeds a large, realistic dataset straight through the ORM, then times the hot read paths
(spool listing variants, grouping, exports, websocket fan-out) and prints a Markdown table.
No timing is asserted -- machines differ -- only that responses succeed and counts match the seed.

    SPOOLMAN_PERF=1 uv run pytest tests/integration/test_perf_harness.py -q -s

Environment:
    SPOOLMAN_PERF=1            enable the harness (otherwise every test is skipped)
    SPOOLMAN_PERF_SPOOLS=N     number of spools to seed (default 10000)
    SPOOLMAN_PERF_REPORT=path  also write the Markdown table to this file
"""

import json
import os
import random
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from starlette.websockets import WebSocketState

from spoolman import extra_field_registry
from spoolman.database import database as db_module
from spoolman.database import models
from spoolman.database import spool as db_spool
from spoolman.extra_field_registry import EntityType, ExtraField, ExtraFieldType, add_or_update_extra_field
from spoolman.ws import websocket_manager
from tests.integration.conftest import QueryCounter

pytestmark = [
    pytest.mark.perf,
    pytest.mark.skipif(os.environ.get("SPOOLMAN_PERF") != "1", reason="performance harness: set SPOOLMAN_PERF=1"),
]

SEED = 300
N_VENDORS = 50
N_FILAMENTS = 500
N_SPOOLS = int(os.environ.get("SPOOLMAN_PERF_SPOOLS", "10000"))
REPEATS = 5
PAGE = 50

MATERIALS = ["PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC", "PLA+"]
MATERIAL_WEIGHTS = [40, 25, 10, 5, 5, 5, 3, 7]
LOCATIONS = [f"{area}-{n}" for area in ("Shelf", "Dry box", "AMS", "Cabinet") for n in range(1, 11)]
EXTRA_KEYS = ("perf_note", "perf_rank", "perf_grade")
GRADES = ["a", "b", "c"]


@dataclass
class Row:
    """One measured scenario."""

    name: str
    median_ms: float
    queries: int
    size: int
    note: str = ""


def _field_defs(entity: EntityType) -> list[ExtraField]:
    return [
        ExtraField(key="perf_note", name="Note", field_type=ExtraFieldType.text, entity_type=entity),
        ExtraField(key="perf_rank", name="Rank", field_type=ExtraFieldType.integer, entity_type=entity),
        ExtraField(
            key="perf_grade",
            name="Grade",
            field_type=ExtraFieldType.choice,
            choices=GRADES,
            multi_choice=False,
            entity_type=entity,
        ),
    ]


def _extra_values(rng: random.Random, i: int) -> dict[str, str]:
    """Extra-field values as the app stores them: JSON-encoded strings."""
    return {
        "perf_note": json.dumps(f"note {i} {rng.choice(['alpha', 'beta', 'gamma'])}"),
        "perf_rank": json.dumps(rng.randint(0, 1000)),
        "perf_grade": json.dumps(rng.choice(GRADES)),
    }


async def _seed() -> dict[str, int]:
    """Bulk-insert the dataset and register the extra-field definitions."""
    rng = random.Random(SEED)  # noqa: S311 -- deterministic seed, not security
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    async with db_module.get_session_maker()() as db:
        for entity in (EntityType.vendor, EntityType.filament, EntityType.spool):
            for field in _field_defs(entity):
                await add_or_update_extra_field(db, entity, field)
        await db.commit()

        vendors = [
            models.Vendor(
                registered=now,
                name=f"Vendor {i:03d}",
                extra=[models.VendorField(key=k, value=v) for k, v in _extra_values(rng, i).items()],
            )
            for i in range(N_VENDORS)
        ]
        db.add_all(vendors)
        await db.flush()

        filaments = [
            models.Filament(
                registered=now,
                name=f"Colour {i:03d}",
                vendor_id=rng.choice(vendors).id,
                material=rng.choices(MATERIALS, MATERIAL_WEIGHTS)[0],
                price=round(rng.uniform(12, 40), 2),
                density=1.24,
                diameter=1.75,
                weight=1000,
                spool_weight=rng.choice([140, 180, 220]),
                color_hex=f"{rng.randrange(0x1000000):06X}",
                extra=[models.FilamentField(key=k, value=v) for k, v in _extra_values(rng, i).items()],
            )
            for i in range(N_FILAMENTS)
        ]
        db.add_all(filaments)
        await db.flush()

        for i in range(N_SPOOLS):
            archived = rng.random() < 0.15
            used = 1000.0 if archived else round(rng.choice([0.0, rng.uniform(0, 1000), rng.uniform(0, 300)]), 1)
            db.add(
                models.Spool(
                    registered=now - timedelta(days=rng.randint(0, 700)),
                    filament_id=rng.choice(filaments).id,
                    initial_weight=1000,
                    spool_weight=rng.choice([140, 180, 220]),
                    used_weight=used,
                    location=None if rng.random() < 0.1 else rng.choice(LOCATIONS),
                    lot_nr=f"LOT{rng.randint(1, 400):04d}" if rng.random() < 0.6 else None,
                    comment=rng.choice([None, "opened", "sealed", "dry before use"]),
                    archived=archived or None,
                    extra=[models.SpoolField(key=k, value=v) for k, v in _extra_values(rng, i).items()],
                ),
            )
            if i % 2000 == 1999:
                await db.flush()
        await db.commit()
    return {"vendors": N_VENDORS, "filaments": N_FILAMENTS, "spools": N_SPOOLS}


async def _measure(
    name: str,
    op: Callable[[], Awaitable[tuple[int, int]]],
    counter: QueryCounter,
    note: str = "",
) -> Row:
    """Run `op` once to warm up and REPEATS times for timing. `op` returns (size_in_bytes, item_count)."""
    await op()
    times: list[float] = []
    queries = 0
    size = 0
    for _ in range(REPEATS):
        counter.reset()
        start = time.perf_counter()
        size, _ = await op()
        times.append((time.perf_counter() - start) * 1000)
        queries = counter.count
    return Row(name, statistics.median(times), queries, size, note)


class _FakeSocket:
    """Minimal stand-in for a WebSocket: connected, records what it is sent."""

    client = None
    client_state = WebSocketState.CONNECTED
    application_state = WebSocketState.CONNECTED

    def __init__(self) -> None:
        self.received: list[str] = []

    async def send_text(self, data: str) -> None:
        self.received.append(data)


def _make_fan_out(
    sockets: list[_FakeSocket],
    filament_id: int,
    spool_count: int,
) -> Callable[[], Awaitable[tuple[int, int]]]:
    """Build the op that re-broadcasts a filament's spools to `sockets` and checks delivery."""

    async def fan_out() -> tuple[int, int]:
        for sock in sockets:
            sock.received.clear()
        async with db_module.get_session_maker()() as db:
            await db_spool.notify_spools_of_filament_change(db, filament_id)
        assert all(len(s.received) == spool_count for s in sockets)
        return sum(len(m) for s in sockets for m in s.received), sum(len(s.received) for s in sockets)

    return fan_out


def _render(rows: list[Row], counts: dict[str, int]) -> str:
    lines = [
        f"Seeded {counts['vendors']} vendors, {counts['filaments']} filaments, {counts['spools']} spools "
        f"(3 extra fields each, seed {SEED}); median of {REPEATS} runs after 1 warm-up.",
        "",
        "| Scenario | Median ms | Queries | Response bytes | Note |",
        "|---|---:|---:|---:|---|",
    ]
    lines.extend(f"| {r.name} | {r.median_ms:.1f} | {r.queries} | {r.size} | {r.note} |" for r in rows)
    return "\n".join(lines) + "\n"


async def test_perf_harness(  # noqa: C901
    client: AsyncClient,
    query_counter: QueryCounter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    counts = await _seed()
    rows: list[Row] = []

    def get(path: str, expect_items: Callable[[list], bool] | None = None) -> Callable[[], Awaitable[tuple[int, int]]]:
        async def op() -> tuple[int, int]:
            r = await client.get(path)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
            body = r.json() if "json" in r.headers.get("content-type", "") else None
            items = body if isinstance(body, list) else []
            if expect_items is not None:
                assert expect_items(items), f"{path}: unexpected item count {len(items)}"
            return len(r.content), len(items)

        return op

    async def total_for(path: str) -> int:
        r = await client.get(path)
        assert r.status_code == 200
        return int(r.headers["x-total-count"])

    # Counts as seeded: the unfiltered listing excludes archived spools, the export includes them.
    active_total = await total_for("/api/v1/spool?limit=1")
    all_total = await total_for("/api/v1/spool?limit=1&allow_archived=true")
    assert all_total == counts["spools"]
    assert 0 < active_total < all_total

    page_ok = lambda items: 0 < len(items) <= PAGE  # noqa: E731
    listing = [
        ("spool list, no filter", f"/api/v1/spool?limit={PAGE}"),
        ("spool list, filament.material=PLA", f"/api/v1/spool?limit={PAGE}&filament.material=PLA"),
        ("spool list, location=Shelf-1", f"/api/v1/spool?limit={PAGE}&location=Shelf-1"),
        ("spool list, sort remaining_weight:desc", f"/api/v1/spool?limit={PAGE}&sort=remaining_weight:desc"),
        ("spool list, sort filament.vendor.name:asc", f"/api/v1/spool?limit={PAGE}&sort=filament.vendor.name:asc"),
        ("spool list, search=PLA", f"/api/v1/spool?limit={PAGE}&search=PLA"),
        ("spool list, search=Vendor 007,opened", f"/api/v1/spool?limit={PAGE}&search=Vendor%20007,opened"),
        (
            "spool list, sort extra.perf_rank:desc",
            f"/api/v1/spool?limit={PAGE}&sort=extra.perf_rank:desc",
        ),
    ]
    for name, path in listing:
        rows.append(await _measure(name, get(path, page_ok if "search" not in name else None), query_counter))

    rows.append(
        await _measure(
            "spool group, group_by=filament",
            get("/api/v1/spool/group?group_by=filament", lambda items: len(items) > 0),
            query_counter,
        ),
    )
    rows.append(
        await _measure(
            "spool group, group_by=filament&limit=50",
            get("/api/v1/spool/group?group_by=filament&limit=50", lambda items: len(items) == PAGE),
            query_counter,
        ),
    )

    export_json_op = get("/api/v1/export/spools?fmt=json", lambda items: len(items) == counts["spools"])
    rows.append(await _measure("export spools, fmt=json", export_json_op, query_counter))

    async def export_csv() -> tuple[int, int]:
        r = await client.get("/api/v1/export/spools?fmt=csv")
        assert r.status_code == 200
        data_lines = r.text.strip().splitlines()[1:]
        assert len(data_lines) >= counts["spools"]  # quoted newlines in comments could only add lines
        return len(r.content), len(data_lines)

    rows.append(await _measure("export spools, fmt=csv", export_csv, query_counter))

    # WebSocket fan-out: the ASGI transport cannot open sockets, so drive the broadcast path directly.
    # Pick the filament with the most spools so the event count is the worst case for this dataset.
    session_maker = db_module.get_session_maker()
    async with session_maker() as db:
        from sqlalchemy import func, select  # noqa: PLC0415

        result = await db.execute(
            select(models.Spool.filament_id, func.count())
            .group_by(models.Spool.filament_id)
            .order_by(func.count().desc())
            .limit(1),
        )
        filament_id, spool_count = result.one()

    for n_subscribers in (1, 10, 50):
        sockets = [_FakeSocket() for _ in range(n_subscribers)]
        for sock in sockets:
            websocket_manager.connect(("spool",), sock)  # type: ignore[arg-type]
        try:
            fan_out = _make_fan_out(sockets, filament_id, spool_count)

            rows.append(
                await _measure(
                    f"ws fan-out, filament edit, {n_subscribers} subscriber(s)",
                    fan_out,
                    query_counter,
                    note=f"{spool_count} spool events each",
                ),
            )
        finally:
            for sock in sockets:
                websocket_manager.disconnect(("spool",), sock)  # type: ignore[arg-type]

    report = _render(rows, counts)
    with capsys.disabled():
        print("\n" + report)  # noqa: T201
    report_path = os.environ.get("SPOOLMAN_PERF_REPORT")
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")

    extra_field_registry.extra_field_cache.clear()
