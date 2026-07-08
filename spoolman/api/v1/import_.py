"""Data import endpoint — the inverse of /export (issue #55).

Accepts a raw CSV or JSON body in the exact shape produced by /export (flat rows with dot-separated
keys), validates every row with the existing *Parameters models, and applies them to the database in
a single all-or-nothing transaction. If any row fails validation or references a missing foreign key,
nothing is written and the errors are returned. A dry run validates and reports the would-be counts
without committing.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.filament import FilamentParameters
from spoolman.api.v1.spool import SpoolParameters
from spoolman.api.v1.vendor import VendorParameters
from spoolman.database import models
from spoolman.database.database import get_db_session
from spoolman.database.utils import utc_timezone_naive
from spoolman.import_data import ImportFormat, ImportMode, ImportResult, parse_body, unflatten_row

router = APIRouter(
    prefix="/import",
    tags=["import"],
)

# ruff: noqa: D103


class ImportResponse(BaseModel):
    created: int = Field(description="Number of rows inserted (or that would be inserted on a dry run).")
    updated: int = Field(description="Number of existing rows updated (upsert mode).")
    skipped: int = Field(description="Number of rows skipped (skip_existing mode).")
    dry_run: bool = Field(description="Whether this was a dry run — if true, nothing was committed.")
    errors: list[str] = Field(description="Per-row errors. Non-empty means nothing was committed.")


# Per-entity import configuration: which *Parameters model validates a row, which foreign-key columns
# a dotted export key maps to, and which columns to ignore (computed/aggregate/read-only).
_FK_MAP: dict[str, dict[str, str]] = {
    "vendor": {},
    "filament": {"vendor.id": "vendor_id"},
    "spool": {"filament.id": "filament_id"},
}
_IGNORE: dict[str, set[str]] = {
    "vendor": {"registered", "filament_count", "spool_count"},
    "filament": {"registered", "spool_count", "remaining_weight"},
    "spool": {"registered", "remaining_weight", "used_length", "remaining_length"},
}
_PARAMS = {
    "vendor": VendorParameters,
    "filament": FilamentParameters,
    "spool": SpoolParameters,
}


def _now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


async def _build_vendor(
    db: AsyncSession,  # noqa: ARG001  (kept for a uniform builder signature; vendors have no foreign keys)
    data: dict[str, Any],
    existing: models.Vendor | None,
) -> models.Vendor:
    extra = data.pop("extra", None)
    obj = existing or models.Vendor(registered=_now())
    for key, value in data.items():
        setattr(obj, key, value)
    if extra is not None:
        obj.extra = [models.VendorField(key=k, value=v) for k, v in extra.items()]
    return obj


async def _build_filament(db: AsyncSession, data: dict[str, Any], existing: models.Filament | None) -> models.Filament:
    extra = data.pop("extra", None)
    vendor_id = data.pop("vendor_id", None)
    direction = data.pop("multi_color_direction", None)
    obj = existing or models.Filament(registered=_now())
    for key, value in data.items():
        setattr(obj, key, value)
    obj.multi_color_direction = direction.value if direction is not None else None
    if vendor_id is None:
        obj.vendor = None
    else:
        vendor = await db.get(models.Vendor, vendor_id)
        if vendor is None:
            raise LookupError(f"vendor with id {vendor_id} does not exist")
        obj.vendor = vendor
    if extra is not None:
        obj.extra = [models.FilamentField(key=k, value=v) for k, v in extra.items()]
    return obj


async def _build_spool(db: AsyncSession, data: dict[str, Any], existing: models.Spool | None) -> models.Spool:
    extra = data.pop("extra", None)
    filament_id = data.pop("filament_id", None)
    # remaining_weight is a computed view; the raw used_weight from the export is authoritative.
    data.pop("remaining_weight", None)
    for time_key in ("first_used", "last_used"):
        if isinstance(data.get(time_key), datetime):
            data[time_key] = utc_timezone_naive(data[time_key])
    obj = existing or models.Spool(registered=_now(), used_weight=0)
    for key, value in data.items():
        setattr(obj, key, value)
    if filament_id is not None:
        filament = await db.get(models.Filament, filament_id)
        if filament is None:
            raise LookupError(f"filament with id {filament_id} does not exist")
        obj.filament = filament
    elif existing is None:
        raise LookupError("spool row is missing filament.id")
    if extra is not None:
        obj.extra = [models.SpoolField(key=k, value=v) for k, v in extra.items()]
    return obj


_BUILDERS = {
    "vendor": _build_vendor,
    "filament": _build_filament,
    "spool": _build_spool,
}
_MODELS = {
    "vendor": models.Vendor,
    "filament": models.Filament,
    "spool": models.Spool,
}


@router.post(
    "/{entity}",
    name="Import data",
    description=(
        "Import vendors, filaments or spools from a CSV or JSON body in the same flat, dot-separated "
        "shape produced by the matching /export endpoint. The whole import is one all-or-nothing "
        "transaction: if any row fails validation or references a missing foreign key, nothing is "
        "written and the errors are returned. Use dry_run=true to validate without committing."
    ),
)
async def import_entity(
    *,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    entity: str,
    fmt: Annotated[ImportFormat, Query(description="Body format.")],
    mode: Annotated[ImportMode, Query(description="How to treat rows whose id already exists.")] = ImportMode.CREATE,
    dry_run: Annotated[bool, Query(description="Validate and report counts without committing.")] = False,
) -> ImportResponse:
    if entity not in _PARAMS:
        return ImportResponse(created=0, updated=0, skipped=0, dry_run=dry_run, errors=[f"Unknown entity '{entity}'."])

    raw = (await request.body()).decode("utf-8")
    try:
        rows = parse_body(raw, fmt)
    except (ValueError, UnicodeDecodeError) as exc:
        return ImportResponse(created=0, updated=0, skipped=0, dry_run=dry_run, errors=[f"Could not parse body: {exc}"])

    params_model = _PARAMS[entity]
    fk_map = _FK_MAP[entity]
    ignore = _IGNORE[entity]
    builder = _BUILDERS[entity]
    orm_model = _MODELS[entity]

    result = ImportResult(dry_run=dry_run)

    for index, row in enumerate(rows):
        try:
            parsed = unflatten_row(row, fk_map=fk_map, ignore=ignore)
            validated = params_model.model_validate(parsed.params)
            data = validated.model_dump(exclude_unset=True)

            existing = None
            if parsed.source_id is not None and mode != ImportMode.CREATE:
                existing = await db.get(orm_model, parsed.source_id)

            if existing is not None and mode == ImportMode.SKIP_EXISTING:
                result.skipped += 1
                continue

            obj = await builder(db, data, existing)
            db.add(obj)
            if existing is not None:
                result.updated += 1
            else:
                result.created += 1
        except (ValidationError, ValueError, LookupError) as exc:
            result.errors.append(f"Row {index}: {exc}")

    if result.errors and not dry_run:
        # All-or-nothing: a real run that hit any error applied nothing, so report zero counts.
        await db.rollback()
        result.created = 0
        result.updated = 0
        result.skipped = 0
    elif dry_run:
        # Nothing is committed, but the counts report what a real run would have applied.
        await db.rollback()
    else:
        await db.commit()

    return ImportResponse(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        dry_run=result.dry_run,
        errors=result.errors,
    )
