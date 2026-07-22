"""Tests for the `poe scenario` CLI (host-only: no docker, no network)."""

from __future__ import annotations

import pytest

from tests_scenarios.__main__ import build_parser, cmd_list


def test_list_prints_core_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_list(build_parser().parse_args(["list"]))
    out = capsys.readouterr().out
    assert "sqlite-bare" in out
    assert "armv7-sqlite" in out


def test_parser_rejects_unknown_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["frobnicate"])
