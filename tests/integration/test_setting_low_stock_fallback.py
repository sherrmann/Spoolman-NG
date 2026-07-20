"""Integration test for the low_stock_fallback_g instance setting (#298 low-stock redesign).

The merged per-filament Low Stock view flags a filament with no explicit low_stock_threshold once its
aggregate remaining weight drops to/below this global fallback (absolute grams). It ships registered
with a sensible default so Low Stock works out of the box (US5); it is settable and type-checked.
"""

import json

from httpx import AsyncClient

SETTING = "/api/v1/setting/low_stock_fallback_g"
HEADERS = {"content-type": "application/json"}


async def test_fallback_setting_has_shipped_default(client: AsyncClient):
    resp = await client.get(SETTING)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_set"] is False  # unset -> the registered default is returned
    assert json.loads(body["value"]) == 200


async def test_fallback_setting_is_settable(client: AsyncClient):
    assert (await client.post(SETTING, content=json.dumps(json.dumps(350)), headers=HEADERS)).status_code == 200
    body = (await client.get(SETTING)).json()
    assert body["is_set"] is True
    assert json.loads(body["value"]) == 350


async def test_fallback_setting_rejects_non_number(client: AsyncClient):
    bad = await client.post(SETTING, content=json.dumps(json.dumps("lots")), headers=HEADERS)
    assert bad.status_code == 400, bad.text
