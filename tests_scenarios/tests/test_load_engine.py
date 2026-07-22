"""Unit tests for the load engine's percentile math (nearest-rank)."""

from tests_scenarios.assertions.load import percentile


def test_percentile_nearest_rank_on_1_to_100():
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 95.0
    assert percentile(values, 99) == 99.0
    assert percentile(values, 100) == 100.0


def test_percentile_single_value():
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 99) == 42.0


def test_percentile_empty_is_zero():
    assert percentile([], 95) == 0.0


def test_percentile_ignores_input_order():
    assert percentile([3.0, 1.0, 2.0], 100) == 3.0
