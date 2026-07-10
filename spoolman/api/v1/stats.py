"""Historical usage-statistics endpoints (#81)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import stats
from spoolman.database.database import get_db_session
from spoolman.database.stats import UsageBucket

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
)

# ruff: noqa: D103


class UsageStat(BaseModel):
    period: str = Field(
        description="The time bucket, labelled by its start: a date (YYYY-MM-DD) for day/week, a "
        "month (YYYY-MM), or a year (YYYY).",
        examples=["2026-07"],
    )
    consumed_weight: float = Field(
        description="Net filament consumed in this period, in grams (sum of used_weight deltas).",
        examples=[1234.5],
    )
    cost: float = Field(
        description="Estimated cost of the consumed filament in the system currency, priced at each "
        "spool's price per gram. 0 where the price or net weight is unknown.",
        examples=[24.69],
    )


@router.get(
    "/usage",
    name="Filament usage over time",
    description=(
        "Aggregate filament consumption and cost into time buckets from the spool usage-event log "
        "(#81 / #50). Only real consumption events (use, measure) are counted."
    ),
)
async def usage(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    bucket: Annotated[
        UsageBucket,
        Query(description="Time-bucket granularity."),
    ] = UsageBucket.month,
    from_date: Annotated[
        datetime | None,
        Query(alias="from", description="Only include events at or after this time (inclusive)."),
    ] = None,
    to_date: Annotated[
        datetime | None,
        Query(alias="to", description="Only include events before this time (exclusive)."),
    ] = None,
) -> list[UsageStat]:
    rows = await stats.usage_stats(db, bucket=bucket, from_date=from_date, to_date=to_date)
    return [UsageStat(**row) for row in rows]
