"""Behavioural tests for the log filter that hides websocket API tokens.

Browsers cannot set a header on a websocket handshake, so both of this fork's clients put the
bearer token on the websocket URL (see ``spoolman/auth.py``). uvicorn logs every request line
with its query string, and ``spoolman/main.py`` routes those records to the console and to the
rotating ``spoolman.log`` -- which is how the credential ended up on disk in clear text.

The oracle here is the text a handler actually emits, not the filter's internals: every test
builds a real logger with a real handler and reads back what was written.
"""

import io
import logging
import uuid

import pytest

from spoolman.security import RedactQueryTokenFilter

# uvicorn's own format strings, copied verbatim from uvicorn.protocols.websockets and
# uvicorn.logging, so that a change in how it logs shows up here as a failure.
WEBSOCKET_FORMAT = '%s - "WebSocket %s" [accepted]'
ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


@pytest.fixture
def logger() -> logging.Logger:
    """Build a logger of its own, so nothing else in the suite can write into the stream."""
    log = logging.getLogger(f"test.redaction.{uuid.uuid4()}")
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


def _capture(logger: logging.Logger, *, redact: bool) -> io.StringIO:
    """Attach a stream handler to the logger, optionally behind the filter, and return the stream."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    if redact:
        handler.addFilter(RedactQueryTokenFilter())
    logger.addHandler(handler)
    return stream


def test_a_websocket_handshake_line_loses_its_token(logger: logging.Logger):
    """The line uvicorn logs for every accepted handshake, which is where the token rides."""
    stream = _capture(logger, redact=True)
    logger.info(WEBSOCKET_FORMAT, "127.0.0.1:1234", "/api/v1/spool?token=SECRET")
    written = stream.getvalue()
    assert "SECRET" not in written
    assert "token=[redacted]" in written
    assert "/api/v1/spool" in written


def test_an_access_line_keeps_every_other_query_parameter(logger: logging.Logger):
    """Only the token's value goes; the rest of the query string is what makes the log useful."""
    stream = _capture(logger, redact=True)
    logger.info(ACCESS_FORMAT, "127.0.0.1:1234", "GET", "/api/v1/spool?a=1&token=SECRET&b=2", "1.1", 200)
    written = stream.getvalue()
    assert "SECRET" not in written
    assert "a=1" in written
    assert "b=2" in written
    assert "token=[redacted]" in written


def test_a_line_without_a_token_is_untouched(logger: logging.Logger):
    """A record the filter has no business rewriting must come out byte for byte the same."""
    plain = _capture(logger, redact=False)
    redacted = _capture(logger, redact=True)
    logger.info(ACCESS_FORMAT, "127.0.0.1:1234", "GET", "/api/v1/spool?a=1", "1.1", 200)
    assert redacted.getvalue() == plain.getvalue()


def test_non_string_arguments_survive_interpolation(logger: logging.Logger):
    """The access line's status code is an int; rewriting the record must not break formatting."""
    stream = _capture(logger, redact=True)
    logger.info(ACCESS_FORMAT, "127.0.0.1:1234", "DELETE", "/api/v1/spool/1?token=SECRET", "1.1", 404)
    written = stream.getvalue()
    assert "SECRET" not in written
    assert written.strip() == '127.0.0.1:1234 - "DELETE /api/v1/spool/1?token=[redacted] HTTP/1.1" 404'


def test_the_parameter_name_is_matched_case_insensitively(logger: logging.Logger):
    """Query parameter names are only conventionally lower-case."""
    stream = _capture(logger, redact=True)
    logger.info(WEBSOCKET_FORMAT, "127.0.0.1:1234", "/api/v1/spool?Token=SECRET")
    assert "SECRET" not in stream.getvalue()


def test_a_name_that_merely_ends_in_token_is_left_alone(logger: logging.Logger):
    """Documents the intended scope: only the parameter auth reads, not any name ending in it."""
    stream = _capture(logger, redact=True)
    logger.info(WEBSOCKET_FORMAT, "127.0.0.1:1234", "/api/v1/spool?apitoken=KEEPME")
    assert "KEEPME" in stream.getvalue()


def test_the_same_word_in_prose_is_left_alone(logger: logging.Logger):
    """The auth startup line says ``(token=True, accounts=False)``; that is a diagnostic, not a secret."""
    stream = _capture(logger, redact=True)
    logger.info("API authentication is ENABLED (token=%s, accounts=%s).", True, False)  # noqa: FBT003
    assert stream.getvalue().strip() == "API authentication is ENABLED (token=True, accounts=False)."


def test_an_apostrophe_in_the_token_does_not_end_the_redaction(logger: logging.Logger):
    """The browser's encodeURIComponent leaves ``'`` unescaped, so an operator-chosen token may contain one."""
    stream = _capture(logger, redact=True)
    logger.info(WEBSOCKET_FORMAT, "127.0.0.1:1234", "/api/v1/spool?token=it's-a-secret")
    written = stream.getvalue()
    assert "secret" not in written
    assert "token=[redacted]" in written


def test_uvicorns_own_access_formatter_still_works(logger: logging.Logger):
    """The filter must redact the arguments in place rather than flatten them into the message.

    ``uvicorn.run(app)`` keeps uvicorn's own access handler, whose formatter unpacks the record's
    arguments positionally, so a flattened record would make every access line fail to format.
    """
    from uvicorn.logging import AccessFormatter  # noqa: PLC0415

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    handler.addFilter(RedactQueryTokenFilter())
    logger.addHandler(handler)
    logger.info(ACCESS_FORMAT, "127.0.0.1:1234", "GET", "/api/v1/spool?token=SECRET", "1.1", 200)
    written = stream.getvalue()
    assert "SECRET" not in written
    assert written.strip() == '127.0.0.1:1234 - "GET /api/v1/spool?token=[redacted] HTTP/1.1" 200 OK'


def test_a_pre_formatted_message_is_redacted(logger: logging.Logger):
    """Some code formats the line itself before logging; the token must go there too."""
    stream = _capture(logger, redact=True)
    logger.info("closing ws://spoolman.local/api/v1/spool?token=SECRET&x=1")
    assert stream.getvalue().strip() == "closing ws://spoolman.local/api/v1/spool?token=[redacted]&x=1"


def test_a_template_with_pending_arguments_is_not_mangled(logger: logging.Logger):
    """A placeholder sitting where the value goes must survive, or the record would fail to format."""
    stream = _capture(logger, redact=True)
    logger.info("url was ?token=%s for %s", "SECRET", "spool")
    written = stream.getvalue().strip()
    assert written == "url was ?token=SECRET for spool"
