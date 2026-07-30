"""Unit tests for spoolman.database.utils's pure datetime helper.

Every datetime column in this codebase is stored naive-UTC. ``utc_timezone_naive`` is the single
choke point that normalizes a caller-supplied datetime (naive or offset-aware) into that form
before it hits the ORM, so it must never let the host's local timezone leak into the result.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from spoolman.database.utils import utc_timezone_naive


@pytest.fixture
def non_utc_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the process's local timezone something other than UTC for the duration of a test.

    A naive input's result must not depend on this at all; that's exactly the bug (naive input
    was run through ``astimezone()``, which treats it as system-local time).
    """
    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/New_York")  # UTC-4/UTC-5, unambiguous if this leaks through
    time.tzset()
    yield
    if original_tz is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", original_tz)
    time.tzset()


def test_naive_input_is_returned_unchanged() -> None:
    # Naive already means UTC in this codebase; nothing should shift.
    naive = datetime(2026, 7, 1, 10, 0, 0)  # noqa: DTZ001
    result = utc_timezone_naive(naive)
    assert result == naive
    assert result.tzinfo is None


def test_offset_aware_input_is_converted_to_utc_before_tzinfo_is_dropped() -> None:
    aware = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    result = utc_timezone_naive(aware)
    assert result == datetime(2026, 7, 1, 15, 0, 0)  # noqa: DTZ001
    assert result.tzinfo is None


def test_utc_offset_input_is_a_no_op_shift(non_utc_host: None) -> None:  # noqa: ARG001
    # An input already carrying +00:00 must come out identical to the naive form, on any host.
    aware_utc = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
    assert utc_timezone_naive(aware_utc) == datetime(2026, 7, 1, 10, 0, 0)  # noqa: DTZ001


def test_naive_result_does_not_depend_on_the_hosts_timezone(non_utc_host: None) -> None:  # noqa: ARG001
    # This is the regression itself: on a host whose local TZ is not UTC, a naive datetime must
    # come back byte-for-byte identical, never shifted by the local UTC offset.
    naive = datetime(2026, 7, 1, 10, 0, 0)  # noqa: DTZ001
    result = utc_timezone_naive(naive)
    assert result == naive
    assert result.tzinfo is None
