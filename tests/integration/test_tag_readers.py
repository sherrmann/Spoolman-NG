"""The reader registry remembers the last UID each reader reported (ported from upstream).

A client that wants to link a tag can then offer what is already lying on the reader instead of
asking for another tap. That matters for a reader built into a scale: the spool is on the pad to
be weighed, and lifting it off and putting it back just to fill in a field reads as the dialog not
working. The registry is in memory only, so the field is null until a reader has scanned since
the server started.

These drive the HTTP surface rather than the ScanRelay class (tests/test_scan_relay.py does that):
the contract a client relies on is what GET /tag/reader returns after POST /tag/scan.
"""

import uuid

import pytest
from httpx import AsyncClient

SCAN = "/api/v1/tag/scan"
READERS = "/api/v1/tag/reader"


def _reader_id() -> str:
    # The relay is a process-wide singleton shared by every test, so ids must be unique per test.
    return f"test-{uuid.uuid4().hex[:8]}"


async def _reader(client: AsyncClient, reader_id: str) -> dict:
    resp = await client.get(READERS)
    assert resp.status_code == 200, resp.text
    rows = [r for r in resp.json() if r["reader_id"] == reader_id]
    assert len(rows) == 1, resp.json()
    return rows[0]


@pytest.mark.asyncio
async def test_reader_reports_the_last_uid_it_scanned(client: AsyncClient):
    reader_id = _reader_id()

    resp = await client.post(SCAN, json={"uid": "04:a2:b3:c4", "reader_id": reader_id, "name": "Desk"})
    assert resp.status_code == 200, resp.text

    reader = await _reader(client, reader_id)
    # Normalised, the same shape the scan response echoes and the tag is stored under.
    assert reader["last_uid"] == "04A2B3C4"
    assert reader["name"] == "Desk"


@pytest.mark.asyncio
async def test_a_later_scan_replaces_the_remembered_uid(client: AsyncClient):
    """One UID, not a history: the answer is "what is on the reader", not "what has been"."""
    reader_id = _reader_id()

    await client.post(SCAN, json={"uid": "04A2B3C4", "reader_id": reader_id})
    await client.post(SCAN, json={"uid": "0455667788", "reader_id": reader_id})

    assert (await _reader(client, reader_id))["last_uid"] == "0455667788"


@pytest.mark.asyncio
async def test_a_rejected_uid_leaves_the_registry_alone(client: AsyncClient):
    """A scan the server refuses never reached the reader's entry, so nothing is remembered."""
    reader_id = _reader_id()

    resp = await client.post(SCAN, json={"uid": "not hex", "reader_id": reader_id})
    assert resp.status_code == 400, resp.text

    resp = await client.get(READERS)
    assert resp.status_code == 200
    assert [r for r in resp.json() if r["reader_id"] == reader_id] == []
