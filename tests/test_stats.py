"""Unit tests for the pure usage-stats bucketing helper (#81).

bucket_key must be dialect-independent (it's why bucketing happens in Python, not date SQL), so
these lock the period labels for each granularity, including week's Monday snapping and year/month
rollover boundaries.
"""

from datetime import datetime, timezone

import pytest

from spoolman.database.stats import UsageBucket, bucket_key


def dt(*args: int) -> datetime:
    """Return a UTC datetime; the event log stores UTC and bucket_key operates on it directly."""
    return datetime(*args, tzinfo=timezone.utc)


def test_day_bucket_is_the_date():
    assert bucket_key(dt(2026, 7, 10, 13, 37), UsageBucket.day) == "2026-07-10"


def test_month_bucket_drops_the_day():
    assert bucket_key(dt(2026, 7, 10, 13, 37), UsageBucket.month) == "2026-07"


def test_year_bucket_is_the_year():
    assert bucket_key(dt(2026, 7, 10), UsageBucket.year) == "2026"


def test_week_bucket_snaps_to_the_monday():
    # 2026-07-10 is a Friday; its ISO week starts Monday 2026-07-06.
    assert bucket_key(dt(2026, 7, 10), UsageBucket.week) == "2026-07-06"


def test_week_bucket_on_a_monday_is_that_monday():
    assert bucket_key(dt(2026, 7, 6, 23, 59), UsageBucket.week) == "2026-07-06"


def test_week_bucket_on_a_sunday_snaps_back_to_the_prior_monday():
    assert bucket_key(dt(2026, 7, 12, 0, 1), UsageBucket.week) == "2026-07-06"


def test_week_bucket_crosses_a_month_boundary():
    # 2026-03-01 is a Sunday; its week's Monday is in February.
    assert bucket_key(dt(2026, 3, 1), UsageBucket.week) == "2026-02-23"


@pytest.mark.parametrize(
    ("bucket", "expected"),
    [
        (UsageBucket.day, "2025-12-31"),
        (UsageBucket.month, "2025-12"),
        (UsageBucket.year, "2025"),
    ],
)
def test_year_end_boundary(bucket: UsageBucket, expected: str):
    assert bucket_key(dt(2025, 12, 31, 23, 59, 59), bucket) == expected
