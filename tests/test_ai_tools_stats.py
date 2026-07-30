"""Unit tests for the usage-statistics tool's pure argument handling and aggregation."""

from datetime import datetime

import pytest

from spoolman.ai_tools import stats
from spoolman.ai_tools.base import ToolContext, ToolError
from spoolman.database.stats import UsageBucket


def test_bucket_defaults_to_month() -> None:
    assert stats.parse_bucket({}) is UsageBucket.month


@pytest.mark.parametrize("raw", ["day", "WEEK", " month ", "year"])
def test_bucket_accepts_the_casings_models_emit(raw: str) -> None:
    assert stats.parse_bucket({"bucket": raw}) is UsageBucket(raw.strip().lower())


def test_bucket_rejects_junk_as_a_tool_error() -> None:
    with pytest.raises(ToolError, match="bucket"):
        stats.parse_bucket({"bucket": "fortnight"})


def test_dates_parse_iso_and_tolerate_a_trailing_z() -> None:
    # parse_date's contract is a naive datetime (tzinfo stripped), so the expected values here
    # are deliberately naive too, hence the noqa: DTZ001 (ruff wants tz-aware datetime() calls).
    expected_date = datetime(2026, 1, 31)  # noqa: DTZ001
    expected_datetime = datetime(2026, 1, 31, 10, 0)  # noqa: DTZ001
    assert stats.parse_date({"from_date": "2026-01-31"}, "from_date") == expected_date
    assert stats.parse_date({"from_date": "2026-01-31T10:00:00Z"}, "from_date") == expected_datetime


def test_an_offset_date_is_converted_to_utc_not_merely_stripped() -> None:
    # Event times are stored naive-UTC; dropping the offset would shift the window five hours.
    expected = datetime(2026, 1, 31, 5, 0)  # noqa: DTZ001
    assert stats.parse_date({"from_date": "2026-01-31T00:00:00-05:00"}, "from_date") == expected


def test_absent_date_stays_absent_and_junk_errors() -> None:
    assert stats.parse_date({}, "from_date") is None
    with pytest.raises(ToolError, match="from_date"):
        stats.parse_date({"from_date": "last tuesday"}, "from_date")


# --- _run_get_usage_stats: aggregation on top of a stubbed DB layer ----------------
#
# stats_db.usage_stats is monkeypatched rather than exercised through a real DB session: the
# behaviour under test here is entirely _run_get_usage_stats's own post-processing (truncation,
# the empty-result shape), not the SQL aggregation itself -- that's stats_db's own contract,
# covered separately (see tests/integration/test_ai_chat_endpoints.py).


def _tool_context() -> ToolContext:
    """Build a ToolContext whose db is never touched: usage_stats is stubbed out below."""
    return ToolContext(db=None, can_write=False)


async def test_usage_stats_truncates_to_the_most_recent_max_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    # stats_db.usage_stats returns buckets in chronological (ascending) order; MAX_BUCKETS must
    # keep the tail of that list (the newest buckets), not the head (the oldest) -- a "the periods
    # got cut off" bug that a fixture already in truncated order could never catch.
    extra = 5
    rows = [
        {"period": f"period-{index:03d}", "consumed_weight": float(index), "cost": float(index)}
        for index in range(stats.MAX_BUCKETS + extra)
    ]

    async def fake_usage_stats(*_args: object, **_kwargs: object) -> list[dict]:
        return rows

    monkeypatch.setattr(stats.stats_db, "usage_stats", fake_usage_stats)

    result = await stats._run_get_usage_stats(_tool_context(), {"bucket": "month"})  # noqa: SLF001

    kept = rows[-stats.MAX_BUCKETS :]
    assert result["count"] == stats.MAX_BUCKETS
    assert [period["period"] for period in result["periods"]] == [period["period"] for period in kept]
    # The newest bucket survives and the oldest is dropped -- pinned explicitly so a reversed
    # slice (keeping the oldest buckets instead) fails here, not just on a length check.
    assert result["periods"][0]["period"] == rows[extra]["period"]
    assert result["periods"][-1]["period"] == rows[-1]["period"]
    assert rows[0]["period"] not in {period["period"] for period in result["periods"]}
    assert result["total_consumed_weight_g"] == round(sum(row["consumed_weight"] for row in kept), 1)
    assert result["total_cost"] == round(sum(row["cost"] for row in kept), 2)


async def test_usage_stats_handles_an_empty_result_set(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_usage_stats(*_args: object, **_kwargs: object) -> list[dict]:
        return []

    monkeypatch.setattr(stats.stats_db, "usage_stats", fake_usage_stats)

    result = await stats._run_get_usage_stats(_tool_context(), {})  # noqa: SLF001

    assert result == {
        "bucket": "month",
        "count": 0,
        "total_consumed_weight_g": 0.0,
        "total_cost": 0.0,
        "periods": [],
    }
