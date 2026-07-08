"""Unit tests for the format-agnostic import parsing/unflattening (issue #55).

These cover spoolman.import_data in isolation: turning a CSV/JSON export body into per-row
(source_id, params) pairs, including the foreign-key remap, extra-field collection, and the dropping
of read-only/computed columns and empty cells.
"""

import pytest

from spoolman.import_data import ImportFormat, parse_body, unflatten_row


def test_parse_csv_reads_header_and_rows():
    body = "id,name,weight\n1,PLA,1000\n2,PETG,750\n"
    rows = parse_body(body, ImportFormat.CSV)
    assert rows == [
        {"id": "1", "name": "PLA", "weight": "1000"},
        {"id": "2", "name": "PETG", "weight": "750"},
    ]


def test_parse_json_list():
    body = '[{"id": 1, "name": "PLA"}, {"id": 2, "name": "PETG"}]'
    assert parse_body(body, ImportFormat.JSON) == [{"id": 1, "name": "PLA"}, {"id": 2, "name": "PETG"}]


def test_parse_json_single_object_becomes_one_row():
    assert parse_body('{"name": "PLA"}', ImportFormat.JSON) == [{"name": "PLA"}]


def test_parse_empty_body_is_empty_list():
    assert parse_body("", ImportFormat.CSV) == []
    assert parse_body("   ", ImportFormat.JSON) == []


def test_parse_json_scalar_is_rejected():
    with pytest.raises(ValueError, match="list of objects"):
        parse_body("5", ImportFormat.JSON)


def test_parse_json_list_of_scalars_is_rejected():
    with pytest.raises(ValueError, match="only objects"):
        parse_body("[1, 2, 3]", ImportFormat.JSON)


def test_unflatten_extracts_id_fk_and_extra():
    row = {
        "id": "7",
        "name": "PLA",
        "vendor.id": "3",
        "vendor.name": "Acme",  # nested, non-id -> dropped
        "extra.foo": '"bar"',
        "extra.count": "5",
    }
    parsed = unflatten_row(row, fk_map={"vendor.id": "vendor_id"}, ignore=set())
    assert parsed.source_id == 7
    assert parsed.params == {
        "name": "PLA",
        "vendor_id": 3,
        "extra": {"foo": '"bar"', "count": "5"},
    }


def test_unflatten_drops_ignored_and_empty():
    row = {
        "id": "1",
        "name": "PLA",
        "material": "",  # empty -> dropped
        "spool_count": "4",  # ignored (aggregate)
        "remaining_weight": "2500",  # ignored (aggregate)
        "registered": "2024-01-01T00:00:00Z",  # ignored (read-only)
        "weight": "1000",
    }
    parsed = unflatten_row(
        row,
        fk_map={},
        ignore={"registered", "spool_count", "remaining_weight"},
    )
    assert parsed.source_id == 1
    assert parsed.params == {"name": "PLA", "weight": "1000"}


def test_unflatten_without_id_leaves_source_id_none():
    parsed = unflatten_row({"name": "PLA"}, fk_map={}, ignore=set())
    assert parsed.source_id is None
    assert parsed.params == {"name": "PLA"}
