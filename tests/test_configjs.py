"""Tests for the generated config.js, which interpolates the operator's base path into JS.

Ported from upstream's ``security: finish the audit's low-severity items`` (task 10). Adapted to
this fork's shape: the interpolation logic lives in ``spoolman.client.build_configjs`` (shared by
the plain base-path case and the Home Assistant ingress case), rather than inline in the FastAPI
endpoint in ``spoolman.main`` -- testing it directly here avoids depending on a built client
bundle, which ``spoolman.main`` requires at import time.
"""

import json

from spoolman.client import build_configjs


def value_of(rendered: str) -> str:
    """Parse back the JS string literal the first `window.SPOOLMAN_BASE_PATH = ...;` line holds."""
    line = next(line for line in rendered.splitlines() if "SPOOLMAN_BASE_PATH" in line)
    literal = line.split(" = ", 1)[1].strip().rstrip(";")
    return json.loads(literal)


def test_an_ordinary_base_path_round_trips():
    assert value_of(build_configjs("/spoolman")) == "/spoolman"


def test_an_empty_base_path_round_trips():
    assert value_of(build_configjs("")) == ""


def test_a_quote_cannot_close_the_literal():
    """The old hand-quoting caught this case, by refusing to serve at all."""
    assert value_of(build_configjs('/spool"man')) == '/spool"man'


def test_a_trailing_backslash_cannot_escape_the_closing_quote():
    """The case hand-quoting missed: the backslash would have escaped the terminating quote."""
    rendered = build_configjs("/spoolman\\")
    assert 'window.SPOOLMAN_BASE_PATH = "/spoolman\\\\";' in rendered
    assert value_of(rendered) == "/spoolman\\"


def test_a_backslash_quote_pair_cannot_inject_a_statement():
    assert value_of(build_configjs('/spoolman\\";alert(1);//')) == '/spoolman\\";alert(1);//'


def test_a_newline_cannot_break_out_of_the_statement():
    rendered = build_configjs("/spool\nman")
    line = next(line for line in rendered.splitlines() if "SPOOLMAN_BASE_PATH" in line)
    assert "\n" not in line
    assert value_of(rendered) == "/spool\nman"


def test_ingress_base_path_is_also_json_encoded():
    """The ingress branch hand-quoted too, even though HA's own path shape is already safe.

    Covered here so the two branches cannot drift.
    """
    rendered = build_configjs("/spoolman", ingress_base_path='/api/hassio_ingress/abc"def')
    assert value_of(rendered) == '/api/hassio_ingress/abc"def'
    assert "window.SPOOLMAN_HA_INGRESS = true;" in rendered
