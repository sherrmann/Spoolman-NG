"""Integration tests for the DELETE /filament/{id} cascade gate.

filament_db.delete cascades to a filament's spools (and their usage history) unconditionally --
that behaviour lives in the database layer so the chat tool (which already showed a confirm-card
and got the user's agreement) can call it directly. The REST endpoint has no such prior
confirmation, so it must never destroy spools silently: with spools present and no explicit
`cascade=true`, it refuses with 409 and states the blast radius; the order-line refusal is a hard
refusal that `cascade` can never override.

"Gone" is asserted via the database layer rather than a follow-up GET: the ad-hoc FastAPI app this
in-process harness builds (tests/integration/conftest.py) does not register the app's
ItemNotFoundError -> 404 exception handler (spoolman/api/v1/router.py), so a GET for a missing
resource 500s here rather than 404ing -- a pre-existing harness gap, unrelated to this endpoint.
"""

import pytest
import sqlalchemy
from httpx import AsyncClient

from spoolman.api.v1 import filament as filament_api
from spoolman.database import database as db_module
from spoolman.database import filament as filament_db
from spoolman.database import models
from spoolman.database import spool as spool_db
from spoolman.exceptions import ItemNotFoundError

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
ORDER = "/api/v1/order"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, **fields}
    resp = await client.post(FIL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _add_spool(client: AsyncClient, filament_id: int, **fields: object) -> dict:
    resp = await client.post(SPOOL, json={"filament_id": filament_id, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _assert_filament_gone(filament_id: int) -> None:
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        with pytest.raises(ItemNotFoundError):
            await filament_db.get_by_id(session, filament_id)


async def _assert_spool_gone(spool_id: int) -> None:
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        with pytest.raises(ItemNotFoundError):
            await spool_db.get_by_id(session, spool_id)


async def test_delete_with_spools_and_no_cascade_refuses_and_leaves_everything_intact(
    client: AsyncClient,
) -> None:
    fil = await _add_filament(client, name="Doomed")
    spool_a = await _add_spool(client, fil["id"])
    spool_b = await _add_spool(client, fil["id"])

    resp = await client.delete(f"{FIL}/{fil['id']}")

    assert resp.status_code == 409, resp.text
    message = resp.json()["message"]
    assert "2 spool" in message
    assert "usage history" in message
    assert "cascade" in message
    # The refusal must not have destroyed anything -- a refusal that already deleted something is
    # the worst outcome, worse than the silent cascade it exists to prevent.
    assert (await client.get(f"{FIL}/{fil['id']}")).status_code == 200
    assert (await client.get(f"{SPOOL}/{spool_a['id']}")).status_code == 200
    assert (await client.get(f"{SPOOL}/{spool_b['id']}")).status_code == 200


async def test_delete_with_cascade_true_succeeds_and_removes_filament_and_spools(
    client: AsyncClient,
) -> None:
    fil = await _add_filament(client, name="Doomed")
    spool_a = await _add_spool(client, fil["id"])
    spool_b = await _add_spool(client, fil["id"])

    resp = await client.delete(f"{FIL}/{fil['id']}", params={"cascade": "true"})

    assert resp.status_code == 200, resp.text
    await _assert_filament_gone(fil["id"])
    await _assert_spool_gone(spool_a["id"])
    await _assert_spool_gone(spool_b["id"])


async def test_delete_with_no_spools_succeeds_without_cascade_param(client: AsyncClient) -> None:
    # Backward compatibility: a filament with no spools must delete exactly as it always has, with
    # no new required parameter and no behaviour change for existing callers.
    fil = await _add_filament(client, name="Never had spools")

    resp = await client.delete(f"{FIL}/{fil['id']}")

    assert resp.status_code == 200, resp.text
    await _assert_filament_gone(fil["id"])


async def test_order_line_reference_refuses_even_with_cascade_true(client: AsyncClient) -> None:
    fil = await _add_filament(client, name="On order")
    order_resp = await client.post(ORDER, json={"lines": [{"filament_id": fil["id"], "quantity": 1}]})
    assert order_resp.status_code == 200, order_resp.text

    resp = await client.delete(f"{FIL}/{fil['id']}", params={"cascade": "true"})

    assert resp.status_code == 409, resp.text
    assert "order line" in resp.json()["message"]
    assert (await client.get(f"{FIL}/{fil['id']}")).status_code == 200


async def test_order_line_refusal_is_the_endpoints_own_check_not_only_the_db_layers(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # filament_db.delete independently re-checks order-line references too (defense in depth), which
    # would mask a regression in the endpoint's own gate: the test above still 409s even if the
    # endpoint's check is deleted entirely, because the database layer's check catches it instead.
    # Stub delete to a no-op success so this test isolates the endpoint's own order-line check.
    async def _fake_delete(*_args: object, **_kwargs: object) -> None:
        pass

    monkeypatch.setattr(filament_api.filament, "delete", _fake_delete)

    fil = await _add_filament(client, name="On order")
    order_resp = await client.post(ORDER, json={"lines": [{"filament_id": fil["id"], "quantity": 1}]})
    assert order_resp.status_code == 200, order_resp.text

    resp = await client.delete(f"{FIL}/{fil['id']}", params={"cascade": "true"})

    assert resp.status_code == 409, resp.text
    assert "order line" in resp.json()["message"]


# --- The usage-event cascade must not bind one SQL parameter per spool -------------


async def test_usage_event_cascade_uses_a_correlated_subquery_not_a_python_list_of_ids(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for the cascade's SQL shape, not just its observable outcome.

    A filament with more spools than a SQLite build's bound-variable limit (older builds cap
    it around 999) must not blow that limit. `.in_(<python list of ids>)` binds one SQL parameter
    per id; `.in_(<correlated subquery>)` binds exactly one (the filament_id) no matter how many
    spools it resolves to. This inspects the actual DELETE statement's shape rather than creating
    999+ spools, which the cascade would visibly need to survive but which nothing forces it to
    exercise below the exact threshold that triggers the limit.
    """
    fil = await _add_filament(client, name="Cascade shape")
    await _add_spool(client, fil["id"])
    await _add_spool(client, fil["id"])

    captured_deletes: list[sqlalchemy.sql.dml.Delete] = []
    session_maker = db_module.get_session_maker()
    async with session_maker() as session:
        original_execute = session.execute

        async def _spy_execute(statement: object, *args: object, **kwargs: object) -> object:
            if isinstance(statement, sqlalchemy.sql.dml.Delete):
                captured_deletes.append(statement)
            return await original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", _spy_execute)
        await filament_db.delete(session, fil["id"])

    usage_event_deletes = [stmt for stmt in captured_deletes if stmt.table.name == models.SpoolUsageEvent.__tablename__]
    assert usage_event_deletes, "expected a DELETE against spool_usage_event"
    membership_test = usage_event_deletes[0].whereclause.right
    assert isinstance(membership_test, (sqlalchemy.sql.selectable.Select, sqlalchemy.sql.selectable.ScalarSelect)), (
        "spool_id IN (...) must be built from a correlated subquery, not a Python list of ids bound "
        f"one SQL parameter each; got {type(membership_test)!r} instead"
    )
