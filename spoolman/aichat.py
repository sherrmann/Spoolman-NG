"""In-app chat agent loop (#362).

The agent consumes the same curated tool layer as the MCP server (``spoolman.aitools``)
— one tool surface, two consumers. The loop is stateless: the client holds the whole
transcript (OpenAI wire format) and sends it with every request; the server stacks a
fresh system prompt on top, so the system prompt can never be smuggled in or replayed
stale.

Read-only tools execute immediately inside the loop. Mutating tools STOP the loop and
surface a pending action the user must confirm in the UI — writes never happen
silently (#362 hard requirement). Readonly principals never even see the write tools:
they are absent from the tool list sent to the model, and ``aitools.call_tool``
re-checks the role on execution as defense in depth.
"""

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import aitools
from spoolman.ai import AIConfig, AIRequestError, chat_completion_message

logger = logging.getLogger(__name__)

#: Upper bound on model round-trips per request — a runaway backstop, not a target.
MAX_STEPS = 6
#: Bounds on the client-supplied transcript, to keep abuse and accidents cheap.
MAX_MESSAGES = 200
MAX_TRANSCRIPT_CHARS = 400_000
MAX_TOOL_CALLS_PER_TURN = 8

STOP_REASON_STEP_BUDGET = "step_budget"


class ChatProtocolError(Exception):
    """The client-supplied transcript or pending-action resolution is malformed (HTTP 400)."""


@dataclass
class ToolEvent:
    """One tool execution, for display in the chat stream."""

    tool: str
    detail: str | None = None


@dataclass
class PendingAction:
    """A mutating tool call awaiting user confirmation. Nothing has been executed."""

    id: str
    tool: str
    arguments: dict


@dataclass
class ChatOutcome:
    """The result of one /ai/chat round trip."""

    messages: list[dict]
    reply: str | None = None
    events: list[ToolEvent] = field(default_factory=list)
    pending: PendingAction | None = None
    stopped_reason: str | None = None


def build_system_prompt(*, locale: str | None, page: str | None) -> str:
    """Compose the system prompt for one request."""
    lines = [
        "You are the assistant built into Spoolman, a 3D-printing filament inventory manager.",
        "Answer questions about the user's spools, filaments and stock using the provided tools;",
        "never invent inventory data - if a tool returns nothing, say so.",
        "Amounts are grams and millimeters. Be concise and factual.",
        "Do not use emojis.",
        "Mutating tools are executed only after the user confirms them in the interface,",
        "so propose a mutating tool call directly when the user asks for a change -",
        "do not ask for permission in text first.",
    ]
    if locale:
        lines.append(f"Reply in the language of the locale '{locale}'.")
    if page:
        lines.append(f"The user is currently on the '{page}' page of the Spoolman web interface.")
    return " ".join(lines)


def tools_payload(role: str) -> list[dict]:
    """Build the OpenAI tools array for a principal: readonly roles get read tools only."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in aitools.tools_for_role(role)
    ]


# --- Transcript hygiene ------------------------------------------------------------


def _sanitize_tool_calls(raw: object) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_TOOL_CALLS_PER_TURN:
        raise ChatProtocolError("Malformed assistant tool_calls.")
    calls = []
    for call in raw:
        if not isinstance(call, dict) or not isinstance(call.get("id"), str):
            raise ChatProtocolError("Malformed assistant tool_calls.")
        function = call.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ChatProtocolError("Malformed assistant tool_calls.")
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        if not isinstance(arguments, str):
            raise ChatProtocolError("Malformed assistant tool_calls.")
        calls.append(
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": function["name"], "arguments": arguments},
            },
        )
    return calls


def _sanitize_message(message: object) -> dict:
    if not isinstance(message, dict):
        raise ChatProtocolError("Transcript entries must be objects.")
    role = message.get("role")
    content = message.get("content")
    if role == "user":
        if not isinstance(content, str) or not content.strip():
            raise ChatProtocolError("User messages must carry text content.")
        return {"role": "user", "content": content}
    if role == "assistant":
        clean: dict = {"role": "assistant", "content": content if isinstance(content, str) else None}
        if message.get("tool_calls"):
            clean["tool_calls"] = _sanitize_tool_calls(message["tool_calls"])
        return clean
    if role == "tool":
        if not isinstance(message.get("tool_call_id"), str) or not isinstance(content, str):
            raise ChatProtocolError("Tool messages must carry tool_call_id and text content.")
        return {"role": "tool", "tool_call_id": message["tool_call_id"], "content": content}
    # A "system" role here would be prompt smuggling; anything else is garbage.
    raise ChatProtocolError(f"Unsupported transcript role: {role!r}.")


def sanitize_transcript(messages: object) -> list[dict]:
    """Validate and normalize the client-held transcript; reject anything off-protocol."""
    if not isinstance(messages, list) or not messages:
        raise ChatProtocolError("The transcript must be a non-empty list of messages.")
    if len(messages) > MAX_MESSAGES:
        raise ChatProtocolError(f"The transcript exceeds {MAX_MESSAGES} messages; start a new conversation.")
    clean = [_sanitize_message(message) for message in messages]
    total = sum(len(json.dumps(message)) for message in clean)
    if total > MAX_TRANSCRIPT_CHARS:
        raise ChatProtocolError("The transcript is too large; start a new conversation.")
    return clean


def _normalize_assistant(message: dict) -> dict:
    """Reduce a provider assistant message to the keys the transcript keeps."""
    content = message.get("content")
    clean: dict = {"role": "assistant", "content": content if isinstance(content, str) else None}
    if message.get("tool_calls"):
        try:
            clean["tool_calls"] = _sanitize_tool_calls(message["tool_calls"])
        except ChatProtocolError as exc:
            raise AIRequestError("The AI endpoint returned a malformed tool call.") from exc
    return clean


# --- Tool execution ----------------------------------------------------------------


def _summarize(result: dict) -> str | None:
    """Build a short, language-neutral detail line for the chat stream's tool events."""
    for key in ("returned", "low_stock_count", "active_spools"):
        if key in result:
            return f"{key}={result[key]}"
    spool = result.get("spool")
    if isinstance(spool, dict) and "id" in spool:
        return f"spool #{spool['id']}"
    return None


async def _execute_tool(db: AsyncSession, name: str, arguments: dict, role: str) -> tuple[str, str | None, bool]:
    """Run one tool; failures become error results the model can read and correct."""
    try:
        result = await aitools.call_tool(db, name, arguments, role)
    except (aitools.ToolError, aitools.ToolNotFoundError) as exc:
        return json.dumps({"error": str(exc)}), None, False
    return json.dumps(result), _summarize(result), True


def _tool_error(call_id: str, message: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps({"error": message})}


def _parse_arguments(raw: str) -> dict | None:
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    return arguments if isinstance(arguments, dict) else None


def _unresolved_calls(transcript: list[dict]) -> tuple[dict | None, list[dict]]:
    """Return the last assistant message and its tool calls that lack a tool result."""
    last_assistant = None
    for message in reversed(transcript):
        if message["role"] == "assistant":
            last_assistant = message
            break
    if last_assistant is None or not last_assistant.get("tool_calls"):
        return last_assistant, []
    answered = {message["tool_call_id"] for message in transcript if message["role"] == "tool"}
    return last_assistant, [call for call in last_assistant["tool_calls"] if call["id"] not in answered]


async def _drain_tool_calls(
    db: AsyncSession,
    transcript: list[dict],
    role: str,
    events: list[ToolEvent],
) -> PendingAction | None:
    """Execute outstanding tool calls in order; stop at the first mutating one.

    Read-only calls run immediately and append their results. A mutating call is
    returned as a PendingAction without executing anything — the client shows a
    confirm card and resolves it on the next request. Unknown/hidden tools and
    unparseable arguments become error results so the model can correct itself.
    """
    _, unresolved = _unresolved_calls(transcript)
    for call in unresolved:
        name = call["function"]["name"]
        arguments = _parse_arguments(call["function"]["arguments"])
        if arguments is None:
            transcript.append(_tool_error(call["id"], "Tool arguments were not valid JSON."))
            continue
        tool = aitools.visible_tool(name, role)
        if tool is not None and not tool.read_only:
            return PendingAction(id=call["id"], tool=name, arguments=arguments)
        content, detail, ok = await _execute_tool(db, name, arguments, role)
        transcript.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        if ok:
            events.append(ToolEvent(tool=name, detail=detail))
    return None


async def _resolve_pending(
    db: AsyncSession,
    transcript: list[dict],
    call_id: str,
    *,
    approved: bool,
    role: str,
    events: list[ToolEvent],
) -> None:
    """Execute or decline a previously returned pending action."""
    _, unresolved = _unresolved_calls(transcript)
    call = next((entry for entry in unresolved if entry["id"] == call_id), None)
    if call is None:
        raise ChatProtocolError("The resolved action is not pending in this conversation.")
    if not approved:
        transcript.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({"declined": True, "message": "The user declined this action."}),
            },
        )
        return
    name = call["function"]["name"]
    arguments = _parse_arguments(call["function"]["arguments"]) or {}
    content, detail, ok = await _execute_tool(db, name, arguments, role)
    transcript.append({"role": "tool", "tool_call_id": call_id, "content": content})
    if ok:
        events.append(ToolEvent(tool=name, detail=detail))


# --- The loop ----------------------------------------------------------------------


async def run_chat(
    db: AsyncSession,
    config: AIConfig,
    *,
    messages: list[dict],
    role: str,
    locale: str | None = None,
    page: str | None = None,
    resolve_id: str | None = None,
    resolve_approved: bool = False,
) -> ChatOutcome:
    """Run the agent loop for one request and return the updated transcript.

    Raises ChatProtocolError for malformed client input (HTTP 400) and AIRequestError
    for provider trouble (HTTP 502). Database work happens only through the curated
    tool layer, which enforces role gating on every call.
    """
    transcript = sanitize_transcript(messages)
    events: list[ToolEvent] = []

    if resolve_id is not None:
        await _resolve_pending(db, transcript, resolve_id, approved=resolve_approved, role=role, events=events)

    # Outstanding calls from the last assistant turn (reads run now; a second write
    # in the same turn surfaces as the next pending action before any model call).
    pending = await _drain_tool_calls(db, transcript, role, events)
    if pending is not None:
        return ChatOutcome(messages=transcript, events=events, pending=pending)

    system = {"role": "system", "content": build_system_prompt(locale=locale, page=page)}
    tools = tools_payload(role)
    for _ in range(MAX_STEPS):
        provider_message = await chat_completion_message(config, [system, *transcript], tools=tools)
        assistant = _normalize_assistant(provider_message)
        transcript.append(assistant)
        if not assistant.get("tool_calls"):
            return ChatOutcome(messages=transcript, reply=assistant.get("content") or "", events=events)
        pending = await _drain_tool_calls(db, transcript, role, events)
        if pending is not None:
            return ChatOutcome(messages=transcript, events=events, pending=pending)

    # Step budget exhausted: return the transcript as-is; the client renders a
    # localized notice and the conversation can simply continue on the next send.
    return ChatOutcome(messages=transcript, events=events, stopped_reason=STOP_REASON_STEP_BUDGET)
