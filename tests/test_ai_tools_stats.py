"""Unit tests for the usage-statistics tool's pure argument handling."""

from datetime import datetime

import pytest

from spoolman.ai_tools import stats
from spoolman.ai_tools.base import ToolError
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


def test_absent_date_stays_absent_and_junk_errors() -> None:
    assert stats.parse_date({}, "from_date") is None
    with pytest.raises(ToolError, match="from_date"):
        stats.parse_date({"from_date": "last tuesday"}, "from_date")
