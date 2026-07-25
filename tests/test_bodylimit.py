"""Unit tests for the per-path request-body size limits.

The point of the middleware is that it acts *before* the body is buffered, so these drive
it as raw ASGI: a declared Content-Length over the cap must be refused without the app
ever being called, and a chunked body must be cut off mid-stream rather than accumulated.
"""

import json

import pytest
from starlette.types import Receive, Scope, Send

from spoolman.api.v1.bodylimit import BodyLimitMiddleware

_LIMITS = {"/ai/transcribe": 100}


class _Recorder:
    """Minimal ASGI app that records whether it ran and what body it received."""

    def __init__(self) -> None:
        self.called = False
        self.body = b""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:  # noqa: ARG002
        self.called = True
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            self.body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _scope(path: str, *, content_length: int | None = None, root_path: str = "") -> Scope:
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    return {"type": "http", "method": "POST", "path": root_path + path, "root_path": root_path, "headers": headers}


def _receive_from(chunks: list[bytes]) -> Receive:
    remaining = list(chunks)

    async def receive() -> dict:
        body = remaining.pop(0) if remaining else b""
        return {"type": "http.request", "body": body, "more_body": bool(remaining)}

    return receive


class _Sink:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return message["status"]
        return None

    @property
    def body(self) -> bytes:
        return b"".join(m.get("body", b"") for m in self.messages if m["type"] == "http.response.body")


async def _run(scope: Scope, chunks: list[bytes]) -> tuple[_Recorder, _Sink]:
    app = _Recorder()
    sink = _Sink()
    await BodyLimitMiddleware(app, _LIMITS)(scope, _receive_from(chunks), sink)
    return app, sink


async def test_declared_length_over_the_cap_is_refused_before_the_app_runs() -> None:
    app, sink = await _run(_scope("/ai/transcribe", content_length=101), [b"x" * 101])
    assert sink.status == 413
    assert json.loads(sink.body)["message"].startswith("Request body is too large")
    # The whole point: nothing downstream ever saw the request.
    assert app.called is False


async def test_declared_length_at_the_cap_passes_through() -> None:
    app, sink = await _run(_scope("/ai/transcribe", content_length=100), [b"x" * 100])
    assert sink.status == 200
    assert app.body == b"x" * 100


async def test_chunked_body_over_the_cap_is_cut_off() -> None:
    # No Content-Length: the only way to bound this is to count as it arrives.
    app, sink = await _run(_scope("/ai/transcribe"), [b"x" * 60, b"x" * 60])
    assert sink.status == 413
    assert app.called is False


async def test_chunked_body_under_the_cap_is_replayed_intact() -> None:
    app, sink = await _run(_scope("/ai/transcribe"), [b"abc", b"def"])
    assert sink.status == 200
    assert app.body == b"abcdef"


async def test_unlimited_paths_are_passed_straight_through() -> None:
    app, sink = await _run(_scope("/spool", content_length=10_000_000), [b"x" * 1000])
    assert sink.status == 200
    assert app.called is True


async def test_the_limit_matches_on_the_mount_relative_path() -> None:
    # Mounted under /api/v1 (plus any base path) the full path carries a prefix that has to
    # be stripped before the limit table is consulted — otherwise the cap silently never
    # applies in a real deployment while passing an unmounted unit test.
    app, sink = await _run(_scope("/ai/transcribe", content_length=101, root_path="/api/v1"), [b"x"])
    assert sink.status == 413
    assert app.called is False


async def test_an_unparseable_content_length_falls_back_to_counting() -> None:
    scope = _scope("/ai/transcribe")
    scope["headers"] = [(b"content-length", b"not-a-number")]
    app, sink = await _run(scope, [b"x" * 101])
    assert sink.status == 413
    assert app.called is False


@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_non_http_scopes_are_untouched(scope_type: str) -> None:
    app = _Recorder()

    async def receive() -> dict:
        return {"type": "nope"}

    await BodyLimitMiddleware(app, _LIMITS)({"type": scope_type, "path": "/ai/transcribe"}, receive, _Sink())
    assert app.called is True


# --- Wiring ------------------------------------------------------------------------


def test_the_middleware_is_installed_outermost_on_the_v1_app() -> None:
    """Order matters: it has to wrap auth, so an oversize body dies before anything reads it.

    A correct middleware that was never installed — or installed inside the auth layer —
    would leave the endpoints exactly as exposed as before, so pin both facts here.
    """
    from spoolman.api.v1.router import app  # noqa: PLC0415 -- import cost only for this test

    stack = [middleware.cls for middleware in app.user_middleware]
    assert BodyLimitMiddleware in stack
    assert stack[0] is BodyLimitMiddleware


def test_the_real_limits_cover_both_ai_upload_endpoints() -> None:
    from spoolman.api.v1 import bodylimit  # noqa: PLC0415

    assert set(bodylimit.LIMITS) == {"/ai/spool-intake/extract", "/ai/transcribe"}
