"""Tests for the optional request timing (``spoolman.timing``).

The oracle is the documented behaviour: a ``Server-Timing`` header when enabled (never on 401, 403 or
the auth routes), a WARNING log for requests at or over the slow threshold (never for event streams),
and database time and query counts taken from real queries on an in-memory aiosqlite engine.
"""

import logging
import re
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from spoolman import timing
from spoolman.timing import TimingMiddleware, install_query_timer

_HEADER_RE = re.compile(r"^app;dur=(\d+\.\d), db;dur=(\d+\.\d)$")


def _build_app(*, server_timing: bool, slow_ms: int | None, engine: Any = None) -> Starlette:  # noqa: ANN401
    async def ok(_: Request) -> Response:
        return JSONResponse({"ok": True})

    async def denied(_: Request) -> Response:
        return JSONResponse({"message": "no"}, status_code=401)

    async def forbidden(_: Request) -> Response:
        return JSONResponse({"message": "no"}, status_code=403)

    async def login(_: Request) -> Response:
        return JSONResponse({"ok": True})

    async def stream(_: Request) -> Response:
        async def chunks() -> Any:  # noqa: ANN401
            yield b"data: hi\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    async def queries(_: Request) -> Response:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
            await conn.execute(text("select 2"))
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/ok", ok),
            Route("/denied", denied),
            Route("/forbidden", forbidden),
            Route("/api/v1/auth/login", login, methods=["GET", "POST"]),
            Route("/stream", stream),
            Route("/queries", queries),
        ],
    )
    app.add_middleware(TimingMiddleware, server_timing=server_timing, slow_ms=slow_ms)
    return app


def test_header_present_and_parseable_when_enabled() -> None:
    """The header carries app and db durations with one decimal and no query count."""
    client = TestClient(_build_app(server_timing=True, slow_ms=None))
    header = client.get("/ok").headers["server-timing"]
    assert _HEADER_RE.match(header)
    assert "quer" not in header


def test_header_absent_when_disabled() -> None:
    """Nothing is added when Server-Timing is off."""
    client = TestClient(_build_app(server_timing=False, slow_ms=None))
    assert "server-timing" not in client.get("/ok").headers


@pytest.mark.parametrize("path", ["/denied", "/forbidden", "/api/v1/auth/login"])
def test_header_withheld_from_auth_responses(path: str) -> None:
    """401, 403 and the auth routes never expose a server time."""
    client = TestClient(_build_app(server_timing=True, slow_ms=None))
    assert "server-timing" not in client.get(path).headers


def test_header_withheld_under_base_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The auth exclusion also applies when the app is served under a base path."""
    monkeypatch.setenv("SPOOLMAN_BASE_PATH", "/spoolman")
    app = _build_app(server_timing=True, slow_ms=None)
    app.router.routes.append(Route("/spoolman/api/v1/auth/login", lambda _: JSONResponse({}), methods=["POST"]))
    client = TestClient(app)
    assert "server-timing" not in client.post("/spoolman/api/v1/auth/login").headers


def test_slow_request_logged_at_zero_threshold(caplog: pytest.LogCaptureFixture) -> None:
    """A threshold of 0 logs every request, with method, path, status and no query string."""
    client = TestClient(_build_app(server_timing=False, slow_ms=0))
    with caplog.at_level(logging.WARNING, logger="spoolman.timing"):
        client.get("/ok?secret=1")
    messages = [r.getMessage() for r in caplog.records if r.name == "spoolman.timing"]
    assert len(messages) == 1
    assert "GET /ok -> 200" in messages[0]
    assert "secret" not in messages[0]
    assert "0 queries" in messages[0]


def test_slow_request_not_logged_below_threshold(caplog: pytest.LogCaptureFixture) -> None:
    """A fast request under a high threshold is not logged."""
    client = TestClient(_build_app(server_timing=False, slow_ms=10_000_000))
    with caplog.at_level(logging.WARNING, logger="spoolman.timing"):
        client.get("/ok")
    assert not [r for r in caplog.records if r.name == "spoolman.timing"]


def test_event_stream_not_slow_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Event streams are skipped even at a threshold of 0."""
    client = TestClient(_build_app(server_timing=False, slow_ms=0))
    with caplog.at_level(logging.WARNING, logger="spoolman.timing"):
        client.get("/stream")
    assert not [r for r in caplog.records if r.name == "spoolman.timing"]


def test_queries_counted_and_db_time_reported(caplog: pytest.LogCaptureFixture) -> None:
    """Two queries in a request give a positive db duration and a count of 2 in the log."""
    engine = create_async_engine("sqlite+aiosqlite://")
    install_query_timer(engine)
    client = TestClient(_build_app(server_timing=True, slow_ms=0, engine=engine))
    with caplog.at_level(logging.WARNING, logger="spoolman.timing"):
        response = client.get("/queries")
    match = _HEADER_RE.match(response.headers["server-timing"])
    assert match
    assert float(match.group(2)) > 0
    messages = [r.getMessage() for r in caplog.records if r.name == "spoolman.timing"]
    assert "2 queries" in messages[0]


@pytest.mark.asyncio
async def test_queries_outside_a_request_count_into_nothing() -> None:
    """With no holder set the listeners do nothing and do not fail."""
    engine = create_async_engine("sqlite+aiosqlite://")
    install_query_timer(engine)
    async with engine.connect() as conn:
        await conn.execute(text("select 1"))
    assert timing._current.get() is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_websocket_scope_passes_through_untouched() -> None:
    """Non-HTTP scopes reach the inner app with the original send."""
    seen: dict[str, Any] = {}

    async def inner(scope: Any, _receive: Any, send: Any) -> None:  # noqa: ANN401
        seen["scope"], seen["send"] = scope, send

    async def send(_: Any) -> None:  # noqa: ANN401
        return None

    scope = {"type": "websocket", "path": "/ws"}
    await TimingMiddleware(inner, server_timing=True, slow_ms=0)(scope, None, send)  # type: ignore[arg-type]
    assert seen["send"] is send
    assert seen["scope"] is scope
