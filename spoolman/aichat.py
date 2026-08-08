"""The in-app chat agent loop (#362).

A stateless, server-side agent that shares the curated tool layer (spoolman.ai_tools)
with the future MCP server — one tool surface, two consumers. Statelessness is the whole
trick that lets a confirm-card pause work over one-way Server-Sent Events: the full
transcript (including assistant ``tool_calls`` turns and ``tool`` results) lives on the
client and is round-tripped on every request, so there is no session to hold between the
"here is what I'm about to change" and the user's "yes, do it".

One request drives the loop until it reaches a natural stopping point and streams the
events it produced:

* ``tool``     — a read tool ran (shown for transparency; carries deep-link filters).
* ``confirm``  — the model wants to mutate; the stream ends carrying the pending
                 transcript plus before/after confirm-cards. The client resumes with
                 ``decision: "confirm"`` or ``"cancel"``.
* ``executed`` — confirmed writes ran; each card carries an ``undo`` descriptor.
* ``cancelled``— the pending writes were declined.
* ``message``  — the final assistant answer.
* ``error``    — a user-safe failure.
* ``done``     — always the last event.

Guardrails that are the server's job, not the model's: the client-supplied transcript is
sanitised (any ``system`` role is dropped and replaced with ours), writes are re-gated by
``can_write`` at execution time regardless of what the transcript claims, and the loop is
capped so a misbehaving model can't spin forever.
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from spoolman import ai, ai_tools
from spoolman.ai_tools import ToolContext, ToolError

logger = logging.getLogger(__name__)

#: Bounds so one turn can't loop or grow without limit.
_MAX_ITERATIONS = 6
_MAX_CLIENT_MESSAGES = 40
_MAX_CONTENT_CHARS = 8000
_MAX_CONTEXT_CHARS = 200

_FALLBACK = "I wasn't able to finish that in a reasonable number of steps. Could you rephrase or narrow it down?"


def _system_prompt(*, context: str | None, locale: str, can_write: bool) -> str:
    """Build the system message: persona, guardrails, locale, page context, write posture."""
    lines = [
        "You are Spoolman's built-in assistant. Spoolman manages a 3D-printing filament inventory: "
        "filament types and the physical spools of them the user owns, with weights, locations and usage.",
        "Answer using ONLY the tools provided and the data they return. Never invent spool or filament "
        "IDs, quantities, materials, or locations. If the tools return nothing, say so plainly.",
        "When reporting quantities, give concrete per-spool numbers and the total, with grams.",
        "You may give advisory answers (e.g. which materials suit outdoor use, what to reorder) from the "
        "filament data the tools return combined with general 3D-printing knowledge.",
        f"Reply in the user's language (locale: {locale}). Do not use any emoji.",
    ]
    if context:
        lines.append(f"The user is currently viewing: {context}.")
    if can_write:
        # The interface already gates every write behind a confirm-card the user has to click, so a
        # model that also asks "shall I go ahead?" in prose costs the user a turn and confirms
        # nothing extra. The old wording ("only applied after the user confirms them in the
        # interface") described that gate without saying what the model should therefore do, and the
        # observed behaviour was three turns of asking before any card appeared -- the same failure
        # the eval measured, where the dominant error was declining to call any tool at all. The
        # safety property that matters (do not touch things the user did not ask about) is kept, and
        # is now paired with the never-substitute rule below rather than with a prose round-trip.
        lines.append(
            "Changes (creating, updating, deleting, consuming) are applied only after the user clicks "
            "Confirm on a card the interface shows them, so that card IS the confirmation: call the write "
            "tool directly with the intended change instead of asking the user to confirm in chat. Do not "
            "claim a change has happened until a tool result confirms it. Only ever change or delete the "
            "records the user actually asked about.",
        )
        lines.append(
            "If the user names a kind of record (order, spool, filament, location, vendor) and no tool "
            "acts on that kind, say so plainly. Never act on a different kind of record instead.",
        )
        lines.append(
            "Never invent a filament's density or diameter. Call catalog_lookup for real values, or ask "
            "the user. Prefer arrive_order over creating spools by hand when an order arrives, and check "
            "find_vendors or find_locations before creating a vendor or location that may already exist.",
        )
    else:
        lines.append("This user has read-only access. You can answer questions but cannot make any changes.")
    return "\n".join(lines)


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _coerce_content(value: object) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return text[:_MAX_CONTENT_CHARS]


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Keep only well-formed user/assistant/tool turns, preserving tool-call round-trips.

    Any ``system`` turn is dropped — the server owns the system prompt. Assistant turns
    keep their ``tool_calls`` (needed to resume a pending confirm), tool turns keep their
    ``tool_call_id``.
    """
    clean: list[dict] = []
    for raw in messages[-_MAX_CLIENT_MESSAGES:]:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        if role == "user":
            clean.append({"role": "user", "content": _coerce_content(raw.get("content"))})
        elif role == "assistant":
            entry: dict = {"role": "assistant", "content": _coerce_content(raw.get("content"))}
            tool_calls = raw.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                entry["tool_calls"] = tool_calls
                # OpenAI allows (and some servers require) null content on a tool-call turn.
                if not entry["content"]:
                    entry["content"] = None
            clean.append(entry)
        elif role == "tool" and raw.get("tool_call_id"):
            clean.append(
                {"role": "tool", "tool_call_id": raw["tool_call_id"], "content": _coerce_content(raw.get("content"))},
            )
    return clean


def _call_name(call: dict) -> str:
    return str(((call or {}).get("function") or {}).get("name") or "")


def _call_id(call: dict) -> str:
    return str((call or {}).get("id") or "")


def _call_args(call: dict) -> dict:
    """Parse a tool call's arguments (a JSON string per the OpenAI spec) into a dict."""
    raw = ((call or {}).get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _assistant_entry(assistant: dict) -> dict:
    """Normalise a provider assistant message down to the fields we round-trip."""
    entry: dict = {"role": "assistant", "content": assistant.get("content")}
    tool_calls = assistant.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        entry["tool_calls"] = tool_calls
    else:
        entry["content"] = _coerce_content(entry.get("content"))
    return entry


def _tool_result_entry(call: dict, payload: dict) -> dict:
    return {"role": "tool", "tool_call_id": _call_id(call), "content": json.dumps(payload)}


def _read_summary(name: str, result: dict) -> str:  # noqa: PLR0911
    """Return a short human line describing what a read tool found (for the 'tool' event).

    This is the drawer's transparency line: the one place the user can see what the assistant
    actually looked at without opening the raw tool payload. Every READ_TOOLS entry needs a
    branch here that reflects its own result shape -- a bare "Done." tells the user nothing they
    couldn't already infer from the tool name alone, and test_ai_tools.py's
    test_every_read_tool_produces_a_non_default_summary pins that a future read tool can't forget
    to add one.
    """
    if name == "find_spools":
        return f"Found {result.get('count', 0)} spool(s), {result.get('total_remaining_weight_g', 0)} g remaining."
    if name == "find_filaments":
        return f"Listed {result.get('count', 0)} filament(s), {result.get('returned', 0)} shown."
    if name == "get_usage_stats":
        return (
            f"Summed {result.get('count', 0)} {result.get('bucket', 'month')} period(s): "
            f"{result.get('total_consumed_weight_g', 0)} g, {result.get('total_cost', 0)} total cost."
        )
    if name == "find_orders":
        return f"Found {result.get('count', 0)} order(s), {result.get('returned', 0)} shown."
    if name == "find_locations":
        return f"Listed {result.get('count', 0)} location(s)."
    if name == "find_vendors":
        return f"Listed {result.get('count', 0)} vendor(s)."
    if name == "catalog_lookup":
        return f"Found {result.get('count', 0)} catalog match(es)."
    return "Done."


#: Fed back to the model when a tool raises something other than a ToolError. Nothing about
#: the internal failure is exposed — the model just learns the call did not work.
_TOOL_FAILED = "That tool failed unexpectedly. Try again with different arguments."


async def _run_read_call(ctx: ToolContext, call: dict) -> tuple[dict, str]:
    """Execute a read tool call, returning (result-for-model, formatted 'tool' SSE event).

    A failure becomes an error result fed back to the model (so it can recover) rather than
    aborting the turn: ToolError carries its own message, anything unexpected is logged
    server-side and reported generically.
    """
    name = _call_name(call)
    tool = ai_tools.READ_TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool '{name}'."}, _sse("tool", {"name": name, "summary": "Unknown tool."})
    try:
        result = await tool.run(ctx, _call_args(call))
    except ToolError as exc:
        return {"error": str(exc)}, _sse("tool", {"name": name, "summary": str(exc)})
    except Exception:
        logger.exception("Read tool %r raised an unexpected error.", name)
        return {"error": _TOOL_FAILED}, _sse("tool", {"name": name, "summary": _TOOL_FAILED})
    event_data = {"name": name, "summary": _read_summary(name, result)}
    if name == "find_spools" and result.get("filters"):
        event_data["filters"] = result["filters"]
    return result, _sse("tool", event_data)


async def _resolve_pending(ctx: ToolContext, convo: list[dict], *, decision: str | None) -> AsyncIterator[str]:
    """Execute or cancel write tool calls left pending by a previous confirm round.

    Pending = a write tool_call in the last assistant turn with no matching tool result
    yet. On ``confirm`` (and only if the principal may write) each is executed and an
    ``executed`` event is emitted with undo descriptors; otherwise each is answered with a
    cancellation so the model can acknowledge it.
    """
    if not convo or convo[-1].get("role") != "assistant":
        return
    calls = convo[-1].get("tool_calls") or []
    resolved = {m.get("tool_call_id") for m in convo if m.get("role") == "tool"}
    pending = [c for c in calls if ai_tools.is_write_tool(_call_name(c)) and _call_id(c) not in resolved]
    if not pending:
        return

    executed_cards: list[dict] = []
    for call in pending:
        name = _call_name(call)
        if decision == "confirm" and ctx.can_write:
            try:
                result = await ai_tools.WRITE_TOOLS[name].execute(ctx, _call_args(call))
            except ToolError as exc:
                # A commit-level failure (e.g. an IntegrityError raised from inside execute())
                # leaves the shared session needing an explicit rollback; without one, the next
                # pending call in this same confirmed turn would fail with PendingRollbackError
                # instead of running normally. Rolling back here is a no-op when nothing was
                # actually dirtied, so it's safe for the ordinary validation-only ToolError too.
                await ctx.db.rollback()
                convo.append(_tool_result_entry(call, {"error": str(exc)}))
                continue
            except Exception:
                logger.exception("Write tool %r raised an unexpected error during execution.", name)
                await ctx.db.rollback()
                convo.append(_tool_result_entry(call, {"error": _TOOL_FAILED}))
                continue
            convo.append(_tool_result_entry(call, {"ok": True, "summary": result.summary, **result.data}))
            executed_cards.append({"tool": name, "summary": result.summary, "undo": result.undo})
        else:
            reason = "The user cancelled this action." if ctx.can_write else "This user is read-only."
            convo.append(_tool_result_entry(call, {"cancelled": True, "reason": reason}))

    if executed_cards:
        yield _sse("executed", {"cards": executed_cards})
    elif decision != "confirm":
        yield _sse("cancelled", {})


async def _handle_tool_calls(
    ctx: ToolContext,
    convo: list[dict],
    tool_calls: list[dict],
    pending_cards: list[dict],
) -> AsyncIterator[str]:
    """Run read calls (yielding a ``tool`` event each) and preview write calls into cards.

    Read results and preview errors are appended to ``convo`` so the model sees them next
    turn; previewed writes are collected into ``pending_cards`` (their execution waits for
    the user's confirm).
    """
    for call in tool_calls:
        name = _call_name(call)
        if not ai_tools.is_write_tool(name):
            result, event = await _run_read_call(ctx, call)
            convo.append(_tool_result_entry(call, result))
            yield event
            continue
        if not ctx.can_write:
            # A read-only caller is never given write tools; refuse any forged one rather than preview it.
            convo.append(_tool_result_entry(call, {"error": "This user is read-only and cannot make changes."}))
            continue
        tool = ai_tools.WRITE_TOOLS.get(name)
        if tool is None:
            convo.append(_tool_result_entry(call, {"error": f"Unknown tool '{name}'."}))
            continue
        try:
            card = await tool.preview(ctx, _call_args(call))
        except ToolError as exc:
            # Couldn't even preview (e.g. bad ID, missing argument): feed it back so the
            # model recovers instead of losing the turn.
            convo.append(_tool_result_entry(call, {"error": str(exc)}))
            continue
        except Exception:
            logger.exception("Write tool %r raised an unexpected error during preview.", name)
            convo.append(_tool_result_entry(call, {"error": _TOOL_FAILED}))
            continue
        pending_cards.append({"tool_call_id": _call_id(call), **asdict(card)})


async def run_chat(
    *,
    db: AsyncSession,
    config: ai.AIConfig,
    messages: list[dict],
    context: str | None,
    locale: str,
    can_write: bool,
    decision: str | None,
) -> AsyncIterator[str]:
    """Drive one agent turn and yield SSE frames. Always ends with a ``done`` event."""
    ctx = ToolContext(db=db, can_write=can_write)
    convo: list[dict] = [
        {"role": "system", "content": _system_prompt(context=context, locale=locale, can_write=can_write)},
        *_sanitize_messages(messages),
    ]

    try:
        # First, settle anything the previous confirm round left pending.
        async for event in _resolve_pending(ctx, convo, decision=decision):
            yield event

        for _ in range(_MAX_ITERATIONS):
            assistant = await ai.chat_completion_tools(config, convo, tools=ai_tools.tool_schemas(can_write=can_write))
            convo.append(_assistant_entry(assistant))
            tool_calls = [c for c in (assistant.get("tool_calls") or []) if isinstance(c, dict)]

            if not tool_calls:
                yield _sse("message", {"content": _coerce_content(assistant.get("content"))})
                yield _sse("done", {})
                return

            pending_cards: list[dict] = []
            async for event in _handle_tool_calls(ctx, convo, tool_calls, pending_cards):
                yield event
            if pending_cards:
                yield _sse("confirm", {"messages": convo, "cards": pending_cards})
                yield _sse("done", {})
                return
            # Only reads (or preview errors) this round — loop so the model can use them.

        yield _sse("message", {"content": _FALLBACK})
        yield _sse("done", {})
    except ai.AIRequestError as exc:
        yield _sse("error", {"message": str(exc)})
        yield _sse("done", {})
    except Exception:
        logger.exception("Unexpected error in the chat agent loop.")
        yield _sse("error", {"message": "The assistant hit an unexpected error."})
        yield _sse("done", {})
