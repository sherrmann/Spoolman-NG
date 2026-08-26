"""Integration tests for extra_fields_* settings written through POST /setting/{key}.

Ported alongside the extra_field_registry.py structural port from upstream: the /field endpoints
validate what they write, but the generic settings endpoint did not, so a malformed extra_fields_*
array written that way used to be accepted and then fail to parse on every later GET /field/{entity}
(a permanent 500). Also confirms the in-memory registry cache is invalidated by this endpoint, so a
direct settings write is picked up immediately rather than only after a restart.
"""

import json

from httpx import AsyncClient

FIELD = "/api/v1/field"
SETTING = "/api/v1/setting/extra_fields_spool"
HEADERS = {"content-type": "application/json"}


async def test_malformed_extra_field_setting_is_rejected(client: AsyncClient):
    resp = await client.post(SETTING, content=json.dumps(json.dumps([{"key": "nope"}])), headers=HEADERS)
    assert resp.status_code == 400, resp.text


async def test_non_array_extra_field_setting_is_rejected(client: AsyncClient):
    resp = await client.post(SETTING, content=json.dumps(json.dumps({"key": "batch"})), headers=HEADERS)
    assert resp.status_code == 400, resp.text


async def test_valid_extra_field_setting_is_accepted_and_cache_is_invalidated(client: AsyncClient):
    payload = [
        {
            "key": "batch",
            "entity_type": "spool",
            "name": "Batch",
            "field_type": "text",
            "order": 0,
        },
    ]
    resp = await client.post(SETTING, content=json.dumps(json.dumps(payload)), headers=HEADERS)
    assert resp.status_code == 200, resp.text

    # Written directly through /setting, not /field -- only the invalidated cache makes this visible
    # without a restart.
    resp = await client.get(f"{FIELD}/spool")
    assert resp.status_code == 200, resp.text
    keys = {f["key"] for f in resp.json()}
    assert "batch" in keys


async def test_other_settings_are_unaffected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/setting/currency",
        content=json.dumps(json.dumps("EUR")),
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
