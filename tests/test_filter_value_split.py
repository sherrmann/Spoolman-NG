"""Unit tests for split_filter_values, the comma splitter behind every string filter.

A filter value is a comma-separated list, and a part wrapped in double quotes is an exact
match. Splitting on every comma broke a quoted value that itself contains one: a location
called "Top shelf, Rack 3" became the parts `"Top shelf` and ` Rack 3"`, neither of which
matched, so its dashboard card and filter chip showed no spools (upstream issue 1169).
"""

import time

import pytest

from spoolman.database.utils import split_filter_values


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # A comma inside a quoted part belongs to the value.
        ('"Top shelf, Rack 3"', ['"Top shelf, Rack 3"']),
        ('"Top shelf, Rack 3","Bin 2"', ['"Top shelf, Rack 3"', '"Bin 2"']),
        ('PLA,"Top shelf, Rack 3"', ["PLA", '"Top shelf, Rack 3"']),
        ('"a, b, c"', ['"a, b, c"']),
    ],
)
def test_quoted_part_keeps_its_commas(value: str, expected: list[str]):
    assert split_filter_values(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        ",",
        "PLA",
        "PLA,PETG",
        "PLA,,PETG",
        "PLA,",
        ',"PLA"',
        '"PLA"',
        '"PLA","PETG"',
        '""',
        '"',
        # Unbalanced quotes fall back to a plain split, exactly as before.
        '"Top shelf, Rack 3',
        'Top shelf, Rack 3"',
        # A quote that doesn't start a part is literal text, not grouping.
        'a"b,c"d',
        # Quotes inside a quoted part that aren't followed by a comma or the end stay in it.
        '"a"b",c',
    ],
)
def test_matches_a_plain_split_when_no_quoted_part_holds_a_comma(value: str):
    """Every value the old splitter handled correctly still splits the same way."""
    assert split_filter_values(value) == value.split(",")


def test_unclosed_quotes_split_in_linear_time():
    """A value of many unclosed quoted parts must not rescan the rest of the string per part."""
    value = '"a,' * 20000

    started = time.perf_counter()
    parts = split_filter_values(value)
    elapsed = time.perf_counter() - started

    assert parts == value.split(",")
    # Quadratic took about 2.4 s for a quarter of this size; linear takes milliseconds.
    assert elapsed < 0.5
