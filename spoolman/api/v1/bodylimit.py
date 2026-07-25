"""Per-path request-body size limits.

The AI upload endpoints accept user media — a label photo as base64 JSON, a voice clip as
multipart — and both would otherwise be buffered in full (in memory for JSON, spooled to
disk for multipart) *before* the handler ever runs and gets a chance to measure them. A
size check inside the handler is therefore too late to bound anything.

This middleware enforces the cap at the only layer that can: while the request body is
still arriving. A declared ``Content-Length`` over the cap is refused before a single byte
is read. Without one (a chunked upload) the body is drained here, stopping at the cap — so
the peak buffered is the cap plus one chunk, never the whole upload. Handlers keep their
own checks as defence in depth: those produce the precise, per-feature messages, while
this stops the pathological case ever reaching them.

Only the paths listed in ``LIMITS`` are inspected; every other route passes straight
through untouched.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: ~15 MB of image once the base64 in the JSON body is decoded; the client downscales to
#: 1568 px before sending, so a real request is a couple of hundred KB.
MAX_IMAGE_BODY_BYTES = 20 * 1024 * 1024

#: Matches the common Whisper upload ceiling; a push-to-talk clip is far smaller.
MAX_AUDIO_BODY_BYTES = 25 * 1024 * 1024

#: Mount-relative path -> maximum request body in bytes.
LIMITS: dict[str, int] = {
    "/ai/spool-intake/extract": MAX_IMAGE_BODY_BYTES,
    "/ai/transcribe": MAX_AUDIO_BODY_BYTES,
}


def _mount_relative_path(scope: Scope) -> str:
    """Return the request path relative to the app this middleware wraps.

    Starlette keeps the full path in ``scope["path"]`` and the mount prefix (``/api/v1``
    plus any ``SPOOLMAN_BASE_PATH``) in ``scope["root_path"]``, so matching the
    sub-app-relative keys in LIMITS means stripping that prefix first.
    """
    path = scope.get("path") or ""
    root_path = scope.get("root_path") or ""
    if root_path and path.startswith(root_path):
        return path[len(root_path) :] or "/"
    return path


def _declared_length(scope: Scope) -> int | None:
    """Return the Content-Length header as an int, or None when absent/unparseable."""
    for key, value in scope.get("headers", []):
        if key == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodyLimitMiddleware:
    """Pure-ASGI middleware rejecting oversize request bodies on the configured paths."""

    def __init__(self, app: ASGIApp, limits: dict[str, int] | None = None) -> None:
        """Wrap the ASGI app; ``limits`` maps a mount-relative path to a byte cap."""
        self.app = app
        self.limits = LIMITS if limits is None else limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Enforce the cap for a limited path; pass everything else through."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limits.get(_mount_relative_path(scope))
        if limit is None:
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await _reject(send, limit)
            return

        body, overflowed = await _drain(receive, limit)
        if overflowed:
            await _reject(send, limit)
            return
        await self.app(scope, _replay(body), send)


async def _drain(receive: Receive, limit: int) -> tuple[bytes, bool]:
    """Read the request body, stopping as soon as it passes ``limit``.

    Returns the bytes read and whether the cap was exceeded. On overflow reading stops
    immediately, so an endless upload is abandoned rather than accumulated.
    """
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return b"", True
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks), False


def _replay(body: bytes) -> Receive:
    """Return a receive callable that hands the already-drained body to the app."""
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


async def _reject(send: Send, limit: int) -> None:
    """Send a 413 with the same message shape the rest of the API uses."""
    body = json.dumps({"message": f"Request body is too large (limit {limit} bytes)."}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        },
    )
    await send({"type": "http.response.body", "body": body})
