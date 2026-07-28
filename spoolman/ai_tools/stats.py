"""Usage-statistics tool: what the user actually consumed, per time bucket.

Wraps the same aggregation the home dashboard's usage chart reads (#81), so "what did I get
through last month" is answered from the spool usage-event log rather than from the model's
imagination.
"""

from datetime import datetime

from spoolman.ai_tools.base import ReadTool, ToolContext, ToolError
from spoolman.database import stats as stats_db
from spoolman.database.stats import UsageBucket

#: Cap on returned buckets, so "by day since forever" can't flood the model's context.
MAX_BUCKETS = 24


def parse_bucket(args: dict) -> UsageBucket:
    """Coerce the 'bucket' argument to a UsageBucket, defaulting to month."""
    raw = args.get("bucket")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return UsageBucket.month
    try:
        return UsageBucket(str(raw).strip().lower())
    except ValueError as exc:
        raise ToolError(f"The 'bucket' argument must be day, week, month or year, got {raw!r}.") from exc


def parse_date(args: dict, key: str) -> datetime | None:
    """Coerce an optional ISO-8601 date/datetime argument to a naive UTC datetime, or None."""
    raw = args.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError(f"The '{key}' argument must be an ISO date like 2026-01-31, got {raw!r}.") from exc
    return parsed.replace(tzinfo=None)


async def _run_get_usage_stats(ctx: ToolContext, args: dict) -> dict:
    """Aggregate consumption and cost into time buckets, newest MAX_BUCKETS retained."""
    bucket = parse_bucket(args)
    rows = await stats_db.usage_stats(
        ctx.db,
        bucket=bucket,
        from_date=parse_date(args, "from_date"),
        to_date=parse_date(args, "to_date"),
    )
    recent = rows[-MAX_BUCKETS:]
    return {
        "bucket": bucket.value,
        "count": len(recent),
        "total_consumed_weight_g": round(sum(row["consumed_weight"] for row in recent), 1),
        "total_cost": round(sum(row["cost"] for row in recent), 2),
        "periods": recent,
    }


READ_TOOLS: dict[str, ReadTool] = {
    "get_usage_stats": ReadTool(
        name="get_usage_stats",
        description=(
            "How much filament the user consumed and what it cost, grouped into time buckets from the "
            "usage log. Use for 'what did I use last month', 'how fast am I going through filament', "
            "and spend questions. Dates are ISO-8601; omit them for all history."
        ),
        parameters={
            "type": "object",
            "properties": {
                "bucket": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year"],
                    "description": "Time-bucket granularity (default month).",
                },
                "from_date": {"type": "string", "description": "Only count usage at or after this ISO date."},
                "to_date": {"type": "string", "description": "Only count usage before this ISO date."},
            },
        },
        run=_run_get_usage_stats,
    ),
}

WRITE_TOOLS: dict = {}
