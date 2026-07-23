"""Built-in MCP server (#360): the curated tool layer over streamable HTTP at /mcp.

Implements the *stateless* subset of the MCP streamable-HTTP transport directly —
deliberately no SDK dependency, so the endpoint is version-locked to this codebase
by construction and adds nothing to the (armv7-sensitive) dependency set. The
subset is what request-response tool servers need and what Claude Desktop,
claude.ai connectors, and Claude Code speak:

* ``POST /mcp`` with a single JSON-RPC message; requests get a plain JSON response
  (the spec allows JSON instead of an SSE stream), notifications get 202.
* No sessions (the spec makes ``Mcp-Session-Id`` optional), no server-initiated
  streams (``GET /mcp`` answers 405, as the spec prescribes for servers without one),
  no batching (removed in protocol 2025-06-18).

Auth mirrors the API's opt-in model (spoolman/auth.py): with no token/accounts
configured every caller is an anonymous admin; otherwise ``Authorization: Bearer``
is required, and readonly principals see (and can call) only read-only tools.
The endpoint is enabled by the ``mcp_enabled`` setting and answers 404 while off.
"""

import json
import logging
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import aitools, env
from spoolman.auth import Principal, resolve_principal_for_token
from spoolman.database import models
from spoolman.database.database import get_db_session
from spoolman.settings import SETTINGS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})
LATEST_PROTOCOL_VERSION = "2025-06-18"

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603
_RESOURCE_NOT_FOUND = -32002

SERVER_INSTRUCTIONS = (
    "Spoolman NG manages a 3D-printing filament inventory: filaments (types) and spools "
    "(physical rolls) with remaining weight tracked in grams. Use find_filaments/find_spools "
    "to look things up before mutating anything; weights are grams, lengths millimeters."
)


async def _mcp_enabled(db: AsyncSession) -> bool:
    definition = SETTINGS["mcp_enabled"]
    row = await db.get(models.Setting, definition.key)
    raw = row.value if row is not None else definition.default
    try:
        return bool(json.loads(raw))
    except json.JSONDecodeError:
        return False


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    prefix = "Bearer "
    if not header.startswith(prefix):
        return None
    return header[len(prefix) :].strip() or None


def _origin_mismatch(request: Request) -> bool:
    """DNS-rebinding guard: a browser-sent Origin must match the host being addressed.

    Native MCP clients send no Origin header and pass through untouched.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return urlsplit(origin).netloc != request.headers.get("host", "")


def _rpc_result(msg_id: Any, result: dict) -> dict:  # noqa: ANN401
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id: Any, code: int, message: str) -> dict:  # noqa: ANN401
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


# --- Method handlers ---------------------------------------------------------------


async def _handle_initialize(_db: AsyncSession, _principal: Principal, params: dict) -> dict:
    requested = params.get("protocolVersion")
    negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return {
        "protocolVersion": negotiated,
        "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        "serverInfo": {"name": "spoolman-ng", "version": env.get_version()},
        "instructions": SERVER_INSTRUCTIONS,
    }


async def _handle_ping(_db: AsyncSession, _principal: Principal, _params: dict) -> dict:
    return {}


async def _handle_tools_list(_db: AsyncSession, principal: Principal, _params: dict) -> dict:
    return {
        "tools": [
            {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}
            for tool in aitools.tools_for_role(principal.role)
        ],
    }


async def _handle_tools_call(db: AsyncSession, principal: Principal, params: dict) -> dict:
    name = params.get("name")
    if not isinstance(name, str):
        raise _ParamsError("Missing tool name.")
    arguments = params.get("arguments") or {}
    try:
        result = await aitools.call_tool(db, name, arguments, principal.role)
    except aitools.ToolNotFoundError as exc:
        raise _ParamsError(str(exc)) from exc
    except aitools.ToolError as exc:
        # Tool-level failures are results, not protocol errors, so the model can read them.
        return {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
    return {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
        "structuredContent": result,
    }


_RESOURCES = [
    {
        "uri": "spoolman://inventory-summary",
        "name": "Inventory summary",
        "description": "Current inventory overview: spools, remaining weight, materials, locations.",
        "mimeType": "text/markdown",
    },
    {
        "uri": "spoolman://low-stock",
        "name": "Low stock report",
        "description": "Filaments at or below their low-stock threshold.",
        "mimeType": "text/markdown",
    },
]


def _render_inventory_markdown(stats: dict) -> str:
    lines = [
        "# Spoolman inventory summary",
        "",
        f"- Active spools: {stats['active_spools']}",
        f"- Filament types: {stats['filaments']}",
        f"- Vendors: {stats['vendors']}",
        f"- Total remaining filament: {stats['total_remaining_weight_g']} g",
        "",
        "## By material",
    ]
    lines.extend(
        f"- {entry['material']}: {entry['spools']} spools, {entry['remaining_weight_g']} g remaining"
        for entry in stats["by_material"]
    )
    lines.extend(["", "## By location"])
    lines.extend(f"- {entry['location']}: {entry['spools']} spools" for entry in stats["by_location"])
    return "\n".join(lines)


def _render_low_stock_markdown(report: dict) -> str:
    lines = [
        "# Spoolman low-stock report",
        "",
        f"Fallback threshold: {report['fallback_threshold_g']} g. Filaments flagged: {report['low_stock_count']}.",
        "",
    ]
    if not report["filaments"]:
        lines.append("Nothing is low on stock.")
    lines.extend(
        f"- {entry['vendor'] or 'Unknown vendor'} {entry['name'] or 'unnamed'} ({entry['material'] or '?'}): "
        f"{entry['remaining_weight_g']} g remaining of {entry['threshold_g']} g threshold "
        f"across {entry['active_spool_count']} spools"
        for entry in report["filaments"]
    )
    return "\n".join(lines)


async def _handle_resources_list(_db: AsyncSession, _principal: Principal, _params: dict) -> dict:
    return {"resources": _RESOURCES}


async def _handle_resources_read(db: AsyncSession, _principal: Principal, params: dict) -> dict:
    uri = params.get("uri")
    if uri == "spoolman://inventory-summary":
        text = _render_inventory_markdown(await aitools.call_tool(db, "get_inventory_stats", {}, "admin"))
    elif uri == "spoolman://low-stock":
        text = _render_low_stock_markdown(await aitools.call_tool(db, "get_low_stock", {}, "admin"))
    else:
        raise _ResourceNotFoundError(f"Resource not found: {uri}")
    return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}


_PROMPTS = [
    {
        "name": "restock_advisor",
        "description": "Review the current low-stock situation and advise what to reorder.",
        "arguments": [],
    },
]


async def _handle_prompts_list(_db: AsyncSession, _principal: Principal, _params: dict) -> dict:
    return {"prompts": _PROMPTS}


async def _handle_prompts_get(db: AsyncSession, _principal: Principal, params: dict) -> dict:
    if params.get("name") != "restock_advisor":
        raise _ParamsError(f"Unknown prompt: {params.get('name')}")
    report = await aitools.call_tool(db, "get_low_stock", {}, "admin")
    text = (
        "You are helping the owner of a 3D-printing filament inventory decide what to reorder.\n"
        "Below is the live low-stock report from Spoolman. For each flagged filament, consider how "
        "critical the material is, suggest a reorder quantity, and point out consolidation "
        "opportunities (same material/color from one vendor). If nothing is flagged, say so.\n\n"
        f"{_render_low_stock_markdown(report)}"
    )
    return {
        "description": "Restock advice based on the live low-stock report.",
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }


class _ParamsError(Exception):
    pass


class _ResourceNotFoundError(Exception):
    pass


_METHODS = {
    "initialize": _handle_initialize,
    "ping": _handle_ping,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
    "resources/list": _handle_resources_list,
    "resources/read": _handle_resources_read,
    "prompts/list": _handle_prompts_list,
    "prompts/get": _handle_prompts_get,
}


async def _dispatch(db: AsyncSession, principal: Principal, message: dict) -> dict | None:  # noqa: PLR0911
    """Handle one JSON-RPC message; return the response object, or None for notifications."""
    method = message.get("method")
    msg_id = message.get("id")
    is_notification = "id" not in message

    if not isinstance(method, str):
        if is_notification or "result" in message or "error" in message:
            # A client response (we never send requests, so nothing to correlate) — ignore.
            return None
        return _rpc_error(msg_id, _INVALID_REQUEST, "Missing method.")

    if is_notification:
        # notifications/initialized and friends: accepted, nothing to answer.
        return None

    handler = _METHODS.get(method)
    if handler is None:
        return _rpc_error(msg_id, _METHOD_NOT_FOUND, f"Method not found: {method}")

    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(msg_id, _INVALID_PARAMS, "Params must be an object.")
    try:
        return _rpc_result(msg_id, await handler(db, principal, params))
    except _ParamsError as exc:
        return _rpc_error(msg_id, _INVALID_PARAMS, str(exc))
    except _ResourceNotFoundError as exc:
        return _rpc_error(msg_id, _RESOURCE_NOT_FOUND, str(exc))
    except Exception:
        logger.exception("MCP method %s failed", method)
        return _rpc_error(msg_id, _INTERNAL_ERROR, "Internal error.")


@router.post("/mcp", include_in_schema=False)
async def mcp_endpoint(  # noqa: PLR0911
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Serve the MCP streamable-HTTP endpoint (single JSON-RPC message per POST)."""
    if not await _mcp_enabled(db):
        return JSONResponse(status_code=404, content={"message": "The MCP endpoint is disabled."})
    if _origin_mismatch(request):
        return JSONResponse(status_code=403, content={"message": "Origin not allowed."})

    principal = resolve_principal_for_token(_bearer_token(request))
    if principal is None:
        return JSONResponse(
            status_code=401,
            content={"message": "Authentication required."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        message = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content=_rpc_error(None, _PARSE_ERROR, "Parse error."))
    if isinstance(message, list):
        return JSONResponse(
            status_code=400,
            content=_rpc_error(None, _INVALID_REQUEST, "Batching is not supported."),
        )
    if not isinstance(message, dict):
        return JSONResponse(status_code=400, content=_rpc_error(None, _INVALID_REQUEST, "Invalid request."))

    response = await _dispatch(db, principal, message)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(status_code=200, content=response)


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
async def mcp_unsupported() -> Response:
    """No server-initiated SSE stream and no sessions: the spec's prescribed answer is 405."""
    return Response(status_code=405, headers={"Allow": "POST"})
