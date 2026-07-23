"""Integration tests for the filament reference-photo endpoints (#88)."""

import hashlib
from typing import Any

import httpx

from ..conftest import URL

# Bigger than 64 KB on purpose: MySQL/MariaDB map a plain LargeBinary to a 64 KB BLOB, so a payload
# above that size proves the LONGBLOB variant is actually in effect on the MariaDB leg of the matrix.
LARGE_PAYLOAD = bytes(range(256)) * 512  # 128 KiB
SMALL_PAYLOAD = b"not really a png, the server stores bytes as-is"
MAX_BYTES = 2 * 1024 * 1024


def test_image_roundtrip(random_filament: dict[str, Any]):
    """Upload an image and read back the identical bytes, headers and filament flag."""
    filament_id = random_filament["id"]

    result = httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=LARGE_PAYLOAD,
        headers={"Content-Type": "image/png"},
    )
    result.raise_for_status()

    assert result.json()["has_image"] is True

    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image")
    result.raise_for_status()
    assert result.content == LARGE_PAYLOAD
    assert result.headers["content-type"] == "image/png"
    assert result.headers["etag"] == f'"{hashlib.sha256(LARGE_PAYLOAD).hexdigest()}"'
    assert "no-cache" in result.headers["cache-control"]
    assert "private" in result.headers["cache-control"]

    # The filament read endpoints expose the flag too
    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}")
    result.raise_for_status()
    assert result.json()["has_image"] is True


def test_image_absent(random_filament: dict[str, Any]):
    """A filament without an image 404s on the image endpoints and omits the flag."""
    filament_id = random_filament["id"]

    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}")
    result.raise_for_status()
    assert "has_image" not in result.json()

    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image")
    assert result.status_code == 404

    result = httpx.delete(f"{URL}/api/v1/filament/{filament_id}/image")
    assert result.status_code == 404


def test_image_conditional_get(random_filament: dict[str, Any]):
    """A matching If-None-Match answers 304 without a body; a stale one re-serves the bytes."""
    filament_id = random_filament["id"]
    httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=SMALL_PAYLOAD,
        headers={"Content-Type": "image/jpeg"},
    ).raise_for_status()
    etag = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image").headers["etag"]

    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image", headers={"If-None-Match": etag})
    assert result.status_code == 304
    assert result.content == b""
    assert result.headers["etag"] == etag

    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image", headers={"If-None-Match": '"stale"'})
    assert result.status_code == 200
    assert result.content == SMALL_PAYLOAD


def test_image_replace(random_filament: dict[str, Any]):
    """A second PUT replaces bytes, content type and ETag in place."""
    filament_id = random_filament["id"]
    httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=SMALL_PAYLOAD,
        headers={"Content-Type": "image/jpeg"},
    ).raise_for_status()
    first_etag = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image").headers["etag"]

    replacement = b"second image body"
    httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=replacement,
        headers={"Content-Type": "image/webp"},
    ).raise_for_status()

    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image")
    result.raise_for_status()
    assert result.content == replacement
    assert result.headers["content-type"] == "image/webp"
    assert result.headers["etag"] != first_etag

    # The pre-replace ETag no longer matches, so a conditional GET re-serves the new bytes.
    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}/image", headers={"If-None-Match": first_etag})
    assert result.status_code == 200
    assert result.content == replacement


def test_image_delete(random_filament: dict[str, Any]):
    """DELETE removes the image; the flag disappears and a second DELETE 404s."""
    filament_id = random_filament["id"]
    httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=SMALL_PAYLOAD,
        headers={"Content-Type": "image/png"},
    ).raise_for_status()

    result = httpx.delete(f"{URL}/api/v1/filament/{filament_id}/image")
    assert result.status_code == 204

    assert httpx.get(f"{URL}/api/v1/filament/{filament_id}/image").status_code == 404
    result = httpx.get(f"{URL}/api/v1/filament/{filament_id}")
    result.raise_for_status()
    assert "has_image" not in result.json()

    assert httpx.delete(f"{URL}/api/v1/filament/{filament_id}/image").status_code == 404


def test_image_rejects_unsupported_type(random_filament: dict[str, Any]):
    """Only the image content-type allowlist is accepted."""
    filament_id = random_filament["id"]

    result = httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=SMALL_PAYLOAD,
        headers={"Content-Type": "text/plain"},
    )
    assert result.status_code == 415

    result = httpx.put(f"{URL}/api/v1/filament/{filament_id}/image", content=SMALL_PAYLOAD)
    assert result.status_code == 415

    # Nothing was stored by the rejected uploads
    assert httpx.get(f"{URL}/api/v1/filament/{filament_id}/image").status_code == 404


def test_image_rejects_oversized(random_filament: dict[str, Any]):
    """A body over the size cap is rejected with 413 and stores nothing."""
    filament_id = random_filament["id"]

    result = httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=b"x" * (MAX_BYTES + 1),
        headers={"Content-Type": "image/png"},
    )
    assert result.status_code == 413
    assert httpx.get(f"{URL}/api/v1/filament/{filament_id}/image").status_code == 404


def test_image_rejects_empty_body(random_filament: dict[str, Any]):
    """An empty body is a 400, not an empty stored image."""
    filament_id = random_filament["id"]

    result = httpx.put(
        f"{URL}/api/v1/filament/{filament_id}/image",
        content=b"",
        headers={"Content-Type": "image/png"},
    )
    assert result.status_code == 400
    assert httpx.get(f"{URL}/api/v1/filament/{filament_id}/image").status_code == 404


def test_image_of_missing_filament():
    """All three endpoints 404 for a filament that does not exist."""
    assert httpx.get(f"{URL}/api/v1/filament/123456789/image").status_code == 404
    result = httpx.put(
        f"{URL}/api/v1/filament/123456789/image",
        content=SMALL_PAYLOAD,
        headers={"Content-Type": "image/png"},
    )
    assert result.status_code == 404
    assert httpx.delete(f"{URL}/api/v1/filament/123456789/image").status_code == 404


def test_delete_filament_with_image(random_vendor: dict[str, Any]):
    """Deleting a filament also cleans up its image row (no orphan, no FK failure on any backend)."""
    result = httpx.post(
        f"{URL}/api/v1/filament",
        json={"name": "Filament with image", "vendor_id": random_vendor["id"], "density": 1.25, "diameter": 1.75},
    )
    result.raise_for_status()
    filament = result.json()

    httpx.put(
        f"{URL}/api/v1/filament/{filament['id']}/image",
        content=LARGE_PAYLOAD,
        headers={"Content-Type": "image/png"},
    ).raise_for_status()

    httpx.delete(f"{URL}/api/v1/filament/{filament['id']}").raise_for_status()

    assert httpx.get(f"{URL}/api/v1/filament/{filament['id']}").status_code == 404
    assert httpx.get(f"{URL}/api/v1/filament/{filament['id']}/image").status_code == 404
