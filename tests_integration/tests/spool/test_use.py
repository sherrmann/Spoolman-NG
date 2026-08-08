"""Integration tests for the Spool API endpoint."""

import asyncio
import math
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from ..conftest import URL


@pytest.mark.parametrize("use_weight", [0, 0.05, -0.05, 1500])  # 1500 is big enough to use all filament
def test_use_spool_weight(random_filament: dict[str, Any], use_weight: float):
    """Test using a spool in the database."""
    # Setup
    filament_net_weight = random_filament["weight"]
    start_weight = 1000
    result = httpx.post(
        f"{URL}/api/v1/spool",
        json={
            "filament_id": random_filament["id"],
            "remaining_weight": start_weight,
        },
    )
    result.raise_for_status()
    spool = result.json()

    # Execute
    result = httpx.put(
        f"{URL}/api/v1/spool/{spool['id']}/use",
        json={
            "use_weight": use_weight,
        },
    )
    result.raise_for_status()

    # Verify
    spool = result.json()
    # remaining_weight should be clamped so it's never negative, but used_weight should not be clamped to the net weight
    assert spool["used_weight"] == pytest.approx(max(use_weight, 0))
    assert spool["remaining_weight"] == pytest.approx(min(max(start_weight - use_weight, 0), filament_net_weight))

    # Verify that first_used has been updated
    diff = abs((datetime.now(tz=timezone.utc) - datetime.fromisoformat(spool["first_used"])).total_seconds())
    assert diff < 60

    # Verify that last_used has been updated
    diff = abs((datetime.now(tz=timezone.utc) - datetime.fromisoformat(spool["last_used"])).total_seconds())
    assert diff < 60

    # Clean up
    httpx.delete(f"{URL}/api/v1/spool/{spool['id']}").raise_for_status()


@pytest.mark.parametrize("use_length", [0, 10, -10, 500e3])  # 500e3 is big enough to use all the filament
def test_use_spool_length(random_filament: dict[str, Any], use_length: float):
    """Test using a spool in the database."""
    # Setup
    filament_net_weight = random_filament["weight"]
    start_weight = 1000
    result = httpx.post(
        f"{URL}/api/v1/spool",
        json={
            "filament_id": random_filament["id"],
            "remaining_weight": start_weight,
            "first_used": "2023-01-01T00:00:00Z",
        },
    )
    result.raise_for_status()
    spool = result.json()

    # Execute
    result = httpx.put(
        f"{URL}/api/v1/spool/{spool['id']}/use",
        json={
            "use_length": use_length,
        },
    )
    result.raise_for_status()

    # Verify
    spool = result.json()
    use_weight = (
        random_filament["density"] * (use_length * 1e-1) * math.pi * ((random_filament["diameter"] * 1e-1 / 2) ** 2)
    )
    # remaining_weight should be clamped so it's never negative, but used_weight should not be clamped to the net weight
    assert spool["used_weight"] == pytest.approx(max(use_weight, 0))
    assert spool["remaining_weight"] == pytest.approx(min(max(start_weight - use_weight, 0), filament_net_weight))

    # Verify that first_used hasn't been updated since it was already set
    assert spool["first_used"] == "2023-01-01T00:00:00Z"

    # Verify that last_used has been updated
    diff = abs((datetime.now(tz=timezone.utc) - datetime.fromisoformat(spool["last_used"])).total_seconds())
    assert diff < 60

    # Clean up
    httpx.delete(f"{URL}/api/v1/spool/{spool['id']}").raise_for_status()


def test_use_spool_weight_and_length(random_filament: dict[str, Any]):
    """Test using a spool in the database."""
    # Setup
    result = httpx.post(
        f"{URL}/api/v1/spool",
        json={"filament_id": random_filament["id"]},
    )
    result.raise_for_status()
    spool = result.json()

    # Execute
    result = httpx.put(
        f"{URL}/api/v1/spool/{spool['id']}/use",
        json={
            "use_weight": 0.05,
            "use_length": 10,
        },
    )
    assert result.status_code == 400  # Cannot use both weight and length

    # Clean up
    httpx.delete(f"{URL}/api/v1/spool/{spool['id']}").raise_for_status()


def test_use_spool_not_found():
    """Test using a spool that does not exist."""
    # Execute
    result = httpx.put(
        f"{URL}/api/v1/spool/123456789/use",
        json={"use_weight": 0.05},
    )
    assert result.status_code == 404
    message = result.json()["message"].lower()
    assert "spool" in message
    assert "id" in message
    assert "123456789" in message


def test_use_spool_weight_repeated_small_increments(random_filament: dict[str, Any]):
    """Repeated small `use` calls must not accumulate float64 noise, nor lose real sub-gram usage.

    #377: used_weight is accumulated server-side as `used_weight = used_weight + weight` on every
    call. Doing that in float64 many times accumulates representation noise -- 100 additions of
    0.03 land on 2.999999999999995 in plain Python, not 3.0 -- which used to reach the client as a
    long noisy literal, and a (since-fixed) client-side bug turned that into string concatenation
    instead of addition, crashing the home page. The server-side fix rounds the accumulator to 6
    decimal places (1 microgram) on every write, which is far below any real increment: a slicer
    legitimately reporting ~0.03 g per layer must keep accumulating normally, not get rounded away.

    The noise from repeated float64 addition alone is around 1e-15 here -- far smaller than any
    tolerance that would still be a meaningful "no drift" check -- so this compares for exact
    equality rather than pytest.approx with a workable-looking tolerance; a loose tolerance would
    pass on both the rounded and the unrounded accumulator and catch nothing.
    """
    # Setup
    start_weight = 1000
    result = httpx.post(
        f"{URL}/api/v1/spool",
        json={
            "filament_id": random_filament["id"],
            "remaining_weight": start_weight,
        },
    )
    result.raise_for_status()
    spool = result.json()

    # Execute: 100 calls of 0.03g -- individually far too small to lose to a 0.1g-scale rounding
    # rule, but exactly the kind of repeated small increment that accumulates float noise.
    per_use = 0.03
    uses = 100
    for _ in range(uses):
        result = httpx.put(
            f"{URL}/api/v1/spool/{spool['id']}/use",
            json={"use_weight": per_use},
        )
        result.raise_for_status()

    # Verify: the accumulated total is exactly correct (no float64 drift) ...
    spool = result.json()
    expected_used = round(per_use * uses, 6)
    assert spool["used_weight"] == expected_used
    # ... and, crucially, the 100 individual 0.03g increments were not lost to rounding: 100 * 0.03
    # is meaningfully more than a single increment, so a bug that rounded each accumulation down to
    # the nearest 0.1g (or coarser) would fail this by a wide margin, not just a float epsilon.
    assert spool["used_weight"] > per_use * (uses - 1)

    # Clean up
    httpx.delete(f"{URL}/api/v1/spool/{spool['id']}").raise_for_status()


@pytest.mark.asyncio
async def test_use_spool_concurrent(random_filament: dict[str, Any]):
    """Test using a spool with many concurrent requests."""
    # Setup
    start_weight = 1000
    result = httpx.post(
        f"{URL}/api/v1/spool",
        json={
            "filament_id": random_filament["id"],
            "remaining_weight": start_weight,
        },
    )
    result.raise_for_status()
    spool = result.json()

    # Execute
    requests = 100
    used_weight = 0.5
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *(
                client.put(
                    f"{URL}/api/v1/spool/{spool['id']}/use",
                    json={
                        "use_weight": used_weight,
                    },
                    timeout=60,
                )
                for _ in range(requests)
            ),
        )

    # Verify
    result = httpx.get(f"{URL}/api/v1/spool/{spool['id']}")
    result.raise_for_status()
    spool = result.json()
    assert spool["remaining_weight"] == pytest.approx(start_weight - (used_weight * requests))

    # Clean up
    httpx.delete(f"{URL}/api/v1/spool/{spool['id']}").raise_for_status()
