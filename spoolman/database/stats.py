"""Historical usage statistics derived from the spool usage-event log (#81).

The event log (#50) persists every used_weight change with a timestamp and signed delta. This module
aggregates those into time buckets (day/week/month/year) for a consumption-and-cost-over-time view.

Bucketing is done in Python rather than with dialect-specific date SQL, so it is portable across all
four supported databases by construction; the SQL itself is a plain JOIN + range filter.
"""

from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import models

# Only real consumption events count toward usage stats; administrative resets/updates/transfers are
# excluded so a "reset usage" doesn't read as a huge negative consumption spike.
_CONSUMPTION_EVENT_TYPES = ("use", "measure")


class UsageBucket(Enum):
    """Granularity of the usage-stats time buckets."""

    day = "day"
    week = "week"
    month = "month"
    year = "year"


def bucket_key(time: datetime, bucket: UsageBucket) -> str:
    """Return the period label a timestamp falls into, for the given granularity.

    Pure and dialect-independent: day -> YYYY-MM-DD, week -> the Monday's YYYY-MM-DD, month ->
    YYYY-MM, year -> YYYY.
    """
    if bucket == UsageBucket.year:
        return time.strftime("%Y")
    if bucket == UsageBucket.month:
        return time.strftime("%Y-%m")
    if bucket == UsageBucket.week:
        monday = time - timedelta(days=time.weekday())
        return monday.strftime("%Y-%m-%d")
    return time.strftime("%Y-%m-%d")


async def usage_stats(
    db: AsyncSession,
    *,
    bucket: UsageBucket,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[dict]:
    """Aggregate filament consumption (grams) and cost into time buckets (#81).

    consumed_weight is the net sum of used_weight deltas for consumption events in the bucket. cost is
    that weight priced at each spool's price-per-gram (effective price over its net weight), skipped
    when the price or net weight is unknown. The effective price is the spool's own price falling back
    to the filament price, matching how the client values a spool. Buckets are returned in
    chronological order.
    """
    stmt = (
        select(
            models.SpoolUsageEvent.time,
            models.SpoolUsageEvent.delta,
            models.Spool.price,
            models.Spool.initial_weight,
            models.Filament.price,
            models.Filament.weight,
        )
        .join(models.Spool, models.SpoolUsageEvent.spool_id == models.Spool.id)
        .join(models.Filament, models.Spool.filament_id == models.Filament.id)
        .where(models.SpoolUsageEvent.event_type.in_(_CONSUMPTION_EVENT_TYPES))
    )
    if from_date is not None:
        stmt = stmt.where(models.SpoolUsageEvent.time >= from_date)
    if to_date is not None:
        stmt = stmt.where(models.SpoolUsageEvent.time < to_date)

    buckets: dict[str, dict] = {}
    for time, delta, spool_price, initial_weight, filament_price, filament_weight in (await db.execute(stmt)).all():
        key = bucket_key(time, bucket)
        agg = buckets.setdefault(key, {"period": key, "consumed_weight": 0.0, "cost": 0.0})
        agg["consumed_weight"] += delta
        # Effective price = spool override, else filament price (mirrors client show.tsx / list.tsx).
        price = spool_price if spool_price is not None else filament_price
        net_weight = initial_weight if initial_weight is not None else filament_weight
        if price is not None and net_weight:
            agg["cost"] += delta * (price / net_weight)

    return [buckets[key] for key in sorted(buckets)]
