"""Unit tests for the defensive color_hex normalization on the serialization path (issue #45).

The write-side validators keep new rows clean, but a row poisoned by an older build (a
color stored with a leading '#') must still render instead of 500ing the whole list. These
exercise the pure helpers that Filament.from_db applies on read.
"""

import pytest

from spoolman.api.v1.models import _normalize_stored_color_hex, _normalize_stored_multi_color_hexes


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, None),
        ("", None),
        ("FF0000", "FF0000"),
        ("ff0000", "FF0000"),
        ("#FF000000", "FF000000"),  # the reported poison: 9 chars in, valid 8 out
        ("  #ff8800  ", "FF8800"),
        ("FF00", None),  # too short → drop the colour, don't raise
        ("FF00000000", None),  # too long → drop
        ("GGGGGG", None),  # non-hex → drop
    ],
)
def test_normalize_stored_color_hex(stored: str | None, expected: str | None):
    assert _normalize_stored_color_hex(stored) == expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, None),
        ("#FF0000,#00FF00", "FF0000,00FF00"),
        ("ff0000,00ff00", "FF0000,00FF00"),
        ("FF0000,GARBAGE", "FF0000"),  # keep the salvageable colours
        ("GARBAGE,ZZZ", None),  # nothing salvageable → None
    ],
)
def test_normalize_stored_multi_color_hexes(stored: str | None, expected: str | None):
    assert _normalize_stored_multi_color_hexes(stored) == expected
