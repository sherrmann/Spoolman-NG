"""The curated agent tool layer (#362), assembled from per-domain modules.

One tool surface, two consumers: the in-app chat agent (:mod:`spoolman.aichat`) and the MCP
server (:mod:`spoolman.mcp_server`). Each tool is a thin, *curated* wrapper over the same
database functions the REST API uses — never raw SQL, never a field the UI wouldn't let a
user touch — so the agent can only do things a person could do in the web client.

Domain modules each publish ``READ_TOOLS``/``WRITE_TOOLS``; this module merges them into the
single registry both consumers read. Adding a domain means adding a module and one line here.
"""

from spoolman.ai_tools import catalog, filaments, inventory, orders, spools, stats
from spoolman.ai_tools.base import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ConfirmCard,
    ExecutionResult,
    ReadTool,
    ToolContext,
    ToolError,
    WriteTool,
    arg_bool,
    arg_float,
    arg_int,
    arg_limit,
    clean_str,
    combined_name,
    echo_spool_filters,
    get_spool,
    initial_weight,
    low_stock_fallback_g,
    optional_float,
    remaining_weight,
    require_write,
    spool_brief,
)

_MODULES = (catalog, filaments, inventory, orders, spools, stats)

READ_TOOLS: dict[str, ReadTool] = {name: tool for module in _MODULES for name, tool in module.READ_TOOLS.items()}
WRITE_TOOLS: dict[str, WriteTool] = {name: tool for module in _MODULES for name, tool in module.WRITE_TOOLS.items()}

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "READ_TOOLS",
    "WRITE_TOOLS",
    "ConfirmCard",
    "ExecutionResult",
    "ReadTool",
    "ToolContext",
    "ToolError",
    "WriteTool",
    "arg_bool",
    "arg_float",
    "arg_int",
    "arg_limit",
    "clean_str",
    "combined_name",
    "echo_spool_filters",
    "get_spool",
    "get_tool",
    "initial_weight",
    "is_write_tool",
    "low_stock_fallback_g",
    "optional_float",
    "remaining_weight",
    "require_write",
    "spool_brief",
    "tool_schemas",
]


def is_write_tool(name: str) -> bool:
    """Whether a tool name refers to a mutating tool."""
    return name in WRITE_TOOLS


def get_tool(name: str) -> ReadTool | WriteTool | None:
    """Look a tool up by name across both registries, or None if unknown."""
    return READ_TOOLS.get(name) or WRITE_TOOLS.get(name)


def _openai_schema(tool: ReadTool | WriteTool) -> dict:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
    }


def tool_schemas(*, can_write: bool) -> list[dict]:
    """Return the OpenAI ``tools`` array offered to the model for this principal.

    Read tools always; model-facing write tools only when the principal may write. A
    read-only caller therefore never even sees a mutation exists. Undo-only primitives
    (``model_facing=False``) are offered to nobody.
    """
    schemas = [_openai_schema(tool) for tool in READ_TOOLS.values()]
    if can_write:
        schemas.extend(_openai_schema(tool) for tool in WRITE_TOOLS.values() if tool.model_facing)
    return schemas
