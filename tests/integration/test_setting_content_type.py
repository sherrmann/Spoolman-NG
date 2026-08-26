"""Non-JSON bodies on POST /setting/{key} are refused (upstream security/backend-audit-todo).

POST /setting/{key} takes a bare `str` body, and FastAPI only JSON-parses `application/*json` --
anything else arrives as raw bytes that lax-mode Pydantic happily coerces. A `text/plain` body was
therefore accepted, which is exactly what `<form enctype="text/plain">` sends, so any website the
user visited could rewrite settings through their browser. `require_json_content_type` closes
that: only a JSON (or `+json`) content type is accepted; everything else gets a 415.
"""

import json

from httpx import AsyncClient

SETTING = "/api/v1/setting/currency"


async def test_a_json_body_is_accepted(client: AsyncClient):
    resp = await client.post(
        SETTING,
        content=json.dumps(json.dumps("EUR")),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["value"] == json.dumps("EUR")


async def test_a_json_body_with_charset_is_accepted(client: AsyncClient):
    resp = await client.post(
        SETTING,
        content=json.dumps(json.dumps("USD")),
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert resp.status_code == 200, resp.text


async def test_a_text_plain_body_is_refused(client: AsyncClient):
    """Exactly what <form enctype="text/plain"> sends -- the CSRF vector the audit found."""
    resp = await client.post(SETTING, content=json.dumps("EUR"), headers={"content-type": "text/plain"})
    assert resp.status_code == 415, resp.text


async def test_a_missing_content_type_is_refused(client: AsyncClient):
    # httpx sets no Content-Type header for raw `content=` unless one is given explicitly --
    # this is the request shape a bare `fetch(url, {method: "POST", body: ...})` sends.
    resp = await client.post(SETTING, content=json.dumps("EUR"))
    assert resp.status_code == 415, resp.text


async def test_a_form_urlencoded_body_is_refused(client: AsyncClient):
    resp = await client.post(
        SETTING,
        content="value=EUR",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 415, resp.text


async def test_a_setting_is_unaffected_by_a_refused_write(client: AsyncClient):
    """The 415 must be refused before the setting is touched -- no partial write."""
    resp = await client.get(SETTING)
    assert resp.status_code == 200
    before = resp.json()

    resp = await client.post(SETTING, content=json.dumps("GBP"), headers={"content-type": "text/plain"})
    assert resp.status_code == 415

    resp = await client.get(SETTING)
    assert resp.json() == before
