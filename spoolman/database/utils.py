"""Utility functions for the database module."""

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar

import sqlalchemy
from sqlalchemy import Select
from sqlalchemy.orm import attributes
from sqlalchemy.sql import ColumnElement

from spoolman import env
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


def utc_now() -> datetime:
    """Return the current time in the naive-UTC form every datetime column in this codebase stores.

    This is the replacement for the ``datetime.utcnow`` classmethod, deprecated since Python 3.12. It
    must stay naive: the ORM drops tzinfo on read-back, so an offset-aware value written today
    comes back naive tomorrow, and a comparison between the two raises ``TypeError``. Callers
    that write a column keep their own ``.replace(microsecond=0)`` on top of this; the event
    emitters use the value as it is. See :func:`utc_timezone_naive` for the storage contract.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        # The first mention of a field decides its order, as it would in SQL: `ORDER BY id DESC, id ASC`
        # sorts descending. Overwriting instead turned the Svelte client's `id:asc` tie-breaker into the
        # primary order whenever the user sorted by ID descending.
        sort_by.setdefault(field, SortOrder[direction.upper()])
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


# A quote that ends a quoted filter part: followed by a comma or the end of the value.
_CLOSING_QUOTE = re.compile(r'"(?=,|\Z)')


def split_filter_values(value: str) -> list[str]:
    """Split a comma-separated filter value, keeping commas inside a quoted part.

    A part wrapped in double quotes is an exact match, and its value may itself contain a
    comma (a location called "Top shelf, Rack 3"). A part that starts with a quote runs to the
    first quote followed by a comma or the end of the string. Without such a closing quote, or
    for a part that doesn't start with one, this splits at the next comma exactly like
    ``value.split(",")``, so every value that has no comma inside quotes splits as before.
    """
    parts: list[str] = []
    start = 0
    # Once no closing quote is found after some position, none exists after any later one
    # either, so the search runs at most once past the last closing quote. Without this a
    # value like '"a,' * n rescans the rest of the string for every part: quadratic.
    closing_quote_left = True
    while True:
        end = -1
        if closing_quote_left and value.startswith('"', start):
            match = _CLOSING_QUOTE.search(value, start + 1)
            if match:
                end = match.end()
            else:
                closing_quote_left = False
        if end == -1:
            comma = value.find(",", start)
            end = len(value) if comma == -1 else comma
        parts.append(value[start:end])
        if end == len(value):
            return parts
        start = end + 1


# How many alternatives one filter may OR together on SQLite. SQLite parses `a OR b OR c ...`
# into a tree as deep as the chain is long and refuses one deeper than 1000 ("Expression tree is
# too large"), which reached the client as a 500. Measured, a spool list with every other filter
# set still ran at 980 alternatives and failed at 990, so this leaves room for the rest of the
# query. SQLAlchemy flattens nested ORs back into one chain, so the tree cannot be balanced
# instead. The other three databases have no such limit and are not capped.
#
# Exact matches on a built-in string field, and ids, do not add to the chain: they are collected
# into one IN list, which SQLite does not nest.
SQLITE_MAX_FILTER_ALTERNATIVES = 900


def any_of(conditions: Sequence[ColumnElement[bool]], what: str) -> ColumnElement[bool]:
    """OR `conditions` together, refusing a chain too long for SQLite to parse.

    Raises ValueError, which the list endpoints turn into a 400, naming `what` was filtered on.
    """
    if len(conditions) > SQLITE_MAX_FILTER_ALTERNATIVES and env.get_database_type() in (None, env.DatabaseType.SQLITE):
        raise ValueError(
            f"The '{what}' filter asks for too many alternatives at once ({len(conditions)}); "
            f"with SQLite at most {SQLITE_MAX_FILTER_ALTERNATIVES} are supported. Split the request.",
        )
    return sqlalchemy.or_(*conditions)


def _str_filter_conditions(
    field: attributes.InstrumentedAttribute[Any],
    value: str,
    *,
    empty_means_null: bool,
) -> ColumnElement[bool]:
    """Build the condition for a comma-separated string filter value (see add_where_clause_str)."""
    conditions: list[ColumnElement[bool]] = []
    exact: list[str] = []
    for value_part in split_filter_values(value):
        # If part is empty, search for empty fields
        if len(value_part) == 0:
            if empty_means_null:
                conditions.append(field.is_(None))
            conditions.append(field == "")
        # Do exact match if value_part is surrounded by quotes
        elif value_part[0] == '"' and value_part[-1] == '"':
            exact.append(value_part[1:-1])
        # Do fuzzy match if value_part is not surrounded by quotes
        else:
            conditions.append(field.ilike(f"%{escape_like(value_part)}%", escape=LIKE_ESCAPE))
    if exact:
        # One IN list however many values: `field = x` per value would lengthen the OR chain.
        conditions.append(field == exact[0] if len(exact) == 1 else field.in_(exact))
    return any_of(conditions, f"{field.class_.__tablename__}.{field.key}")


def add_where_clause_str_opt(
    stmt: Select,
    field: attributes.InstrumentedAttribute[str | None],
    value: str | None,
) -> Select:
    """Add a where clause to a select statement for an optional string field."""
    if value is not None:
        stmt = stmt.where(_str_filter_conditions(field, value, empty_means_null=True))
    return stmt


def add_where_clause_str(
    stmt: Select,
    field: attributes.InstrumentedAttribute[str],
    value: str | None,
) -> Select:
    """Add a where clause to a select statement for a string field."""
    if value is not None:
        stmt = stmt.where(_str_filter_conditions(field, value, empty_means_null=False))
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
        # -1 asks for rows with no value; every other id goes in one IN list, which unlike an
        # `id = x OR ...` chain does not get deeper with each id (see any_of).
        ids = [v for v in value if v != -1]
        statements: list[ColumnElement[bool]] = [field.in_(ids)] if ids else []
        if len(ids) < len(value):
            statements.append(field.is_(None))
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
