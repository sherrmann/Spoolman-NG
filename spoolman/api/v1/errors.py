"""Shared exception handlers for the v1 API.

Kept out of ``router.py`` so the in-process test harness can install exactly the same handlers the
real app uses. Without that, error responses in tests are rendered by FastAPI's defaults while
production uses these — and a bug in the difference is invisible to the suite, which is precisely
how the non-finite-float 500 below went unnoticed (#377).
"""

import logging
import math

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from spoolman.exceptions import ItemNotFoundError

logger = logging.getLogger(__name__)


def json_safe(value: object) -> object:
    """Replace non-finite floats so a strict JSON encoder can render the value.

    ``Infinity`` and ``NaN`` are not valid JSON, but Python's ``json.loads`` — which Starlette uses
    to read request bodies — accepts the bare literals, so they can reach a validation error's echo
    of the offending input. Starlette then renders with ``json.dumps(allow_nan=False)``, which
    raises. ``repr`` keeps the rejected value visible to the caller ("inf", "nan") rather than
    dropping it, since showing the input back is the point of the error.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


async def itemnotfounderror_exception_handler(_request: Request, exc: ItemNotFoundError) -> Response:
    """Render a missing item as a 404."""
    logger.debug(exc)
    return JSONResponse(status_code=404, content={"message": exc.args[0]})


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> Response:
    """Render a 422 that a strict JSON encoder can actually serialize (#377).

    A non-finite float in the request body is rejected by validation, but the rejection used to be
    unrenderable — the payload echoed the offending ``inf``/``nan`` straight back — so a clean 422
    turned into an unhandled 500 and masked the real problem.
    """
    # jsonable_encoder first, exactly as FastAPI's own handler does: an error's `ctx` can hold a
    # live exception object, which json.dumps cannot serialize. It leaves floats alone, so the
    # non-finite pass still has to run after it.
    return JSONResponse(status_code=422, content={"detail": json_safe(jsonable_encoder(exc.errors()))})


def install_exception_handlers(app: FastAPI) -> None:
    """Register the API's exception handlers on ``app``."""
    app.add_exception_handler(ItemNotFoundError, itemnotfounderror_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
