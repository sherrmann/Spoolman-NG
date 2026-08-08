"""Compile-level guards for the SQL types of the used_weight write expressions (#377).

use_weight_safe's refill path clamps at zero with a ``CASE``: one branch is the NUMERIC-typed
``_round6`` result, the other is the literal zero. CockroachDB requires every branch of a ``CASE``
to resolve to the same type and rejects a mixed one outright::

    asyncpg.exceptions.InvalidParameterValueError: incompatible value type:
    expected $5::FLOAT8 to be of type decimal, found type float

PostgreSQL, SQLite and MySQL/MariaDB all accept the mismatch, so a bare ``else_=0.0`` regression
passes every fast-suite test (they run SQLite) and only turns up on the Docker-based CockroachDB
leg of the integration matrix -- which is exactly how it shipped once already. These tests assert
the invariant on the compiled SQL instead of on a live database, so the fast suite catches it.

They deliberately compile the *production* expressions imported from spoolman.database.spool
rather than rebuilding equivalent ones here: a local copy of the ``case()`` would keep passing
after someone reverted the real one.
"""

import re
import warnings

import pytest
import sqlalchemy
from sqlalchemy import Float, Numeric
from sqlalchemy.dialects import registry

from spoolman.database import models
from spoolman.database.spool import WEIGHT_NUMERIC, _round6, _used_weight_after_refill

# Matches the type in any "CAST(... AS <TYPE>(p, s))" the compiler emitted. Dialects spell the
# fixed-point type differently -- NUMERIC on PostgreSQL/CockroachDB/SQLite, DECIMAL on
# MySQL/MariaDB -- so capture whatever was emitted instead of pinning one spelling.
_CAST_TYPE_RE = re.compile(r"\bAS ([A-Z]+\(\d+, ?\d+\))\)")

# CockroachDB is the strict one and the reason this file exists; the others are compiled too so a
# fix that only satisfies one dialect stands out.
_DIALECT_NAMES = ["cockroachdb", "postgresql", "mysql", "sqlite"]


def _compile(element: sqlalchemy.ClauseElement, dialect_name: str) -> str:
    dialect = registry.load(dialect_name)()
    return str(element.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def _compile_capturing(element: sqlalchemy.ClauseElement, dialect_name: str) -> tuple[str, list[str]]:
    """Compile, returning the SQL and any warnings the compiler raised (rather than leaking them)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sql = _compile(element, dialect_name)
    return sql, [str(warning.message) for warning in caught]


@pytest.mark.parametrize("dialect_name", _DIALECT_NAMES)
def test_refill_case_branches_declare_the_same_sql_type(dialect_name: str):
    """Both branches of the refill CASE must declare the same fixed-point type.

    The rounded branch is ``round(CAST(... AS NUMERIC(18, 6)), 6)``; the zero-clamp branch has to
    be cast to the same type rather than left as a bare float literal, or CockroachDB refuses the
    UPDATE. Split the compiled CASE into its THEN and ELSE halves and compare the types each one
    declares -- a bare ``0.0`` declares none, so this fails loudly if the cast is removed.
    """
    sql = _compile(_used_weight_after_refill(-100.0), dialect_name)

    before_else, else_separator, else_branch = sql.rpartition(" ELSE ")
    assert else_separator, f"expected a CASE with an ELSE branch, got: {sql}"
    else_branch = else_branch.removesuffix(" END")
    _, then_separator, then_branch = before_else.partition(" THEN ")
    assert then_separator, f"expected a CASE with a THEN branch, got: {sql}"

    then_types = set(_CAST_TYPE_RE.findall(then_branch))
    else_types = set(_CAST_TYPE_RE.findall(else_branch))
    assert then_types, f"the rounded branch is no longer fixed-point typed: {sql}"
    assert else_types == then_types, (
        f"the zero-clamp branch declares {else_types or 'no type'} while the rounded branch "
        f"declares {then_types}; CockroachDB rejects a CASE whose branches disagree on type. "
        f"Compiled for {dialect_name}: {sql}"
    )


def test_refill_case_resolves_to_the_shared_weight_numeric_type():
    """SQLAlchemy must resolve the whole CASE to WEIGHT_NUMERIC, not to double precision.

    ``Float`` subclasses ``Numeric``, so an isinstance check alone would not notice the
    regression -- the exact type has to be pinned.
    """
    case_type = _used_weight_after_refill(-100.0).type
    assert isinstance(case_type, Numeric)
    assert not isinstance(case_type, Float), f"the CASE resolved to a float type: {case_type!r}"
    assert (case_type.precision, case_type.scale) == (WEIGHT_NUMERIC.precision, WEIGHT_NUMERIC.scale)


def test_weight_updates_compile_without_mysql_cast_warnings():
    """Neither used_weight UPDATE may reintroduce a CAST that MySQL/MariaDB cannot honour.

    Reconciling the CASE branches by wrapping the whole thing in ``CAST(... AS FLOAT)`` also works
    on CockroachDB, but MySQL/MariaDB support no such cast: SQLAlchemy drops it from the compiled
    SQL and warns. The positive control at the end proves this detector actually fires, so a green
    result means "no warning", not "warnings are invisible here".
    """
    consume = sqlalchemy.update(models.Spool).values(used_weight=_round6(models.Spool.used_weight + 5.0))
    refill = sqlalchemy.update(models.Spool).values(used_weight=_used_weight_after_refill(-5.0))
    assert _compile_capturing(consume, "mysql")[1] == []
    assert _compile_capturing(refill, "mysql")[1] == []

    float_cast = sqlalchemy.update(models.Spool).values(
        used_weight=sqlalchemy.cast(_round6(models.Spool.used_weight + 5.0), Float),
    )
    float_cast_sql, float_cast_warnings = _compile_capturing(float_cast, "mysql")
    assert float_cast_warnings, "the MySQL CAST warning detector no longer fires"
    assert "FLOAT" not in float_cast_sql, "MySQL is expected to drop the FLOAT cast entirely"


def test_consumption_update_assigns_the_rounded_value_without_a_case():
    """The consumption path has no CASE, so it needs no clamp branch to agree with.

    This pins the asymmetry the _round6 docstring describes: only the refill path builds a CASE,
    which is why only it needs the extra cast. If consumption ever grows one, this test fails and
    whoever added it has to give the new branch a matching type too.
    """
    sql = _compile(
        sqlalchemy.update(models.Spool).values(used_weight=_round6(models.Spool.used_weight + 5.0)),
        "cockroachdb",
    )
    assert "CASE" not in sql, sql
    assert _CAST_TYPE_RE.findall(sql), sql
