"""Utility functions for the database module."""

from collections.abc import Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar

import sqlalchemy
from sqlalchemy import Select
from sqlalchemy.orm import attributes
from sqlalchemy.sql import ColumnElement

from spoolman.database import models

# Escape character for LIKE patterns. Deliberately not backslash: a backslash ESCAPE clause is
# ambiguous under MySQL/MariaDB string parsing. '/' renders safely on all four dialects.
LIKE_ESCAPE = "/"


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is matched literally, not as a wildcard pattern.

    Pair it with ``escape=LIKE_ESCAPE`` on the ``like``/``ilike`` call, or the escape character
    means nothing to the database and the wildcards are still live.

    Args:
        value: The raw user input to be embedded in a LIKE pattern.

    Returns:
        str: The input with the escape character and both wildcards escaped.

    """
    return value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", f"{LIKE_ESCAPE}%").replace("_", f"{LIKE_ESCAPE}_")


def utc_timezone_naive(dt: datetime) -> datetime:
    """Coerce a datetime to the naive-UTC form every datetime column in this codebase stores.

    A naive ``dt`` already means UTC here, so it is returned unchanged: calling
    ``astimezone()`` on it would have Python interpret it as system-local time and shift it
    by the host's offset (silently, and only on a non-UTC host). An offset-aware ``dt`` is
    genuinely converted to UTC before its tzinfo is dropped, so its instant in time is
    preserved. Same fix as :func:`spoolman.ai_tools.stats.parse_date`.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=timezone.utc)
    return dt.replace(tzinfo=None)


class SortOrder(Enum):
    ASC = 1
    DESC = 2


def order_by_clauses(
    exprs: Sequence[Any],
    order: "SortOrder",
) -> list[Any]:
    """Build ORDER BY clauses for one sort field, always placing NULLs last.

    The databases disagree on where a NULL goes: SQLite and MySQL treat NULL as the lowest
    value (so it lands last on DESC, first on ASC), while PostgreSQL and CockroachDB default
    to NULLS LAST on ASC and NULLS FIRST on DESC. A NULL means "no value recorded", which
    belongs at the bottom whichever way the list is pointing, so this orders on an explicit
    "is it null" flag first.

    It is written as a boolean expression rather than SQLAlchemy's ``nullslast()`` on purpose:
    that renders a literal NULLS LAST, which MySQL and MariaDB do not support, whereas
    ``expr IS NULL`` sorts false-before-true on all four supported databases.

    Args:
        exprs: The expressions to sort by, in priority order. A field usually contributes one.
        order: The requested direction, applied to every expression.

    Returns:
        list[Any]: Clauses to hand to ``Select.order_by()``.

    """
    clauses: list[Any] = []
    for expr in exprs:
        clauses.append(expr.is_(None).asc())
        clauses.append(expr.asc() if order == SortOrder.ASC else expr.desc())
    return clauses


def parse_sort(sort: str | None) -> dict[str, "SortOrder"]:
    """Parse a sort query string of comma-separated "field:direction" items.

    Raises ValueError (mapped to HTTP 400 by the endpoints) for malformed input instead of letting
    an unpacking ValueError / KeyError surface as a 500.
    """
    sort_by: dict[str, SortOrder] = {}
    if sort is None:
        return sort_by
    for sort_item in sort.split(","):
        field, sep, direction = sort_item.partition(":")
        if not sep or direction.upper() not in SortOrder.__members__:
            raise ValueError(
                f"Invalid sort item '{sort_item}'. Expected '<field>:asc' or '<field>:desc'.",
            )
        sort_by[field] = SortOrder[direction.upper()]
    return sort_by


def parse_nested_field(base_obj: type[models.Base], field: str) -> attributes.InstrumentedAttribute[Any]:
    """Parse a nested field string into a sqlalchemy field object."""
    fields = field.split(".")
    if not hasattr(base_obj, fields[0]):
        raise ValueError(f"Invalid field name '{field}', '{fields[0]}' is not a valid field on '{base_obj.__name__}'.")

    if fields[0] == "filament" and len(fields) == 1:
        raise ValueError("No field specified for filament")
    if fields[0] == "filament":
        return parse_nested_field(models.Filament, ".".join(fields[1:]))

    if fields[0] == "vendor" and len(fields) == 1:
        raise ValueError("No field specified for vendor")
    if fields[0] == "vendor":
        return parse_nested_field(models.Vendor, ".".join(fields[1:]))

    if len(fields) > 1:
        raise ValueError(f"Field '{fields[0]}' does not have any nested fields")

    return getattr(base_obj, fields[0])


def order_by_expression(expr: ColumnElement[Any], order: "SortOrder") -> ColumnElement[Any]:
    """Build an ORDER BY clause element, sorting string columns case-insensitively.

    Among the four supported backends only SQLite's default BINARY collation sorts
    case-sensitively, so a lowercase-initial vendor like "eSUN" would sort after every
    uppercase name. Wrapping string expressions in lower() gives portable dictionary
    order; numeric/date/other expressions (e.g. the computed remaining_weight sort) are
    left untouched. Issue #63.
    """
    col_type = getattr(expr, "type", None)
    if isinstance(col_type, sqlalchemy.String):
        expr = sqlalchemy.func.lower(expr)
    return expr.asc() if order == SortOrder.ASC else expr.desc()


def add_where_clause_str_opt(
    stmt: Select,
    field: attributes.InstrumentedAttribute[str | None],
    value: str | None,
) -> Select:
    """Add a where clause to a select statement for an optional string field."""
    if value is not None:
        conditions = []
        for value_part in value.split(","):
            # If part is empty, search for empty fields
            if len(value_part) == 0:
                conditions.append(field.is_(None))
                conditions.append(field == "")
            # Do exact match if value_part is surrounded by quotes
            elif value_part[0] == '"' and value_part[-1] == '"':
                conditions.append(field == value_part[1:-1])
            # Do fuzzy match if value_part is not surrounded by quotes
            else:
                conditions.append(field.ilike(f"%{escape_like(value_part)}%", escape=LIKE_ESCAPE))

        stmt = stmt.where(sqlalchemy.or_(*conditions))
    return stmt


def add_where_clause_str(
    stmt: Select,
    field: attributes.InstrumentedAttribute[str],
    value: str | None,
) -> Select:
    """Add a where clause to a select statement for a string field."""
    if value is not None:
        conditions = []
        for value_part in value.split(","):
            # If part is empty, search for empty fields
            if len(value_part) == 0:
                conditions.append(field == "")
            # Do exact match if value_part is surrounded by quotes
            elif value_part[0] == '"' and value_part[-1] == '"':
                conditions.append(field == value_part[1:-1])
            # Do fuzzy match if value_part is not surrounded by quotes
            else:
                conditions.append(field.ilike(f"%{escape_like(value_part)}%", escape=LIKE_ESCAPE))

        stmt = stmt.where(sqlalchemy.or_(*conditions))
    return stmt


# Separates the two ends of a datetime range. Not ':', which ISO 8601 timestamps are full of —
# the same reason the extra-field datetime filters use this character (see add_where_clause_extra_field).
DATETIME_RANGE_SEPARATOR = "|"


def split_datetime_range_filter(value: str, field_name: str) -> tuple[str, str] | None:
    """Split a `<start>|<end>` datetime filter into its two ends, or None if it isn't a range.

    Either end may be empty, leaving that side open; a range with neither end asks nothing and is
    rejected. Shared by any built-in datetime columns and the datetime extra fields so that the
    one documented grammar is parsed in exactly one place. Only the parsing is common: what each
    caller then does with the ends differs, because a typed column would be compared as a datetime
    while an extra field is compared as its decoded JSON text (see add_where_clause_extra_field).
    """
    if DATETIME_RANGE_SEPARATOR not in value:
        return None
    start, _, end = value.partition(DATETIME_RANGE_SEPARATOR)
    if not start and not end:
        raise ValueError(
            f"Invalid datetime range filter for '{field_name}': '{value}'. "
            f"Expected '<start>{DATETIME_RANGE_SEPARATOR}<end>' with at least one end given.",
        )
    return start, end


def add_where_clause_int(
    stmt: Select,
    field: attributes.InstrumentedAttribute[int],
    value: int | Sequence[int] | None,
) -> Select:
    """Add a where clause to a select statement for a field."""
    if value is not None:
        if isinstance(value, int):
            value = [value]
        stmt = stmt.where(field.in_(value))
    return stmt


def add_where_clause_int_opt(
    stmt: Select,
    field: attributes.InstrumentedAttribute[int | None],
    value: int | Sequence[int] | None,
) -> Select:
    """Add a where clause to a select statement for a field."""
    if value is not None:
        if isinstance(value, int):
            value = [value]
        statements = []
        for value_part in value:
            if value_part == -1:
                statements.append(field.is_(None))
            else:
                statements.append(field == value_part)
        stmt = stmt.where(sqlalchemy.or_(*statements))
    return stmt


T = TypeVar("T")


def add_where_clause_int_in(
    stmt: Select,
    field: attributes.InstrumentedAttribute[T],
    value: Sequence[T] | None,
) -> Select:
    """Add a where clause to a select statement for a field."""
    if value is not None:
        stmt = stmt.where(field.in_(value))
    return stmt
