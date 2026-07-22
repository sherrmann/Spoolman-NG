"""Query-count guards: list endpoints must not do per-row (N+1) queries.

The absolute caps are generous canaries; the load-invariant assertions (same
query count for 3 rows as for 25) are the real N+1 guard and survive refactors.
"""

from httpx import AsyncClient

from tests.integration.conftest import QueryCounter

# Observed today: spool list = 2, filament list = 4 (flat in row count). Budgets carry
# headroom for legitimate additions; the equality assertions below are the hard guard.
SPOOL_LIST_BUDGET = 6
FILAMENT_LIST_BUDGET = 8


async def _seed_spools(client: AsyncClient, n: int) -> None:
    vendor = (await client.post("/api/v1/vendor", json={"name": f"qb-vendor-{n}"})).json()
    filament = (
        await client.post(
            "/api/v1/filament",
            json={
                "name": f"qb-fil-{n}",
                "material": "PLA",
                "density": 1.24,
                "diameter": 1.75,
                "vendor_id": vendor["id"],
            },
        )
    ).json()
    for _ in range(n):
        r = await client.post("/api/v1/spool", json={"filament_id": filament["id"]})
        assert r.status_code == 200


async def _count_list_queries(client: AsyncClient, query_counter: QueryCounter, path: str) -> int:
    query_counter.reset()
    r = await client.get(path)
    assert r.status_code == 200
    return query_counter.count


async def test_spool_list_query_count_does_not_grow_with_rows(client: AsyncClient, query_counter: QueryCounter):
    await _seed_spools(client, 3)
    small = await _count_list_queries(client, query_counter, "/api/v1/spool?limit=100")
    await _seed_spools(client, 22)
    large = await _count_list_queries(client, query_counter, "/api/v1/spool?limit=100")
    assert large == small, f"query count grew with row count ({small} -> {large}): N+1 regression"
    assert large <= SPOOL_LIST_BUDGET, f"spool list ran {large} queries (budget {SPOOL_LIST_BUDGET})"


async def test_filament_list_query_count_does_not_grow_with_rows(client: AsyncClient, query_counter: QueryCounter):
    await _seed_spools(client, 3)
    small = await _count_list_queries(client, query_counter, "/api/v1/filament?limit=100")
    await _seed_spools(client, 22)
    large = await _count_list_queries(client, query_counter, "/api/v1/filament?limit=100")
    assert large == small, f"query count grew with row count ({small} -> {large}): N+1 regression"
    assert large <= FILAMENT_LIST_BUDGET, f"filament list ran {large} queries (budget {FILAMENT_LIST_BUDGET})"
