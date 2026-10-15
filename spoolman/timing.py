"""Optional per-request timing: a ``Server-Timing`` header and a slow-request log.

Both features are off by default (``SPOOLMAN_SERVER_TIMING`` and ``SPOOLMAN_SLOW_REQUEST_MS``),
and ``main.py`` installs nothing at all unless one of them is on, so the default request path
is unchanged.

What is measured: the time from the request reaching this middleware until the response
*starts* (the ``http.response.start`` message), plus the part of that spent in SQL. It is
therefore a time to first byte. It covers the handler and the database, and it does not cover
sending the body to a slow client. Because the clock stops at the first byte, a long
streaming response (an AI chat stream, the MCP event stream) is never counted as slow, and
``text/event-stream`` responses are skipped by the slow-request log explicitly. When
``GZipMiddleware`` sits inside this one it holds a small response back until its body is
compressed, so that compression is inside the figure; a streamed body is not.

The ``Server-Timing`` header is withheld from 401 and 403 responses and from everything under
``/api/v1/auth/``. The login endpoint answers an unknown user before it hashes a password, so
an exact server time on a failed login would tell an attacker which usernames exist.
Rejections by the auth and origin guards are withheld for the same reason: they are quick
by design and say nothing the caller needs. The query count is only ever logged, never sent,
since it reveals how the handler is built.

Database time is collected with SQLAlchemy cursor events (``install_query_timer``). The async
engine runs the cursor in a greenlet that inherits the awaiting task's context, so the
per-request holder in a ``ContextVar`` is visible to the listeners. Outside a request (start-up,
background tasks) the variable is ``None`` and the listeners count into nothing.
"""

import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from spoolman import env

logger = logging.getLogger(__name__)

#: Path (below any base path) whose responses never carry a Server-Timing header.
_AUTH_PREFIX = "/api/v1/auth/"

#: Statuses that never carry a Server-Timing header.
_UNTIMED_STATUSES = frozenset({401, 403})


@dataclass
class RequestTiming:
    """Database cost accumulated while serving one request."""

    db_seconds: float = 0.0
    queries: int = 0


_current: ContextVar[RequestTiming | None] = ContextVar("spoolman_request_timing", default=None)


def install_query_timer(engine: AsyncEngine) -> None:
    """Count queries and their time into the current request's holder, if there is one."""
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before_cursor_execute(*args: Any) -> None:  # noqa: ANN401  # SQLAlchemy's fixed listener signature
        context = args[4]  # (conn, cursor, statement, parameters, context, executemany)
        if _current.get() is not None:
            context._spoolman_t0 = time.perf_counter()  # noqa: SLF001

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after_cursor_execute(*args: Any) -> None:  # noqa: ANN401  # SQLAlchemy's fixed listener signature
        context = args[4]
        holder = _current.get()
        started = getattr(context, "_spoolman_t0", None)
        if holder is None or started is None:
            return
        holder.db_seconds += time.perf_counter() - started
        holder.queries += 1
        context._spoolman_t0 = None  # noqa: SLF001


def _path_below_base(scope: Scope) -> str:
    """Return the request path without the ingress root path and ``SPOOLMAN_BASE_PATH``."""
    path = scope.get("path") or ""
    root_path = scope.get("root_path") or ""
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :]
    base_path = env.get_base_path()
    if base_path and path.startswith(base_path):
        path = path[len(base_path) :]
    return path


class TimingMiddleware:
    """Pure-ASGI middleware adding ``Server-Timing`` and/or logging slow requests.

    See the module docstring for what is measured and why some responses are left out.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        server_timing: bool | None = None,
        slow_ms: int | None = None,
    ) -> None:
        """Wrap the ASGI app; both settings default to the environment."""
        self.app = app
        self.server_timing = env.get_server_timing_enabled() if server_timing is None else server_timing
        self.slow_ms = env.get_slow_request_ms() if slow_ms is None else slow_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Time an HTTP request; pass websocket and lifespan scopes straight through."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        holder = RequestTiming()
        token = _current.set(holder)
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed = time.perf_counter() - started
                message = self._on_response_start(scope, message, holder, elapsed)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _current.reset(token)

    def _on_response_start(self, scope: Scope, message: Message, holder: RequestTiming, elapsed: float) -> Message:
        """Log the request if slow and add the Server-Timing header if allowed."""
        status = message["status"]
        headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))

        if self.slow_ms is not None and elapsed * 1000 >= self.slow_ms:
            content_type = next((v for k, v in headers if k.lower() == b"content-type"), b"")
            if not content_type.lower().startswith(b"text/event-stream"):
                logger.warning(
                    "Slow request: %s %s -> %d in %.1f ms (database %.1f ms, %d queries)",
                    scope.get("method", "?"),
                    scope.get("path", ""),
                    status,
                    elapsed * 1000,
                    holder.db_seconds * 1000,
                    holder.queries,
                )

        if (
            self.server_timing
            and status not in _UNTIMED_STATUSES
            and not _path_below_base(scope).startswith(_AUTH_PREFIX)
        ):
            value = f"app;dur={elapsed * 1000:.1f}, db;dur={holder.db_seconds * 1000:.1f}"
            headers.append((b"server-timing", value.encode("latin-1")))
            message = {**message, "headers": headers}
        return message
