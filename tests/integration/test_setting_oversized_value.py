"""An oversized setting value is a 400, not a 500 (upstream 7d683eb2).

spoolman/database/setting.py already caps a setting's value at SETTING_MAX_LENGTH (the Text
column's practical limit) and raises ValueError past it. POST /setting/{key} did not catch that
ValueError, so an oversized write 500'd instead of getting a normal validation error, and left
the setting unset.

Wire format note: a setting's "value" is itself a JSON-encoded string (e.g. the STRING setting
`base_url` stores the JSON text `"/spoolman"`, quotes included). POST /setting/{key} takes that
JSON text as a `str` body over a `content-type: application/json` request, so FastAPI itself
JSON-decodes the wire body once before the endpoint ever sees it. Sending the setting's JSON
representation as the wire body therefore requires encoding it *again* -- double `json.dumps` --
so that after FastAPI's one decode, the endpoint's `body` variable is exactly the setting's JSON
text. Every existing setting test in this suite follows this convention (see
tests/integration/test_extra_field_setting_endpoint.py); sending it only once here would have
FastAPI's own decode already strip the setting's JSON syntax, and the endpoint's later
`json.loads(body)` (in `SettingDefinition.validate_type`) would then fail on the bare, no-longer-
JSON text -- a 400 for the wrong reason, not the SETTING_MAX_LENGTH check this file exists to test.
"""

import json

from httpx import AsyncClient

from spoolman.database.setting import SETTING_MAX_LENGTH

SETTING = "/api/v1/setting/base_url"
HEADERS = {"content-type": "application/json"}


async def test_an_oversized_value_is_a_400_not_a_500(client: AsyncClient):
    # The JSON text of a 65536-character string, which is what setting.update() measures.
    oversized_setting_value = json.dumps("x" * (SETTING_MAX_LENGTH + 1))
    resp = await client.post(SETTING, content=json.dumps(oversized_setting_value), headers=HEADERS)
    assert resp.status_code == 400, resp.text
    assert "too big" in resp.json()["message"]


async def test_an_oversized_write_leaves_the_setting_unset(client: AsyncClient):
    oversized_setting_value = json.dumps("x" * (SETTING_MAX_LENGTH + 1))
    resp = await client.post(SETTING, content=json.dumps(oversized_setting_value), headers=HEADERS)
    assert resp.status_code == 400

    resp = await client.get(SETTING)
    assert resp.status_code == 200
    assert resp.json()["is_set"] is False


async def test_a_value_at_the_limit_is_accepted(client: AsyncClient):
    # The JSON text of a string sized so the JSON text itself (quotes included) is exactly
    # SETTING_MAX_LENGTH -- the boundary the "oversized" tests approach from the other side.
    at_limit_setting_value = json.dumps("x" * (SETTING_MAX_LENGTH - 2))
    assert len(at_limit_setting_value) == SETTING_MAX_LENGTH

    resp = await client.post(SETTING, content=json.dumps(at_limit_setting_value), headers=HEADERS)
    assert resp.status_code == 200, resp.text
