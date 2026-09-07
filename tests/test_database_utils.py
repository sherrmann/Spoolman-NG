"""Unit tests for spoolman.database.utils's pure datetime helpers.

Every datetime column in this codebase is stored naive-UTC. ``utc_timezone_naive`` is the single
choke point that normalizes a caller-supplied datetime (naive or offset-aware) into that form
before it hits the ORM, so it must never let the host's local timezone leak into the result.
``utc_now`` is the matching source of "now" for every write and event timestamp (issue #385): it
must produce the same naive-UTC form, never an offset-aware value, on any host.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import time_machine

from spoolman.database.utils import utc_now, utc_timezone_naive

# An arbitrary fixed instant. Pinning the clock gives every ``utc_now`` test an oracle that is
# independent of the helper itself: the expected value is the instant travelled to, spelled naive.
PINNED_INSTANT = datetime(2026, 1, 1, 12, 30, 45, tzinfo=timezone.utc)
PINNED_NAIVE = datetime(2026, 1, 1, 12, 30, 45)  # noqa: DTZ001


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


def test_utc_now_is_naive() -> None:
    assert utc_now().tzinfo is None


def test_utc_now_returns_the_current_utc_instant_as_a_naive_value() -> None:
    with time_machine.travel(PINNED_INSTANT, tick=False):
        assert utc_now() == PINNED_NAIVE


def test_utc_now_does_not_depend_on_the_hosts_timezone(non_utc_host: None) -> None:  # noqa: ARG001
    # On a UTC-5 host a naive ``datetime.now()`` would read 07:30; the helper must still say 12:30,
    # because naive means UTC in this codebase, not local wall-clock time.
    with time_machine.travel(PINNED_INSTANT, tick=False):
        assert utc_now() == PINNED_NAIVE


def test_utc_now_compares_cleanly_with_a_normalised_aware_input() -> None:
    # The failure mode issue #385 guards against: an aware "now" and a naive value read back from
    # the database cannot be compared. Both helpers must land on the same naive form so that
    # ``now - stored`` never raises TypeError.
    with time_machine.travel(PINNED_INSTANT, tick=False):
        now = utc_now()
    stored = utc_timezone_naive(PINNED_INSTANT.astimezone(timezone(timedelta(hours=-5))))
    assert now == stored
    assert now - stored == timedelta(0)
