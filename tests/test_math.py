"""Unit tests for the pure math helpers in spoolman.math."""

import math

import pytest

from spoolman.math import (
    color_hex_to_hue,
    delta_e,
    hex_to_rgb,
    length_from_weight,
    rgb_to_hue,
    rgb_to_lab,
    weight_from_length,
)

# Common 1.75 mm PLA-ish parameters used across several tests.
DIAMETER_MM = 1.75
DENSITY_G_CM3 = 1.24


def test_weight_from_length_known_value():
    # volume = length * pi * (d/2)^2 = 1000 * pi * (0.875)^2 mm^3
    # = 1000 * pi * 0.765625 / 1000 cm^3 -> * density
    expected_volume_cm3 = (1000 * math.pi * (DIAMETER_MM / 2) ** 2) / 1000
    expected_weight = DENSITY_G_CM3 * expected_volume_cm3
    weight = weight_from_length(length=1000, diameter=DIAMETER_MM, density=DENSITY_G_CM3)
    assert weight == pytest.approx(expected_weight)


def test_length_from_weight_known_value():
    volume_cm3 = 100 / DENSITY_G_CM3
    volume_mm3 = volume_cm3 * 1000
    expected_length = volume_mm3 / (math.pi * (DIAMETER_MM / 2) ** 2)
    length = length_from_weight(weight=100, diameter=DIAMETER_MM, density=DENSITY_G_CM3)
    assert length == pytest.approx(expected_length)


def test_weight_length_roundtrip():
    original_length = 12345.6
    weight = weight_from_length(length=original_length, diameter=DIAMETER_MM, density=DENSITY_G_CM3)
    length = length_from_weight(weight=weight, diameter=DIAMETER_MM, density=DENSITY_G_CM3)
    assert length == pytest.approx(original_length)


def test_length_weight_roundtrip():
    original_weight = 998.7
    length = length_from_weight(weight=original_weight, diameter=DIAMETER_MM, density=DENSITY_G_CM3)
    weight = weight_from_length(length=length, diameter=DIAMETER_MM, density=DENSITY_G_CM3)
    assert weight == pytest.approx(original_weight)


def test_weight_from_zero_length_is_zero():
    # Edge case: zero length yields zero weight.
    assert weight_from_length(length=0, diameter=DIAMETER_MM, density=DENSITY_G_CM3) == pytest.approx(0)


def test_length_from_zero_weight_is_zero():
    # Edge case: zero weight yields zero length.
    assert length_from_weight(weight=0, diameter=DIAMETER_MM, density=DENSITY_G_CM3) == pytest.approx(0)


def test_hex_to_rgb_basic():
    assert hex_to_rgb("#FF0000") == [255, 0, 0]
    assert hex_to_rgb("00FF00") == [0, 255, 0]  # Works without leading '#'
    assert hex_to_rgb("#0000ff") == [0, 0, 255]


def test_rgb_to_lab_black_and_white():
    # Black maps to L ~= 0; white maps to L ~= 100.
    lab_black = rgb_to_lab([0, 0, 0])
    lab_white = rgb_to_lab([255, 255, 255])
    assert lab_black[0] == pytest.approx(0, abs=1e-6)
    assert lab_white[0] == pytest.approx(100, abs=1e-6)


def test_delta_e_identical_colors_is_zero():
    lab = rgb_to_lab([123, 45, 67])
    assert delta_e(lab, lab) == pytest.approx(0, abs=1e-9)


def test_delta_e_distinct_colors_is_positive():
    lab_a = rgb_to_lab([0, 0, 0])
    lab_b = rgb_to_lab([255, 255, 255])
    assert delta_e(lab_a, lab_b) > 0


def test_rgb_to_hue_primaries():
    # Red at 0deg, green at 120deg, blue at 240deg -- the classic HSV wheel positions.
    assert rgb_to_hue([255, 0, 0]) == pytest.approx(0)
    assert rgb_to_hue([0, 255, 0]) == pytest.approx(120)
    assert rgb_to_hue([0, 0, 255]) == pytest.approx(240)
    # Secondaries fall halfway between their neighbouring primaries.
    assert rgb_to_hue([255, 255, 0]) == pytest.approx(60)  # yellow
    assert rgb_to_hue([0, 255, 255]) == pytest.approx(180)  # cyan
    assert rgb_to_hue([255, 0, 255]) == pytest.approx(300)  # magenta


def test_rgb_to_hue_greys_are_zero():
    # Achromatic colours have no meaningful hue; they collapse to 0 so they sort together.
    assert rgb_to_hue([0, 0, 0]) == pytest.approx(0)
    assert rgb_to_hue([128, 128, 128]) == pytest.approx(0)
    assert rgb_to_hue([255, 255, 255]) == pytest.approx(0)


def test_rgb_to_hue_in_range():
    # A slightly-off colour still lands within the [0, 360) range.
    hue = rgb_to_hue([200, 120, 40])
    assert 0 <= hue < 360


def test_color_hex_to_hue_single_colour():
    assert color_hex_to_hue("#FF0000") == pytest.approx(0)
    assert color_hex_to_hue("00FF00") == pytest.approx(120)
    # An 8-char value with an alpha channel uses the RGB portion (first 6 chars).
    assert color_hex_to_hue("0000FFAA") == pytest.approx(240)


def test_color_hex_to_hue_falls_back_to_multi_colour():
    # With no single colour, the first entry of the multi-colour list is used.
    assert color_hex_to_hue(None, "#00FF00,#FF0000") == pytest.approx(120)


def test_color_hex_to_hue_none_for_missing_or_invalid():
    assert color_hex_to_hue(None, None) is None
    assert color_hex_to_hue("", "") is None
    assert color_hex_to_hue("#FFF", None) is None  # too short to be RRGGBB
    assert color_hex_to_hue("#ZZZZZZ", None) is None  # not valid hex
