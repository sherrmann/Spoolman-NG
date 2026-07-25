"""Built-in MCP server (#360): the curated tool layer, exposed over MCP.

Spoolman mounts a streamable-HTTP MCP endpoint at ``/mcp`` so any MCP client — Claude
Desktop, claude.ai, ChatGPT — can talk to a self-hosted install with zero extra
deployment, version-locked to the API by construction. It needs no LLM provider of its
own: only the ``ai_feature_mcp`` toggle.

**One tool surface, two consumers.** The tools here are the *same* curated implementations
the in-app chat agent calls (:mod:`spoolman.ai_tools`) — never blind CRUD. Reads are always
offered; the curated writes (log usage, create a spool, archive via update) are offered
only to a principal that may write. Delete is deliberately not exposed over MCP.

**Per-request auth without a session.** The transport runs stateless (a fresh task per
request), so the thin ASGI wrapper resolves the caller from the ``Authorization`` bearer
token — reusing Spoolman's own token/role model — and stashes write-eligibility in a
context variable the tool handlers read. A read-only token is offered no mutating tools at
all; the disabled toggle answers 404 so the endpoint is invisible until enabled.
"""

import contextvars
import json
import logging
from collections.abc import Iterable

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyUrl
from starlette.types import Receive, Scope, Send

from spoolman import ai_tools
from spoolman.ai_tools import ToolContext, ToolError
from spoolman.auth import Principal, auth_state
from spoolman.database.database import get_session_maker
from spoolman.settings import SETTINGS
from spoolman.users import ROLE_ADMIN

logger = logging.getLogger(__name__)

SERVER_NAME = "spoolman-ng"

#: The write tools exposed over MCP — the curated set from #360 (log usage, create, archive
#: via update). delete_spool is intentionally excluded: destructive and outside MCP scope.
_MCP_WRITE_TOOLS = ("create_spool", "update_spool", "consume_spool")

#: URI of the low-stock report resource.
LOW_STOCK_URI = "spoolman://low-stock"
RESTOCK_PROMPT = "restock_advisor"

#: Set per-request by the ASGI wrapper from the caller's role. Stateless transport starts a
#: fresh task per request, so this propagates cleanly into the tool handlers.
_can_write: contextvars.ContextVar[bool] = contextvars.ContextVar("mcp_can_write", default=False)

# --- Tools -------------------------------------------------------------------------


def _tool_def(tool: object, *, read_only: bool, destructive: bool = False) -> types.Tool:
    return types.Tool(
        name=tool.name,
        description=tool.description,
        inputSchema=tool.parameters,
        annotations=types.ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive),
    )


async def _list_tools() -> list[types.Tool]:
    """Offer read tools to everyone; curated write tools only to a writer."""
    tools = [_tool_def(tool, read_only=True) for tool in ai_tools.READ_TOOLS.values()]
    if _can_write.get():
        tools.extend(_tool_def(ai_tools.WRITE_TOOLS[name], read_only=False) for name in _MCP_WRITE_TOOLS)
    return tools


async def _execute_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    """Run one curated tool by name, gating writes by role. Raises ToolError on any refusal."""
    if name in ai_tools.READ_TOOLS:
        return await ai_tools.READ_TOOLS[name].run(ctx, args)
    if name in _MCP_WRITE_TOOLS:
        if not ctx.can_write:
            raise ToolError("This account is read-only and cannot make changes.")
        execution = await ai_tools.WRITE_TOOLS[name].execute(ctx, args)
        return {"ok": True, "summary": execution.summary, **execution.data}
    raise ToolError(f"Unknown tool '{name}'.")


async def _call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
    """Dispatch a tool call to the curated implementation; surface refusals as tool output.

    Every failure comes back as tool output rather than a transport error, so the calling
    model can read what went wrong and retry. Unexpected exceptions are logged server-side
    and reported generically — no internal detail crosses the MCP boundary.
    """
    session_maker = get_session_maker()
    try:
        async with session_maker() as session:
            ctx = ToolContext(db=session, can_write=_can_write.get())
            result = await _execute_tool(ctx, name, arguments or {})
    except ToolError as exc:
        return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    except Exception:
        logger.exception("MCP tool %r raised an unexpected error.", name)
        error = "That tool failed unexpectedly. Try again with different arguments."
        return [types.TextContent(type="text", text=json.dumps({"error": error}))]
    return [types.TextContent(type="text", text=json.dumps(result))]


# --- Resources ---------------------------------------------------------------------


async def _list_resources() -> list[types.Resource]:
    return [
        types.Resource(
            uri=AnyUrl(LOW_STOCK_URI),
            name="Low-stock filaments",
            description="Filaments at or below their low-stock threshold, with remaining weight and on-order status.",
            mimeType="application/json",
        ),
    ]


async def _read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
    if str(uri) != LOW_STOCK_URI:
        raise ValueError(f"Unknown resource: {uri}")
    session_maker = get_session_maker()
    async with session_maker() as session:
        ctx = ToolContext(db=session, can_write=False)
        report = await ai_tools.READ_TOOLS["find_filaments"].run(ctx, {"low_stock_only": True, "limit": 100})
    return [ReadResourceContents(content=json.dumps(report), mime_type="application/json")]


# --- Prompts -----------------------------------------------------------------------


async def _list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name=RESTOCK_PROMPT,
            description="Advise what filament to reorder, using low-stock, reserve, and on-order data.",
            arguments=[],
        ),
    ]


async def _get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:  # noqa: ARG001 -- no args, fixed prompt
    if name != RESTOCK_PROMPT:
        raise ValueError(f"Unknown prompt: {name}")
    text = (
        "Call the find_filaments tool with low_stock_only=true, then review the results "
        "(remaining weight, reserve count, whether more is already on order) and recommend what "
        "to reorder and roughly how much, most urgent first. Skip anything already on order. "
        "Be concise and do not use emoji."
    )
    return types.GetPromptResult(
        description="Restock advice from current low-stock data.",
        messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))],
    )


# --- Auth + gating + ASGI wrapper --------------------------------------------------


async def _mcp_enabled() -> bool:
    """Read the ai_feature_mcp toggle (per request; the endpoint is invisible until on)."""
    from spoolman.database import models  # noqa: PLC0415 — avoid an import cycle at module load

    session_maker = get_session_maker()
    async with session_maker() as session:
        definition = SETTINGS["ai_feature_mcp"]
        row = await session.get(models.Setting, "ai_feature_mcp")
        raw = row.value if row is not None else definition.default
        try:
            return bool(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return False


def _bearer_token(scope: Scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key == b"authorization":
            decoded = value.decode("latin-1")
            if decoded.startswith("Bearer "):
                return decoded[len("Bearer ") :].strip()
    return None


def _resolve_principal(scope: Scope) -> Principal | None:
    """Resolve the caller, reusing Spoolman's token/role model. None means unauthenticated.

    When no auth is configured the caller is the anonymous admin, exactly like the rest of
    the API on a default install.
    """
    from spoolman.auth import _principal_for_token  # noqa: PLC0415 — internal reuse

    if not auth_state.auth_required():
        return Principal(name="anonymous", role=ROLE_ADMIN)
    return _principal_for_token(auth_state, _bearer_token(scope))


async def _reject(send: Send, status: int, message: str, *, auth: bool = False) -> None:
    headers = [(b"content-type", b"application/json")]
    if auth:
        headers.append((b"www-authenticate", b"Bearer"))
    body = json.dumps({"message": message}).encode()
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class MCPApp:
    """ASGI endpoint for ``/mcp``: gate on the toggle, authenticate, then hand off to MCP.

    A class instance (not a bare function) so Starlette treats it as an ASGI app and routes
    every method (POST/GET/DELETE) to it rather than GET-only.
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        """Wrap the streamable-HTTP session manager."""
        self._session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject when disabled/unauthenticated, else run the request with role in context."""
        if scope["type"] != "http":
            return
        if not await _mcp_enabled():
            await _reject(send, 404, "The MCP server is not enabled.")
            return
        principal = _resolve_principal(scope)
        if principal is None:
            await _reject(send, 401, "Missing or invalid credentials.", auth=True)
            return
        _can_write.set(principal.role == ROLE_ADMIN)
        await self._session_manager.handle_request(scope, receive, send)


def build_server() -> Server:
    """Create a low-level MCP Server with the curated handlers registered.

    A factory (rather than a module singleton wired via decorators) so tests can build a
    fresh Server + session manager inside their own event loop — the session manager's
    ``run()`` is once-per-instance, so reuse across test cases is not possible.
    """
    srv = Server(SERVER_NAME)
    srv.list_tools()(_list_tools)
    srv.call_tool()(_call_tool)
    srv.list_resources()(_list_resources)
    srv.read_resource()(_read_resource)
    srv.list_prompts()(_list_prompts)
    srv.get_prompt()(_get_prompt)
    return srv


def build_session_manager(srv: Server) -> StreamableHTTPSessionManager:
    """Wrap a Server in a stateless, JSON-response streamable-HTTP session manager."""
    return StreamableHTTPSessionManager(app=srv, json_response=True, stateless=True)


#: The process-wide server and its session manager. Stateless streamable HTTP: a fresh task
#: per request, so per-request role context is clean.
server: Server = build_server()
session_manager: StreamableHTTPSessionManager = build_session_manager(server)
mcp_app: MCPApp = MCPApp(session_manager)

#: Holds the live session-manager run() context between start() and stop() without a module
#: global rebind (mutating a dict entry, not reassigning a name).
_runner: dict[str, object] = {"ctx": None}


async def start() -> None:
    """Start the session manager's task group (call from app startup)."""
    if _runner["ctx"] is not None:
        return
    ctx = session_manager.run()
    await ctx.__aenter__()
    _runner["ctx"] = ctx
    logger.info("MCP server task manager started (endpoint gated by the ai_feature_mcp toggle).")


async def stop() -> None:
    """Stop the session manager's task group (call from app shutdown)."""
    ctx = _runner["ctx"]
    if ctx is not None:
        await ctx.__aexit__(None, None, None)
        _runner["ctx"] = None
