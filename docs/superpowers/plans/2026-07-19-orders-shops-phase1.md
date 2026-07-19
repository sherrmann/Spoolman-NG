# Orders, Shops & Purchase Options — PR 0 (revert) + Phase 1 (Spoolman core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revert the unreleased #309 flat filament order fields, then add first-class **Shop**, **Order**, and **OrderLine** entities to Spoolman core with `/shop` and `/order` CRUD, an order `arrive` endpoint (per-line arrival + quantity splitting + spool creation), and a derived `on_order` computed field on filaments.

**Architecture:** New SQLAlchemy tables mirror the existing entity conventions in `spoolman/database/models.py` (plain `String`/`Text`/`Integer`/`Float` columns, a `registered` timestamp, no native JSON/ARRAY columns). Each entity gets a thin FastAPI router (`spoolman/api/v1/<name>.py`) delegating to a database helper module (`spoolman/database/<name>.py`), Pydantic request/response models in `spoolman/api/v1/models.py`, and a websocket event type — exactly the vendor/location pattern. "On order" state is **derived at read time** from un-arrived order lines, never stored on the filament. `ships_to` is stored as a comma-separated string and serialized to/from a JSON array at the API edge. Order state (`open`/`arrived`) is derived from its lines, not stored.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async (`Mapped[...]` / `mapped_column`), Alembic 1.15, Pydantic v2, pytest + pytest-asyncio (in-process integration harness over throwaway SQLite), ruff 0.14.10. Client: React + react-admin + TypeScript (client API-model additions only in this plan; UI is mockup-gated).

## Global Constraints

- **Wire-compatibility with upstream Spoolman v1 REST/WS API is a hard constraint.** Everything is additive; PR 0 removes the unreleased #309 fields before any release wires them into the stable API.
- **No native JSON/ARRAY columns.** Lists (e.g. `ships_to`) are stored as comma-separated strings in a `Text` column and serialized to/from a JSON array at the API edge.
- **`registered` timestamps** are set with `datetime.utcnow().replace(microsecond=0)`; datetimes coming in from the API are normalized with `utc_timezone_naive(...)` before storage.
- **Reserved SQL words:** the `Order` entity's table is named `purchase_order` (not `order`, which is reserved in PostgreSQL/MySQL/CockroachDB), mirroring the existing `User` → `user_account` precedent (#52).
- **SQLite does not enforce foreign keys in this codebase** (no `PRAGMA foreign_keys=ON` is set — see `spoolman/database/database.py`). Deletion **restrictions** must therefore be enforced with an explicit application-level count check, not by catching a DB `IntegrityError`. UNIQUE constraints *are* enforced by SQLite and may be relied on.
- **Aggregates / derived fields** (`spool_count`, `remaining_weight`, `on_order`) are populated **only** on an entity's own list and detail endpoints and are `null` in nested and websocket payloads — mirror `Filament.get_aggregates`.
- **Lint/format before every commit:** run BOTH `uv run ruff check spoolman/ migrations/ tests/` AND `uv run ruff format spoolman/ migrations/ tests/`. The CI style job enforces both.
- **Tests:** `uv run pytest tests/integration/<file> -q` (asyncio_mode is `auto`; no `@pytest.mark.asyncio` needed). The harness (`tests/integration/conftest.py`) creates the schema with `Base.metadata.create_all` and mounts each router explicitly — **new routers must be added to the conftest `client` fixture** or their endpoints 404 in tests.
- **Commit trailer** on every commit: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **One branch + PR + squash-merge per shippable unit.** Changelog bullets go in `CHANGELOG.md` under `## Unreleased`.
- **UI is gated:** per project rule, UI implementation happens only after mockup review and Sam's approval. Task 7 is a hard MOCKUP GATE that STOPS. Tasks 8+ (UI) must not begin until approval.

---

## File Structure

**PR 0 (Task 1) — revert #309** (branch `claude/orders-pr0`, its own PR):
- Modify: `spoolman/database/models.py` (remove 3 filament columns)
- Delete: `migrations/versions/2026_07_19_1500-e8b3c6d9f2a5_filament_order_fields.py`
- Modify: `spoolman/api/v1/models.py` (remove 3 Filament fields + from_db kwargs)
- Modify: `spoolman/api/v1/filament.py` (remove 3 FilamentParameters fields + create kwargs)
- Modify: `spoolman/database/filament.py` (remove create kwargs + constructor entries)
- Delete: `tests/integration/test_filament_order_fields.py`
- Modify: `CHANGELOG.md`

**Phase 1 (Tasks 2–6)** (branch `claude/orders-shops-phase1`, its own PR):
- Modify: `spoolman/database/models.py` — add `Shop`, `Order`, `OrderLine` classes
- Create: `migrations/versions/2026_07_19_1600-f2a9c7e4b1d8_shop_tables.py`
- Create: `migrations/versions/2026_07_19_1700-a3b8d6f1c9e2_order_tables.py`
- Modify: `spoolman/api/v1/models.py` — add `Shop`, `ShopEvent`, `OrderLine`, `Order`, `OrderEvent`, `OnOrderInfo`; add `on_order` to `Filament`
- Create: `spoolman/database/shop.py`, `spoolman/api/v1/shop.py`
- Create: `spoolman/database/order.py`, `spoolman/api/v1/order.py`
- Modify: `spoolman/database/filament.py` — `get_on_order` helper + filament-delete restriction; `spoolman/api/v1/filament.py` — wire `on_order` into find/get
- Modify: `spoolman/api/v1/router.py` and `tests/integration/conftest.py` — mount the two new routers
- Create: `tests/integration/test_shop.py`, `tests/integration/test_order.py`, `tests/integration/test_order_arrive.py`, `tests/integration/test_filament_on_order.py`
- Modify: `client/src/pages/filaments/model.tsx`; Create: `client/src/pages/orders/model.tsx`
- Modify: `CHANGELOG.md`

**Phase 1 UI (Tasks 7–12)** — mockup-gated; file lists given per task.

---

## Task 1 (PR 0): Revert the unreleased #309 filament order fields

**Branch:** `claude/orders-pr0` (its own PR, squash-merged before Phase 1 starts).

**Files:**
- Modify: `spoolman/database/models.py:86-97`
- Delete: `migrations/versions/2026_07_19_1500-e8b3c6d9f2a5_filament_order_fields.py`
- Modify: `spoolman/api/v1/models.py:431-448` and `:516-518`
- Modify: `spoolman/api/v1/filament.py:193-212` and `:614-616`
- Modify: `spoolman/database/filament.py:63-65` and `:106-108`
- Delete: `tests/integration/test_filament_order_fields.py`
- Modify: `CHANGELOG.md:7`

**Interfaces:**
- Produces: a `filament` table and `Filament` API model with NO `ordered_at`/`order_url`/`order_note`; the Alembic head returns to `d4e7a1b9c6f2`.

- [ ] **Step 1: Confirm the current head and full green baseline**

Run:
```bash
cd /home/sam/spoolman/Spoolman
git checkout master && git checkout -b claude/orders-pr0
uv run alembic heads
uv run pytest tests/integration -q
```
Expected: `alembic heads` prints `e8b3c6d9f2a5 (head)`; pytest all pass. (This establishes the pre-revert baseline. The revert's real test is that everything stays green after removal.)

- [ ] **Step 2: Delete the #309 test file (it must fail to import against the reverted code)**

Run:
```bash
git rm tests/integration/test_filament_order_fields.py
```
Expected: file removed.

- [ ] **Step 3: Remove the three columns from the `Filament` DB model**

In `spoolman/database/models.py`, delete these lines (currently 86–97, immediately after the `label_printed_at` column):
```python
    ordered_at: Mapped[datetime | None] = mapped_column(
        comment="When a replenishment order was placed for this filament (#298). Null means nothing on order; "
        "doubles as the boolean and as the age of the order.",
    )
    order_url: Mapped[str | None] = mapped_column(
        String(1024),
        comment="Link to the (bulk) order that replenishes this filament (#298).",
    )
    order_note: Mapped[str | None] = mapped_column(
        String(1024),
        comment="Free-text order details (#298): order number, quantity, supplier.",
    )
```
Leave the `extra: Mapped[list["FilamentField"]]` relationship that follows untouched.

- [ ] **Step 4: Remove the three fields from the `Filament` API response model**

In `spoolman/api/v1/models.py`, delete the three `Field` definitions (currently 431–448, between `label_printed_at` and `spool_count`):
```python
    ordered_at: SpoolmanDateTime | None = Field(
        None,
        description=(
            "When a replenishment order was placed for this filament. Null means nothing on order. UTC Timezone."
        ),
    )
    order_url: str | None = Field(
        None,
        max_length=1024,
        description="Link to the (bulk) order that replenishes this filament.",
        examples=["https://shop.example.com/orders/4711"],
    )
    order_note: str | None = Field(
        None,
        max_length=1024,
        description="Free-text order details: order number, quantity, supplier.",
        examples=["3 spools, order #4711"],
    )
```
And in the same file's `Filament.from_db`, delete these three kwargs (currently 516–518):
```python
            ordered_at=item.ordered_at,
            order_url=item.order_url,
            order_note=item.order_note,
```

- [ ] **Step 5: Remove the three fields from `FilamentParameters` and the create endpoint**

In `spoolman/api/v1/filament.py`, delete the three `Field` definitions from `FilamentParameters` (currently 193–212, between `reserve_count` and `extra`):
```python
    ordered_at: datetime | None = Field(
        None,
        description=(
            "When a replenishment order was placed for this filament (#298). Null means nothing on order; "
            "pass null on update to clear. UTC Timezone."
        ),
        examples=["2026-07-19T09:00:00Z"],
    )
    order_url: str | None = Field(
        None,
        max_length=1024,
        description="Link to the (bulk) order that replenishes this filament. Pass null on update to clear.",
        examples=["https://shop.example.com/orders/4711"],
    )
    order_note: str | None = Field(
        None,
        max_length=1024,
        description="Free-text order details: order number, quantity, supplier. Pass null on update to clear.",
        examples=["3 spools, order #4711"],
    )
```
And in the `create` endpoint, delete these three kwargs (currently 614–616, in the `filament.create(...)` call):
```python
        ordered_at=body.ordered_at,
        order_url=body.order_url,
        order_note=body.order_note,
```
Do NOT remove `from datetime import datetime` at the top — it is still used by `FilamentUpdateParameters.label_printed_at`.

- [ ] **Step 6: Remove the plumbing from `spoolman/database/filament.py`**

In `spoolman/database/filament.py`, delete these three `create()` keyword parameters (currently 63–65):
```python
    ordered_at: datetime | None = None,
    order_url: str | None = None,
    order_note: str | None = None,
```
And delete these three constructor entries in the `models.Filament(...)` call (currently 106–108):
```python
        ordered_at=utc_timezone_naive(ordered_at) if ordered_at is not None else None,
        order_url=order_url,
        order_note=order_note,
```
Do NOT remove the `utc_timezone_naive` import — it is still used in `update()` (`setattr(filament, k, utc_timezone_naive(v))`). Do NOT remove `from datetime import datetime` — still used for `registered=datetime.utcnow()...`.

- [ ] **Step 7: Delete the #309 migration file**

Run:
```bash
git rm migrations/versions/2026_07_19_1500-e8b3c6d9f2a5_filament_order_fields.py
```
Expected: file removed. The head migration is now `d4e7a1b9c6f2` (user_accounts), whose `down_revision` chain is intact.

- [ ] **Step 8: Update the CHANGELOG**

In `CHANGELOG.md`, under `## Unreleased`, delete the existing bullet (currently line 7):
```markdown
- **API: filament 'ordered' state** (#298, backend half) — three additive nullable fields on filament: `ordered_at`, `order_url`, `order_note`. Settable at create or PATCH, cleared with explicit `null`; integrations (e.g. the HA integration's low-stock notifications) can now detect that replenishment is already on its way. UI lands separately.
```
and add, as the first bullet under `## Unreleased`:
```markdown
- **Reverted the unreleased filament 'ordered' fields** (#298/#309) — the three flat `ordered_at`/`order_url`/`order_note` columns that landed unreleased in #309 modelled order state as a property of a product type (couldn't group a bulk order, capture arrival into spools, or hold a shop). They are removed before any release wired them into the stable v1 API, and superseded by first-class **Orders & Shops** (Phase 1, below).
```

- [ ] **Step 9: Verify the Alembic head and a fresh upgrade**

Run:
```bash
uv run alembic heads
tmp=$(mktemp -d); SPOOLMAN_DIR_DATA="$tmp" uv run alembic upgrade head; SPOOLMAN_DIR_DATA="$tmp" uv run alembic current
```
Expected: `alembic heads` prints `d4e7a1b9c6f2 (head)`; `alembic upgrade head` runs with no error and creates `$tmp/spoolman.db`; `alembic current` prints `d4e7a1b9c6f2 (head)`.

- [ ] **Step 10: Run the full integration suite**

Run:
```bash
uv run pytest tests/integration -q
```
Expected: all pass, and `test_filament_order_fields.py` is gone so nothing references the removed fields.

- [ ] **Step 11: Lint, format, commit**

Run:
```bash
uv run ruff check spoolman/ migrations/ tests/
uv run ruff format spoolman/ migrations/ tests/
git add -A
git commit -m "revert(#298/#309): drop unreleased flat filament order fields

Superseded by first-class Orders & Shops (Phase 1). Removes the three
filament columns, the e8b3c6d9f2a5 migration, the API fields, the DB
plumbing, and the #309 test file; Alembic head is back to d4e7a1b9c6f2.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: ruff check passes with no findings; format reports no changes; commit succeeds. Open this as its own PR and squash-merge before starting Task 2.

---

## Task 2: Shop entity — table, migration, `/shop` CRUD with WS events

**Branch:** `claude/orders-shops-phase1` (branch from master AFTER PR 0 is merged). Tasks 2–6 land on this branch as one PR.

**Files:**
- Modify: `spoolman/database/models.py` (add `Shop` class after `Vendor`)
- Create: `migrations/versions/2026_07_19_1600-f2a9c7e4b1d8_shop_tables.py`
- Modify: `spoolman/api/v1/models.py` (add `Shop` model + `ShopEvent`)
- Create: `spoolman/database/shop.py`
- Create: `spoolman/api/v1/shop.py`
- Modify: `spoolman/api/v1/router.py` (mount `shop.router`)
- Modify: `tests/integration/conftest.py` (mount `shop.router`)
- Test: `tests/integration/test_shop.py`

**Interfaces:**
- Produces:
  - `models.Shop` — columns `id`, `registered`, `name` (unique), `homepage`, `ships_to` (comma-joined str), `comment`; relationship `orders` (back-populated by `Order.shop`, added in Task 3).
  - API `Shop` Pydantic model with `ships_to: list[str] | None` on the wire; `Shop.from_db(item) -> Shop`.
  - `spoolman.database.shop`: `create(*, db, name, homepage=None, ships_to=None, comment=None) -> models.Shop` (raises `ItemCreateError` on duplicate name), `get_by_id(db, shop_id) -> models.Shop`, `find(*, db, name=None, sort_by=None, limit=None, offset=0) -> tuple[list, int]`, `update(*, db, shop_id, data) -> models.Shop` (raises `ItemCreateError` on duplicate name), `delete(db, shop_id) -> None` (raises `ItemDeleteError` when orders reference it — enforced in Task 3), `shop_changed(shop, typ)`.
  - Router `spoolman/api/v1/shop.py` mounted at `/shop`.

- [ ] **Step 1: Write the failing Shop CRUD + serialization test**

Create `tests/integration/test_shop.py`:
```python
"""Integration tests for the Shop entity (#298 Phase 1).

A shop is where a reorder is placed: a unique name, an optional homepage, a free-form
list of regions it ships to (stored comma-separated, exposed as a JSON array), and a
comment. CRUD mirrors /vendor, plus a unique-name conflict and the ships_to array edge.
"""

from httpx import AsyncClient

SHOP = "/api/v1/shop"


async def test_shop_crud_round_trip(client: AsyncClient):
    created = (
        await client.post(
            SHOP,
            json={"name": "3DJake", "homepage": "https://3djake.com", "ships_to": ["CH", "EU"], "comment": "fast"},
        )
    ).json()
    assert created["name"] == "3DJake"
    assert created["homepage"] == "https://3djake.com"
    assert created["ships_to"] == ["CH", "EU"]
    assert created["comment"] == "fast"
    shop_id = created["id"]

    got = await client.get(f"{SHOP}/{shop_id}")
    assert got.status_code == 200
    assert got.json()["ships_to"] == ["CH", "EU"]

    listed = await client.get(SHOP)
    assert listed.status_code == 200
    assert listed.headers["x-total-count"] == "1"
    assert [s["name"] for s in listed.json()] == ["3DJake"]

    patched = await client.patch(f"{SHOP}/{shop_id}", json={"name": "3DJake DE", "ships_to": ["DE"]})
    assert patched.status_code == 200
    assert patched.json()["name"] == "3DJake DE"
    assert patched.json()["ships_to"] == ["DE"]

    deleted = await client.delete(f"{SHOP}/{shop_id}")
    assert deleted.status_code == 200
    empty = await client.get(SHOP)
    assert empty.headers["x-total-count"] == "0"
    assert empty.json() == []


async def test_shop_name_is_unique(client: AsyncClient):
    assert (await client.post(SHOP, json={"name": "Prusa"})).status_code == 200
    dup = await client.post(SHOP, json={"name": "Prusa"})
    assert dup.status_code == 409, dup.text


async def test_shop_ships_to_absent_when_unset(client: AsyncClient):
    created = (await client.post(SHOP, json={"name": "Bare"})).json()
    # response_model_exclude_none drops null ships_to entirely.
    assert "ships_to" not in created
    assert (await client.get(f"{SHOP}/{created['id']}")).json().get("ships_to") is None


async def test_shop_ships_to_empty_list_stored_as_null(client: AsyncClient):
    created = (await client.post(SHOP, json={"name": "Empty", "ships_to": []})).json()
    assert "ships_to" not in created
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_shop.py -q`
Expected: FAIL — `/api/v1/shop` 404s (router not mounted) / `models.Shop` does not exist.

- [ ] **Step 3: Add the `Shop` DB model**

In `spoolman/database/models.py`, add this class immediately after the `Vendor` class (after line 29, before `class Filament`):
```python
class Shop(Base):
    """A shop where filament is (re)ordered (#298). Distinct from Vendor (the manufacturer).

    ``ships_to`` is a comma-separated list of free-form region strings (e.g. ``"CH,EU,DE"``), stored
    in a Text column because the schema has no JSON/list columns; it is serialized to/from a JSON
    array at the API edge. ``name`` is unique so inline shop autocomplete can dedupe.
    """

    __tablename__ = "shop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    homepage: Mapped[str | None] = mapped_column(String(1024))
    ships_to: Mapped[str | None] = mapped_column(
        Text(),
        comment="Comma-separated free-form region codes this shop ships to (e.g. 'CH,EU,DE'). "
        "Serialized to/from a JSON array at the API edge. Null means unspecified.",
    )
    comment: Mapped[str | None] = mapped_column(String(1024))
    orders: Mapped[list["Order"]] = relationship(back_populates="shop")
```
(`Order` is defined in Task 3; the string forward-reference resolves at mapper-configuration time, which happens after both are imported.)

- [ ] **Step 4: Add the `Shop` API model and `ShopEvent`**

In `spoolman/api/v1/models.py`, add the `Shop` model immediately after the `Vendor` class (after line 158):
```python
class Shop(BaseModel):
    id: int = Field(description="Unique internal ID of this shop.")
    registered: SpoolmanDateTime = Field(description="When the shop was registered in the database. UTC Timezone.")
    name: str = Field(max_length=64, description="Shop name (unique).", examples=["3DJake"])
    homepage: str | None = Field(
        None,
        max_length=1024,
        description="Shop homepage URL.",
        examples=["https://3djake.com"],
    )
    ships_to: list[str] | None = Field(
        None,
        description=(
            "Free-form region codes this shop ships to, e.g. ['CH', 'EU', 'DE']. Null/absent means unspecified. "
            "Stored server-side as a comma-separated string."
        ),
        examples=[["CH", "EU"]],
    )
    comment: str | None = Field(
        None,
        max_length=1024,
        description="Free text comment about this shop.",
        examples=[""],
    )

    @staticmethod
    def from_db(item: models.Shop) -> "Shop":
        """Create a Pydantic shop object from a database shop object."""
        return Shop(
            id=item.id,
            registered=item.registered,
            name=item.name,
            homepage=item.homepage,
            ships_to=item.ships_to.split(",") if item.ships_to else None,
            comment=item.comment,
        )
```
And add `ShopEvent` next to the other `*Event` classes (after `VendorEvent`, ~line 802):
```python
class ShopEvent(Event):
    """Event."""

    payload: Shop = Field(description="Updated shop.")
    resource: Literal["shop"] = Field(description="Resource type.")
```

- [ ] **Step 5: Create the Shop database helper**

Create `spoolman/database/shop.py`:
```python
"""Helper functions for interacting with shop database objects (#298)."""

import logging
from datetime import datetime

import sqlalchemy
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import EventType, Shop, ShopEvent
from spoolman.database import models
from spoolman.database.utils import SortOrder, add_where_clause_str, order_by_expression
from spoolman.exceptions import ItemCreateError, ItemDeleteError, ItemNotFoundError
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)


def _join_ships_to(ships_to: list[str] | None) -> str | None:
    """Serialize a region list to the stored comma-separated string. Empty list -> None."""
    if not ships_to:
        return None
    return ",".join(ships_to)


async def create(
    *,
    db: AsyncSession,
    name: str,
    homepage: str | None = None,
    ships_to: list[str] | None = None,
    comment: str | None = None,
) -> models.Shop:
    """Add a new shop to the database. Raises ItemCreateError on a duplicate name."""
    shop = models.Shop(
        name=name,
        registered=datetime.utcnow().replace(microsecond=0),
        homepage=homepage,
        ships_to=_join_ships_to(ships_to),
        comment=comment,
    )
    db.add(shop)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ItemCreateError(f"A shop named '{name}' already exists.") from exc
    await shop_changed(shop, EventType.ADDED)
    return shop


async def get_by_id(db: AsyncSession, shop_id: int) -> models.Shop:
    """Get a shop object from the database by the unique ID."""
    shop = await db.get(models.Shop, shop_id)
    if shop is None:
        raise ItemNotFoundError(f"No shop with ID {shop_id} found.")
    return shop


async def find(
    *,
    db: AsyncSession,
    name: str | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Shop], int]:
    """Find a list of shop objects by search criteria.

    Returns a tuple of (items, total count of matching items).
    """
    stmt = select(models.Shop)
    stmt = add_where_clause_str(stmt, models.Shop.name, name)

    total_count = None
    if sort_by is not None:
        for fieldstr, order in sort_by.items():
            field = getattr(models.Shop, fieldstr)
            stmt = stmt.order_by(order_by_expression(field, order))

    if limit is not None:
        total_count_stmt = stmt.with_only_columns(func.count(), maintain_column_froms=True).order_by(None)
        total_count = (await db.execute(total_count_stmt)).scalar()
        stmt = stmt.offset(offset).limit(limit)

    rows = await db.execute(stmt, execution_options={"populate_existing": True})
    result = list(rows.unique().scalars().all())
    if total_count is None:
        total_count = len(result)
    return result, total_count


async def update(*, db: AsyncSession, shop_id: int, data: dict) -> models.Shop:
    """Update the fields of a shop object. Raises ItemCreateError on a duplicate name."""
    shop = await get_by_id(db, shop_id)
    for k, v in data.items():
        if k == "ships_to":
            shop.ships_to = _join_ships_to(v)
        else:
            setattr(shop, k, v)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ItemCreateError(f"A shop named '{data.get('name')}' already exists.") from exc
    await shop_changed(shop, EventType.UPDATED)
    return shop


async def delete(db: AsyncSession, shop_id: int) -> None:
    """Delete a shop object.

    Restricted while any order references the shop (#298). FKs are not enforced on SQLite in this
    codebase, so the reference is checked explicitly rather than via a DB IntegrityError.
    """
    shop = await get_by_id(db, shop_id)
    order_count = await db.scalar(
        select(func.count(models.Order.id)).where(models.Order.shop_id == shop_id),
    )
    if order_count:
        raise ItemDeleteError(f"Cannot delete shop {shop_id}: {order_count} order(s) reference it.")
    await db.delete(shop)
    await db.commit()
    await shop_changed(shop, EventType.DELETED)


async def shop_changed(shop: models.Shop, typ: EventType) -> None:
    """Notify websocket clients that a shop has changed."""
    try:
        await websocket_manager.send(
            ("shop", str(shop.id)),
            ShopEvent(
                type=typ,
                resource="shop",
                date=datetime.utcnow(),
                payload=Shop.from_db(shop),
            ),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")
```
(`models.Order` is referenced only inside `delete`; the class exists after Task 3. This module is imported at app start, after `models` is fully defined, so the attribute access is safe.)

- [ ] **Step 6: Create the Shop router**

Create `spoolman/api/v1/shop.py`:
```python
"""Shop related endpoints (#298)."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import Message, Shop, ShopEvent
from spoolman.database import shop
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.exceptions import ItemCreateError, ItemDeleteError
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/shop",
    tags=["shop"],
)

# ruff: noqa: D103


class ShopParameters(BaseModel):
    name: str = Field(max_length=64, description="Shop name (unique).", examples=["3DJake"])
    homepage: str | None = Field(None, max_length=1024, description="Shop homepage URL.", examples=["https://3djake.com"])
    ships_to: list[str] | None = Field(
        None,
        description="Free-form region codes this shop ships to, e.g. ['CH', 'EU'].",
        examples=[["CH", "EU"]],
    )
    comment: str | None = Field(None, max_length=1024, description="Free text comment about this shop.", examples=[""])


class ShopUpdateParameters(ShopParameters):
    name: str | None = Field(None, max_length=64, description="Shop name (unique).", examples=["3DJake"])

    @field_validator("name")
    @classmethod
    def prevent_none(cls: type["ShopUpdateParameters"], v: str | None) -> str | None:
        """Prevent name from being None."""
        if v is None:
            raise ValueError("Value must not be None.")
        return v


@router.get(
    "",
    name="Find shop",
    description=(
        "Get a list of shops that matches the search query. "
        "A websocket is served on the same path to listen for updates to any shop, or added or deleted shops. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={200: {"model": list[Shop]}, 299: {"model": ShopEvent, "description": "Websocket message"}},
)
async def find(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[
        str | None,
        Query(
            title="Shop Name",
            description=(
                "Partial case-insensitive search term for the shop name. Separate multiple terms with a comma. "
                "Surround a term with quotes to search for the exact term."
            ),
        ),
    ] = None,
    sort: Annotated[
        str | None,
        Query(
            title="Sort",
            description='Sort by the given field. Comma-separated string of "field:direction" items.',
            examples=["name:asc,id:desc"],
        ),
    ] = None,
    limit: Annotated[int | None, Query(title="Limit", description="Maximum number of items in the response.")] = None,
    offset: Annotated[int, Query(title="Offset", description="Offset in the full result set if a limit is set.")] = 0,
) -> JSONResponse:
    try:
        sort_by = parse_sort(sort)
        db_items, total_count = await shop.find(db=db, name=name, sort_by=sort_by, limit=limit, offset=offset)
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())

    shops_out = [Shop.from_db(db_item) for db_item in db_items]
    return JSONResponse(
        content=jsonable_encoder(shops_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket("", name="Listen to shop changes")
async def notify_any(websocket: WebSocket) -> None:
    await websocket.accept()
    websocket_manager.connect(("shop",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("shop",), websocket)


@router.get(
    "/{shop_id}",
    name="Get shop",
    description=(
        "Get a specific shop. A websocket is served on the same path to listen for changes to the shop. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": ShopEvent, "description": "Websocket message"}},
)
async def get(db: Annotated[AsyncSession, Depends(get_db_session)], shop_id: int) -> Shop:
    db_item = await shop.get_by_id(db, shop_id)
    return Shop.from_db(db_item)


@router.websocket("/{shop_id}", name="Listen to shop changes")
async def notify(websocket: WebSocket, shop_id: int) -> None:
    await websocket.accept()
    websocket_manager.connect(("shop", str(shop_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("shop", str(shop_id)), websocket)


@router.post(
    "",
    name="Add shop",
    description="Add a new shop to the database.",
    response_model_exclude_none=True,
    response_model=Shop,
    responses={409: {"model": Message}},
)
async def create(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: ShopParameters,
):
    try:
        db_item = await shop.create(
            db=db,
            name=body.name,
            homepage=body.homepage,
            ships_to=body.ships_to,
            comment=body.comment,
        )
    except ItemCreateError as e:
        return JSONResponse(status_code=409, content=Message(message=str(e)).model_dump())
    return Shop.from_db(db_item)


@router.patch(
    "/{shop_id}",
    name="Update shop",
    description="Update any attribute of a shop. Only fields specified in the request will be affected.",
    response_model_exclude_none=True,
    response_model=Shop,
    responses={404: {"model": Message}, 409: {"model": Message}},
)
async def update(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    shop_id: int,
    body: ShopUpdateParameters,
):
    patch_data = body.model_dump(exclude_unset=True)
    try:
        db_item = await shop.update(db=db, shop_id=shop_id, data=patch_data)
    except ItemCreateError as e:
        return JSONResponse(status_code=409, content=Message(message=str(e)).model_dump())
    return Shop.from_db(db_item)


@router.delete(
    "/{shop_id}",
    name="Delete shop",
    description="Delete a shop. Rejected with 409 while any order references it.",
    responses={404: {"model": Message}, 409: {"model": Message}},
)
async def delete(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    shop_id: int,
):
    try:
        await shop.delete(db, shop_id)
    except ItemDeleteError as e:
        return JSONResponse(status_code=409, content=Message(message=str(e)).model_dump())
    return Message(message="Success!")
```

- [ ] **Step 7: Mount the router in the app and the test harness**

In `spoolman/api/v1/router.py`, add `shop` to the `from . import (...)` block (alphabetically, after `setting,`), and add `app.include_router(shop.router)` next to the other `include_router` calls (after `app.include_router(vendor.router)`).

In `tests/integration/conftest.py`, add `shop` to the `from spoolman.api.v1 import (...)` block and add `app.include_router(shop.router, prefix="/api/v1")` next to the others (after the `vendor.router` line).

- [ ] **Step 8: Run the Shop test to verify it passes**

Run: `uv run pytest tests/integration/test_shop.py -q`
Expected: PASS (all 4 tests). The `test_shop_name_is_unique` case relies on SQLite enforcing the UNIQUE index (it does).

- [ ] **Step 9: Run the whole suite to check for regressions**

Run: `uv run pytest tests/integration -q`
Expected: all pass (the forward-reference to `models.Order` in `shop.py`/`models.Shop` is resolved because Task 3 has not run yet — see note below).

> **If Step 9 fails at import time** because `Order`/`models.Order` doesn't exist yet: that is expected only if you run Task 2 in isolation. `models.Shop.orders` is a string forward-reference (`list["Order"]`) evaluated lazily at mapper configuration, and `shop.delete`'s `models.Order` access only runs at delete time — but SQLAlchemy configures mappers on first use, so the `orders` relationship needs `Order` to exist. **Do Task 2 and Task 3 as a pair before running the full suite / committing**, or temporarily comment the `orders` relationship. The recommended order: complete Steps 1–8 here (test_shop passes because it never triggers the `orders` relationship nor a shop delete-with-order), then proceed directly to Task 3, and commit both together at the end of Task 3 if the mapper error appears. Re-run this step after Task 3.

- [ ] **Step 10: Lint, format**

Run:
```bash
uv run ruff check spoolman/ migrations/ tests/
uv run ruff format spoolman/ migrations/ tests/
```
Expected: clean.

- [ ] **Step 11: Write the Shop migration**

Create `migrations/versions/2026_07_19_1600-f2a9c7e4b1d8_shop_tables.py`:
```python
"""shop_tables.

Revision ID: f2a9c7e4b1d8
Revises: d4e7a1b9c6f2
Create Date: 2026-07-19 16:00:00.000000

Adds the first-class ``shop`` table (#298): where a reorder is placed, distinct from the manufacturer
Vendor. ``name`` is unique; ``ships_to`` is a comma-separated region list in a Text column (no JSON
columns in this schema). Purely additive — nothing existing references it.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f2a9c7e4b1d8"
down_revision = "d4e7a1b9c6f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the shop table."""
    op.create_table(
        "shop",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("homepage", sa.String(length=1024), nullable=True),
        sa.Column("ships_to", sa.Text(), nullable=True),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shop_id"), "shop", ["id"], unique=False)
    op.create_index(op.f("ix_shop_name"), "shop", ["name"], unique=True)


def downgrade() -> None:
    """Drop the shop table."""
    op.drop_index(op.f("ix_shop_name"), table_name="shop")
    op.drop_index(op.f("ix_shop_id"), table_name="shop")
    op.drop_table("shop")
```

- [ ] **Step 12: Add a CHANGELOG bullet**

In `CHANGELOG.md`, under `## Unreleased` (after the Task-1 revert bullet), add:
```markdown
- **New: Shops** (#298) — a first-class `/shop` entity (name, homepage, region ships-to list, comment), distinct from the manufacturer Vendor, for tracking where filament is reordered.
```

- [ ] **Step 13: Commit (may be deferred to end of Task 3 — see Step 9 note)**

Run:
```bash
git add -A
git commit -m "feat(#298): Shop entity + /shop CRUD with WS events

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: commit succeeds. (If the mapper configuration error from the `orders` relationship blocks the full suite, complete Task 3 first and make this a single combined commit.)

---

## Task 3: Order + OrderLine entities — tables, migration, `/order` CRUD, deletion semantics

**Files:**
- Modify: `spoolman/database/models.py` (add `Order`, `OrderLine` after `Shop`)
- Create: `migrations/versions/2026_07_19_1700-a3b8d6f1c9e2_order_tables.py`
- Modify: `spoolman/api/v1/models.py` (add `OrderLine`, `Order`, `OrderEvent`)
- Create: `spoolman/database/order.py`
- Create: `spoolman/api/v1/order.py`
- Modify: `spoolman/api/v1/router.py`, `tests/integration/conftest.py` (mount `order.router`)
- Modify: `spoolman/database/filament.py` (restrict delete when order lines reference the filament)
- Test: `tests/integration/test_order.py`

**Interfaces:**
- Consumes: `models.Shop`, `shop.get_by_id` (Task 2); `models.Filament`.
- Produces:
  - `models.Order` (table `purchase_order`): `id`, `registered`, `shop_id` (nullable FK), `shop` relationship, `ordered_at` (NOT NULL), `order_number`, `url`, `comment`, `lines` relationship (cascade delete + delete-orphan).
  - `models.OrderLine` (table `order_line`): `id`, `order_id` (FK CASCADE), `order` rel, `filament_id` (FK, restrict), `filament` rel, `quantity` (int), `price_per_unit` (nullable float), `arrived_at` (nullable datetime).
  - API `Order` model with nested `lines: list[OrderLine]`, nested `shop: Shop | None`, and derived `state: Literal["open", "arrived"]`; `Order.from_db(item) -> Order`.
  - `spoolman.database.order`: `create(*, db, shop_id=None, ordered_at=None, order_number=None, url=None, comment=None, lines=None) -> models.Order`, `get_by_id`, `find`, `update(*, db, order_id, data, replace_lines) -> models.Order`, `delete`, `order_changed`. (`arrive` is added in Task 4.)
  - `filament.delete` now raises `ItemDeleteError` when an order line references the filament.

- [ ] **Step 1: Write the failing Order CRUD + deletion-semantics test**

Create `tests/integration/test_order.py`:
```python
"""Integration tests for the Order / OrderLine entities (#298 Phase 1).

An order groups the lines of one bulk reorder. State (open/arrived) is derived from the lines, not
stored. A PATCH that includes `lines` fully replaces the line set; omitting it leaves lines alone.
Deleting an order cascades its lines; deleting a shop referenced by an order, or a filament
referenced by an order line, is restricted.
"""

from httpx import AsyncClient

ORDER = "/api/v1/order"
SHOP = "/api/v1/shop"
FIL = "/api/v1/filament"


async def _filament(client: AsyncClient, name: str = "PLA") -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_order_crud_round_trip(client: AsyncClient):
    shop_id = (await client.post(SHOP, json={"name": "3DJake"})).json()["id"]
    fid = await _filament(client)

    created = (
        await client.post(
            ORDER,
            json={
                "shop_id": shop_id,
                "order_number": "4711",
                "lines": [{"filament_id": fid, "quantity": 2, "price_per_unit": 19.9}],
            },
        )
    ).json()
    assert created["shop"]["name"] == "3DJake"
    assert created["order_number"] == "4711"
    assert created["state"] == "open"
    assert len(created["lines"]) == 1
    assert created["lines"][0]["quantity"] == 2
    assert created["lines"][0]["price_per_unit"] == 19.9
    assert created["lines"][0]["arrived_at"] is None or "arrived_at" not in created["lines"][0]
    assert created["ordered_at"]  # defaulted to now
    order_id = created["id"]

    got = await client.get(f"{ORDER}/{order_id}")
    assert got.status_code == 200
    assert got.json()["state"] == "open"

    listed = await client.get(ORDER)
    assert listed.headers["x-total-count"] == "1"
    assert [o["id"] for o in listed.json()] == [order_id]


async def test_order_zero_lines_is_arrived_equivalent(client: AsyncClient):
    created = (await client.post(ORDER, json={"comment": "note only"})).json()
    assert created["lines"] == []
    assert created["state"] == "arrived"


async def test_patch_lines_full_replace(client: AsyncClient):
    fid_a = await _filament(client, "A")
    fid_b = await _filament(client, "B")
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid_a, "quantity": 1}]})).json()

    patched = await client.patch(
        f"{ORDER}/{order['id']}",
        json={"lines": [{"filament_id": fid_b, "quantity": 3}]},
    )
    assert patched.status_code == 200
    lines = patched.json()["lines"]
    assert len(lines) == 1
    assert lines[0]["filament_id"] == fid_b
    assert lines[0]["quantity"] == 3


async def test_patch_without_lines_leaves_them_untouched(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 2}]})).json()
    patched = await client.patch(f"{ORDER}/{order['id']}", json={"comment": "updated"})
    assert patched.status_code == 200
    assert patched.json()["comment"] == "updated"
    assert len(patched.json()["lines"]) == 1


async def test_delete_order_cascades_lines(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 2}]})).json()
    assert (await client.delete(f"{ORDER}/{order['id']}")).status_code == 200
    assert (await client.get(ORDER)).headers["x-total-count"] == "0"
    # The filament is now deletable — no order line references it anymore.
    assert (await client.delete(f"{FIL}/{fid}")).status_code == 200


async def test_delete_shop_restricted_while_order_references_it(client: AsyncClient):
    shop_id = (await client.post(SHOP, json={"name": "Locked"})).json()["id"]
    await client.post(ORDER, json={"shop_id": shop_id})
    blocked = await client.delete(f"{SHOP}/{shop_id}")
    assert blocked.status_code == 409, blocked.text


async def test_delete_filament_restricted_while_order_line_references_it(client: AsyncClient):
    fid = await _filament(client)
    await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 1}]})
    blocked = await client.delete(f"{FIL}/{fid}")
    assert blocked.status_code == 403, blocked.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_order.py -q`
Expected: FAIL — `/api/v1/order` 404s / `models.Order` does not exist.

- [ ] **Step 3: Add the `Order` and `OrderLine` DB models**

In `spoolman/database/models.py`, add both classes immediately after the `Shop` class:
```python
class Order(Base):
    """A grouped (bulk) reorder (#298).

    Table name ``purchase_order`` because ``order`` is a reserved SQL word (ORDER BY) in
    PostgreSQL/MySQL/CockroachDB — same reasoning as User -> ``user_account`` (#52). State
    (open/arrived) is DERIVED from the lines, never stored: open while any line is un-arrived.
    """

    __tablename__ = "purchase_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shop.id"))
    shop: Mapped[Optional["Shop"]] = relationship(back_populates="orders")
    ordered_at: Mapped[datetime] = mapped_column(comment="When the order was placed. Defaults to creation time.")
    order_number: Mapped[str | None] = mapped_column(String(256))
    url: Mapped[str | None] = mapped_column(String(1024))
    comment: Mapped[str | None] = mapped_column(String(1024))
    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )


class OrderLine(Base):
    """One filament line within an Order (#298).

    Arrival is tracked PER LINE (``arrived_at``) to support split shipments. No unique constraint on
    (order_id, filament_id): the same filament may appear twice — including as the arrived and
    still-outstanding halves of a split line. The filament FK has no cascade so deleting a filament
    referenced by a line is restricted (enforced in the application layer; see filament.delete).
    """

    __tablename__ = "order_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_order.id", ondelete="CASCADE"), index=True)
    order: Mapped["Order"] = relationship(back_populates="lines")
    filament_id: Mapped[int] = mapped_column(ForeignKey("filament.id"))
    filament: Mapped["Filament"] = relationship()
    quantity: Mapped[int] = mapped_column(comment="Number of spools ordered on this line. Always >= 1.")
    price_per_unit: Mapped[float | None] = mapped_column()
    arrived_at: Mapped[datetime | None] = mapped_column(
        comment="When this line arrived (#298). Null means still outstanding; per-line to support split shipments.",
    )
```

- [ ] **Step 4: Add the `OrderLine`, `Order`, and `OrderEvent` API models**

In `spoolman/api/v1/models.py`, add these classes immediately after the `Shop` model (before `Location`):
```python
class OrderLine(BaseModel):
    id: int = Field(description="Unique internal ID of this order line.")
    filament_id: int = Field(description="The filament type ordered on this line.")
    quantity: int = Field(ge=1, description="Number of spools ordered on this line.", examples=[2])
    price_per_unit: float | None = Field(
        None,
        ge=0,
        description="Price of one spool on this line, in the configured currency; copied to spool price on arrival.",
        examples=[19.9],
    )
    arrived_at: SpoolmanDateTime | None = Field(
        None,
        description="When this line arrived. Null means still outstanding. UTC Timezone.",
    )

    @staticmethod
    def from_db(item: models.OrderLine) -> "OrderLine":
        """Create a Pydantic order-line object from a database order-line object."""
        return OrderLine(
            id=item.id,
            filament_id=item.filament_id,
            quantity=item.quantity,
            price_per_unit=item.price_per_unit,
            arrived_at=item.arrived_at,
        )


class Order(BaseModel):
    id: int = Field(description="Unique internal ID of this order.")
    registered: SpoolmanDateTime = Field(description="When the order was registered in the database. UTC Timezone.")
    shop: Shop | None = Field(None, description="The shop this order was placed with.")
    ordered_at: SpoolmanDateTime = Field(description="When the order was placed. UTC Timezone.")
    order_number: str | None = Field(None, max_length=256, description="Shop order/reference number.", examples=["4711"])
    url: str | None = Field(None, max_length=1024, description="Link to the order.", examples=["https://.../orders/4711"])
    comment: str | None = Field(None, max_length=1024, description="Free text comment about this order.", examples=[""])
    lines: list[OrderLine] = Field(description="The lines of this order.")
    state: Literal["open", "arrived"] = Field(
        description=(
            "Derived state: 'open' while any line is un-arrived, otherwise 'arrived' (an order with zero lines "
            "is 'arrived'). Never stored."
        ),
        examples=["open"],
    )

    @staticmethod
    def from_db(item: models.Order) -> "Order":
        """Create a Pydantic order object from a database order object."""
        lines = [OrderLine.from_db(line) for line in item.lines]
        state = "open" if any(line.arrived_at is None for line in item.lines) else "arrived"
        return Order(
            id=item.id,
            registered=item.registered,
            shop=Shop.from_db(item.shop) if item.shop is not None else None,
            ordered_at=item.ordered_at,
            order_number=item.order_number,
            url=item.url,
            comment=item.comment,
            lines=lines,
            state=state,
        )
```
And add `OrderEvent` next to the other `*Event` classes (after `ShopEvent`):
```python
class OrderEvent(Event):
    """Event."""

    payload: Order = Field(description="Updated order.")
    resource: Literal["order"] = Field(description="Resource type.")
```

- [ ] **Step 5: Create the Order database helper**

Create `spoolman/database/order.py`:
```python
"""Helper functions for interacting with order database objects (#298)."""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from spoolman.api.v1.models import EventType, Order, OrderEvent
from spoolman.database import filament, models, shop
from spoolman.database.utils import SortOrder, add_where_clause_int_opt, order_by_expression, utc_timezone_naive
from spoolman.exceptions import ItemNotFoundError
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)


async def _build_lines(db: AsyncSession, lines: list[dict] | None) -> list[models.OrderLine]:
    """Build OrderLine rows from a list of line dicts, validating each filament FK exists."""
    built: list[models.OrderLine] = []
    for line in lines or []:
        # Validate the filament exists (clean 404 instead of a deferred FK error).
        await filament.get_by_id(db, line["filament_id"])
        built.append(
            models.OrderLine(
                filament_id=line["filament_id"],
                quantity=line.get("quantity", 1),
                price_per_unit=line.get("price_per_unit"),
                arrived_at=utc_timezone_naive(line["arrived_at"]) if line.get("arrived_at") is not None else None,
            ),
        )
    return built


async def create(
    *,
    db: AsyncSession,
    shop_id: int | None = None,
    ordered_at: datetime | None = None,
    order_number: str | None = None,
    url: str | None = None,
    comment: str | None = None,
    lines: list[dict] | None = None,
) -> models.Order:
    """Add a new order (with its lines) to the database."""
    shop_item: models.Shop | None = None
    if shop_id is not None:
        shop_item = await shop.get_by_id(db, shop_id)

    order = models.Order(
        registered=datetime.utcnow().replace(microsecond=0),
        shop=shop_item,
        ordered_at=utc_timezone_naive(ordered_at) if ordered_at is not None else datetime.utcnow().replace(microsecond=0),
        order_number=order_number,
        url=url,
        comment=comment,
        lines=await _build_lines(db, lines),
    )
    db.add(order)
    await db.commit()
    order = await get_by_id(db, order.id)
    await order_changed(order, EventType.ADDED)
    return order


async def get_by_id(db: AsyncSession, order_id: int) -> models.Order:
    """Get an order object from the database by the unique ID, with shop and lines loaded."""
    order = await db.get(models.Order, order_id, options=[joinedload("*")])
    if order is None:
        raise ItemNotFoundError(f"No order with ID {order_id} found.")
    return order


async def find(
    *,
    db: AsyncSession,
    shop_id: int | None = None,
    sort_by: dict[str, SortOrder] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[models.Order], int]:
    """Find a list of order objects. Returns (items, total count of matching items)."""
    stmt = select(models.Order).options(joinedload("*"))
    stmt = add_where_clause_int_opt(stmt, models.Order.shop_id, shop_id)

    total_count = None
    if sort_by is not None:
        for fieldstr, order in sort_by.items():
            field = getattr(models.Order, fieldstr)
            stmt = stmt.order_by(order_by_expression(field, order))

    if limit is not None:
        total_count_stmt = stmt.with_only_columns(func.count(models.Order.id.distinct()), maintain_column_froms=True).order_by(None)
        total_count = (await db.execute(total_count_stmt)).scalar()
        stmt = stmt.offset(offset).limit(limit)

    rows = await db.execute(stmt, execution_options={"populate_existing": True})
    result = list(rows.unique().scalars().all())
    if total_count is None:
        total_count = len(result)
    return result, total_count


async def update(*, db: AsyncSession, order_id: int, data: dict, replace_lines: bool) -> models.Order:
    """Update an order. When replace_lines is True, the line set is fully replaced by data['lines']."""
    order = await get_by_id(db, order_id)
    for k, v in data.items():
        if k == "lines":
            continue  # handled below
        if k == "shop_id":
            order.shop = await shop.get_by_id(db, v) if v is not None else None
        elif k == "ordered_at":
            order.ordered_at = utc_timezone_naive(v) if v is not None else order.ordered_at
        else:
            setattr(order, k, v)
    if replace_lines:
        # delete-orphan cascade removes the old lines when the collection is reassigned.
        order.lines = await _build_lines(db, data.get("lines"))
    await db.commit()
    order = await get_by_id(db, order_id)
    await order_changed(order, EventType.UPDATED)
    return order


async def delete(db: AsyncSession, order_id: int) -> None:
    """Delete an order. Its lines cascade (ORM delete-orphan + DB ON DELETE CASCADE)."""
    order = await get_by_id(db, order_id)
    await db.delete(order)
    await db.commit()
    await order_changed(order, EventType.DELETED)


async def order_changed(order: models.Order, typ: EventType) -> None:
    """Notify websocket clients that an order has changed."""
    try:
        await websocket_manager.send(
            ("order", str(order.id)),
            OrderEvent(
                type=typ,
                resource="order",
                date=datetime.utcnow(),
                payload=Order.from_db(order),
            ),
        )
    except Exception:
        # Important to have a catch-all here since we don't want to stop the call if this fails.
        logger.exception("Failed to send websocket message")
```

- [ ] **Step 6: Create the Order router**

Create `spoolman/api/v1/order.py`:
```python
"""Order related endpoints (#298)."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1.models import Message, Order, OrderEvent
from spoolman.database import order
from spoolman.database.database import get_db_session
from spoolman.database.utils import parse_sort
from spoolman.ws import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/order",
    tags=["order"],
)

# ruff: noqa: D103


class OrderLineParameters(BaseModel):
    filament_id: int = Field(description="The filament type ordered on this line.")
    quantity: int = Field(default=1, ge=1, description="Number of spools ordered on this line.", examples=[2])
    price_per_unit: float | None = Field(None, ge=0, description="Price of one spool on this line.", examples=[19.9])
    arrived_at: datetime | None = Field(
        None,
        description="When this line arrived. Null means still outstanding. Usually set via /order/{id}/arrive.",
    )


class OrderParameters(BaseModel):
    shop_id: int | None = Field(None, description="The shop this order was placed with.")
    ordered_at: datetime | None = Field(None, description="When the order was placed. Defaults to now.")
    order_number: str | None = Field(None, max_length=256, description="Shop order/reference number.", examples=["4711"])
    url: str | None = Field(None, max_length=1024, description="Link to the order.")
    comment: str | None = Field(None, max_length=1024, description="Free text comment about this order.")
    lines: list[OrderLineParameters] | None = Field(
        None,
        description="The lines of this order. On PATCH, if present this fully replaces the line set.",
    )


@router.get(
    "",
    name="Find orders",
    description=(
        "Get a list of orders. A websocket is served on the same path to listen for updates to any order, or "
        "added or deleted orders. See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={200: {"model": list[Order]}, 299: {"model": OrderEvent, "description": "Websocket message"}},
)
async def find(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    shop_id: Annotated[int | None, Query(title="Shop ID", description="Filter to orders placed with this shop.")] = None,
    sort: Annotated[
        str | None,
        Query(title="Sort", description='Comma-separated "field:direction" items.', examples=["ordered_at:desc"]),
    ] = None,
    limit: Annotated[int | None, Query(title="Limit", description="Maximum number of items in the response.")] = None,
    offset: Annotated[int, Query(title="Offset", description="Offset in the full result set if a limit is set.")] = 0,
) -> JSONResponse:
    try:
        sort_by = parse_sort(sort)
        db_items, total_count = await order.find(db=db, shop_id=shop_id, sort_by=sort_by, limit=limit, offset=offset)
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())

    orders_out = [Order.from_db(db_item) for db_item in db_items]
    return JSONResponse(
        content=jsonable_encoder(orders_out, exclude_none=True),
        headers={"x-total-count": str(total_count)},
    )


@router.websocket("", name="Listen to order changes")
async def notify_any(websocket: WebSocket) -> None:
    await websocket.accept()
    websocket_manager.connect(("order",), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("order",), websocket)


@router.get(
    "/{order_id}",
    name="Get order",
    description=(
        "Get a specific order. A websocket is served on the same path to listen for changes to the order. "
        "See the HTTP Response code 299 for the content of the websocket messages."
    ),
    response_model_exclude_none=True,
    responses={404: {"model": Message}, 299: {"model": OrderEvent, "description": "Websocket message"}},
)
async def get(db: Annotated[AsyncSession, Depends(get_db_session)], order_id: int) -> Order:
    db_item = await order.get_by_id(db, order_id)
    return Order.from_db(db_item)


@router.websocket("/{order_id}", name="Listen to order changes")
async def notify(websocket: WebSocket, order_id: int) -> None:
    await websocket.accept()
    websocket_manager.connect(("order", str(order_id)), websocket)
    try:
        while True:
            await asyncio.sleep(0.5)
            if await websocket.receive_text():
                await websocket.send_json({"status": "healthy"})
    except WebSocketDisconnect:
        websocket_manager.disconnect(("order", str(order_id)), websocket)


@router.post(
    "",
    name="Add order",
    description="Add a new order (with its lines) to the database.",
    response_model_exclude_none=True,
    response_model=Order,
    responses={404: {"model": Message}},
)
async def create(db: Annotated[AsyncSession, Depends(get_db_session)], body: OrderParameters) -> Order:
    db_item = await order.create(
        db=db,
        shop_id=body.shop_id,
        ordered_at=body.ordered_at,
        order_number=body.order_number,
        url=body.url,
        comment=body.comment,
        lines=[line.model_dump() for line in body.lines] if body.lines is not None else None,
    )
    return Order.from_db(db_item)


@router.patch(
    "/{order_id}",
    name="Update order",
    description=(
        "Update an order. Only fields specified in the request are affected. If `lines` is present it fully "
        "replaces the existing line set; omit it to leave the lines untouched."
    ),
    response_model_exclude_none=True,
    response_model=Order,
    responses={404: {"model": Message}},
)
async def update(db: Annotated[AsyncSession, Depends(get_db_session)], order_id: int, body: OrderParameters) -> Order:
    patch_data = body.model_dump(exclude_unset=True)
    replace_lines = "lines" in patch_data
    db_item = await order.update(db=db, order_id=order_id, data=patch_data, replace_lines=replace_lines)
    return Order.from_db(db_item)


@router.delete(
    "/{order_id}",
    name="Delete order",
    description="Delete an order. Its lines are cascade-deleted.",
    responses={404: {"model": Message}},
)
async def delete(db: Annotated[AsyncSession, Depends(get_db_session)], order_id: int) -> Message:
    await order.delete(db, order_id)
    return Message(message="Success!")
```

- [ ] **Step 7: Add the filament-delete restriction for order lines**

In `spoolman/database/filament.py`, replace the `delete` function (currently lines 364–373) with:
```python
async def delete(db: AsyncSession, filament_id: int) -> None:
    """Delete a filament object.

    Restricted while any order line references the filament (#298). FKs are not enforced on SQLite in
    this codebase, so the reference is checked explicitly rather than via a DB IntegrityError.
    """
    filament = await get_by_id(db, filament_id)
    line_count = await db.scalar(
        select(func.count(models.OrderLine.id)).where(models.OrderLine.filament_id == filament_id),
    )
    if line_count:
        raise ItemDeleteError(f"Cannot delete filament {filament_id}: {line_count} order line(s) reference it.")
    await db.delete(filament)
    try:
        await db.commit()  # Flush immediately so any errors are propagated in this request.
        await filament_changed(filament, EventType.DELETED)
    except IntegrityError as exc:
        await db.rollback()
        raise ItemDeleteError("Failed to delete filament.") from exc
```
(`select`, `func`, `models`, `ItemDeleteError`, `IntegrityError` are all already imported in this file.) The router already maps `ItemDeleteError` → 403.

- [ ] **Step 8: Mount the order router in the app and the harness**

In `spoolman/api/v1/router.py`, add `order` to the `from . import (...)` block (after `nfc,`) and `app.include_router(order.router)` next to the others.

In `tests/integration/conftest.py`, add `order` to the `from spoolman.api.v1 import (...)` block and `app.include_router(order.router, prefix="/api/v1")` next to the others.

- [ ] **Step 9: Run the order and shop tests**

Run: `uv run pytest tests/integration/test_order.py tests/integration/test_shop.py -q`
Expected: PASS (all cases, including the two restriction cases: shop-delete → 409, filament-delete → 403).

- [ ] **Step 10: Run the whole suite**

Run: `uv run pytest tests/integration -q`
Expected: all pass. (Mapper configuration now succeeds because `Order`/`OrderLine` exist.)

- [ ] **Step 11: Write the order migration**

Create `migrations/versions/2026_07_19_1700-a3b8d6f1c9e2_order_tables.py`:
```python
"""order_tables.

Revision ID: a3b8d6f1c9e2
Revises: f2a9c7e4b1d8
Create Date: 2026-07-19 17:00:00.000000

Adds the ``purchase_order`` and ``order_line`` tables (#298). Table name ``purchase_order`` because
``order`` is a reserved SQL word (same reasoning as ``user_account``). A line's ``arrived_at`` is
per-line to support split shipments. ``order_line.order_id`` cascades on order delete; the filament
FK does not cascade (filament delete is restricted in the application layer while a line references
it). Purely additive.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b8d6f1c9e2"
down_revision = "f2a9c7e4b1d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the purchase_order and order_line tables."""
    op.create_table(
        "purchase_order",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered", sa.DateTime(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=True),
        sa.Column("ordered_at", sa.DateTime(), nullable=False),
        sa.Column("order_number", sa.String(length=256), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shop.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_purchase_order_id"), "purchase_order", ["id"], unique=False)

    op.create_table(
        "order_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("filament_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_per_unit", sa.Float(), nullable=True),
        sa.Column("arrived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_order.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filament_id"], ["filament.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_line_id"), "order_line", ["id"], unique=False)
    op.create_index(op.f("ix_order_line_order_id"), "order_line", ["order_id"], unique=False)


def downgrade() -> None:
    """Drop the order_line and purchase_order tables."""
    op.drop_index(op.f("ix_order_line_order_id"), table_name="order_line")
    op.drop_index(op.f("ix_order_line_id"), table_name="order_line")
    op.drop_table("order_line")
    op.drop_index(op.f("ix_purchase_order_id"), table_name="purchase_order")
    op.drop_table("purchase_order")
```

- [ ] **Step 12: Verify the migration chain on a fresh DB**

Run:
```bash
uv run alembic heads
tmp=$(mktemp -d); SPOOLMAN_DIR_DATA="$tmp" uv run alembic upgrade head; SPOOLMAN_DIR_DATA="$tmp" uv run alembic current
```
Expected: `alembic heads` prints `a3b8d6f1c9e2 (head)`; upgrade runs clean; `alembic current` prints `a3b8d6f1c9e2 (head)`.

- [ ] **Step 13: Add a CHANGELOG bullet**

In `CHANGELOG.md`, under `## Unreleased` (after the Shops bullet), add:
```markdown
- **New: Orders** (#298) — a `/order` entity grouping the lines of one bulk reorder (per-line filament, quantity, price). Order state (open/arrived) is derived from its lines; a PATCH with `lines` fully replaces the line set. Deleting an order cascades its lines; a shop with orders, or a filament with order lines, cannot be deleted.
```

- [ ] **Step 14: Lint, format, commit (combined Shop+Order if deferred from Task 2)**

Run:
```bash
uv run ruff check spoolman/ migrations/ tests/
uv run ruff format spoolman/ migrations/ tests/
git add -A
git commit -m "feat(#298): Order + OrderLine entities, /order CRUD, deletion semantics

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: clean lint; commit succeeds.

---

## Task 4: Order `arrive` endpoint — per-line arrival, quantity splitting, spool creation

**Files:**
- Modify: `spoolman/database/order.py` (add `arrive`)
- Modify: `spoolman/api/v1/order.py` (add `ArriveParameters`, `ArriveResponse`, `POST /order/{id}/arrive`)
- Test: `tests/integration/test_order_arrive.py`

**Interfaces:**
- Consumes: `models.Order`/`OrderLine`, `order.get_by_id`; `spoolman.database.spool.create`; `spoolman.database.location.get_by_id`.
- Produces: `order.arrive(*, db, order_id, lines=None, create_spools=False, location_id=None) -> list[models.Spool]`; `POST /order/{order_id}/arrive` returning `{ "spools": [Spool, ...] }`.

- [ ] **Step 1: Write the failing arrive test (incl. the spec's 4-white/1-black scenario)**

Create `tests/integration/test_order_arrive.py`:
```python
"""Integration tests for POST /order/{id}/arrive (#298 Phase 1).

Arrival marks lines arrived (arrived_at = now); a quantity lower than a line's count SPLITS it into an
arrived part and a still-open remainder. With create_spools=true, one spool per arriving unit is
created, carrying the line's price_per_unit (and an optional location by id). Lines omitted = every
still-outstanding line.
"""

from httpx import AsyncClient

ORDER = "/api/v1/order"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
LOC = "/api/v1/locations"


async def _filament(client: AsyncClient, name: str) -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name, "weight": 1000})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_arrive_whole_order_creates_spools_with_price(client: AsyncClient):
    # The spec scenario: an order of 4 white + 1 black, all delivered at once.
    white = await _filament(client, "White")
    black = await _filament(client, "Black")
    order = (
        await client.post(
            ORDER,
            json={
                "lines": [
                    {"filament_id": white, "quantity": 4, "price_per_unit": 20.0},
                    {"filament_id": black, "quantity": 1, "price_per_unit": 25.0},
                ]
            },
        )
    ).json()

    resp = await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": True})
    assert resp.status_code == 200, resp.text
    spools = resp.json()["spools"]
    assert len(spools) == 5  # 4 + 1
    prices = sorted(s["price"] for s in spools)
    assert prices == [20.0, 20.0, 20.0, 20.0, 25.0]

    # The order derives to 'arrived'; every line has arrived_at.
    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "arrived"
    assert all(line["arrived_at"] is not None for line in got["lines"])
    # And the spools really exist.
    assert (await client.get(SPOOL)).headers["x-total-count"] == "5"


async def test_partial_arrival_splits_line(client: AsyncClient):
    white = await _filament(client, "White")
    order = (
        await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 4, "price_per_unit": 20.0}]})
    ).json()
    line_id = order["lines"][0]["id"]

    resp = await client.post(
        f"{ORDER}/{order['id']}/arrive",
        json={"lines": [{"line_id": line_id, "quantity": 2}], "create_spools": True},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["spools"]) == 2

    got = (await client.get(f"{ORDER}/{order['id']}")).json()
    assert got["state"] == "open"  # 2 still outstanding
    quantities = sorted((line["quantity"], line["arrived_at"] is not None) for line in got["lines"])
    # One arrived line of 2, one open line of 2.
    assert quantities == [(2, False), (2, True)]


async def test_arrive_without_create_spools_makes_no_spools(client: AsyncClient):
    white = await _filament(client, "White")
    order = (await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 3}]})).json()
    resp = await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["spools"] == []
    assert (await client.get(SPOOL)).headers["x-total-count"] == "0"
    assert (await client.get(f"{ORDER}/{order['id']}")).json()["state"] == "arrived"


async def test_arrive_with_location_id_sets_spool_location(client: AsyncClient):
    white = await _filament(client, "White")
    loc = (await client.post(LOC, json={"name": "Dry Box 1"})).json()
    order = (await client.post(ORDER, json={"lines": [{"filament_id": white, "quantity": 1}]})).json()
    resp = await client.post(
        f"{ORDER}/{order['id']}/arrive",
        json={"create_spools": True, "location_id": loc["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["spools"][0]["location"] == "Dry Box 1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_order_arrive.py -q`
Expected: FAIL — the `/arrive` route 404s.

- [ ] **Step 3: Implement `arrive` in the database helper**

In `spoolman/database/order.py`, add this function (after `update`, before `delete`):
```python
async def arrive(
    *,
    db: AsyncSession,
    order_id: int,
    lines: list[dict] | None = None,
    create_spools: bool = False,
    location_id: int | None = None,
) -> list[models.Spool]:
    """Mark order lines arrived, splitting on a partial quantity, optionally creating spools.

    ``lines`` is a list of {"line_id": int, "quantity"?: int}; omitted or None means every still-
    outstanding line, arriving in full. A quantity below a line's count splits the line into an
    arrived part (quantity) and a still-open remainder. When ``create_spools`` is True, one spool per
    arriving unit is created, copying the line's ``price_per_unit`` into the spool price and the
    resolved location name (from ``location_id``) into the spool location.

    Returns the created spools (empty when ``create_spools`` is False).
    """
    from spoolman.database import location, spool  # noqa: PLC0415  (avoid import cycle at module load)

    order = await get_by_id(db, order_id)
    by_id = {line.id: line for line in order.lines}

    # Resolve the requested arrivals into (line, arriving_quantity) pairs.
    requests: list[tuple[models.OrderLine, int]] = []
    if lines is None:
        for line in order.lines:
            if line.arrived_at is None:
                requests.append((line, line.quantity))
    else:
        for req in lines:
            line = by_id.get(req["line_id"])
            if line is None:
                raise ItemNotFoundError(f"Order {order_id} has no line with ID {req['line_id']}.")
            if line.arrived_at is not None:
                raise ValueError(f"Order line {line.id} has already arrived.")
            qty = req.get("quantity")
            if qty is None or qty >= line.quantity:
                requests.append((line, line.quantity))
            else:
                if qty < 1:
                    raise ValueError("Arrival quantity must be >= 1.")
                requests.append((line, qty))

    now = datetime.utcnow().replace(microsecond=0)
    location_name: str | None = None
    if location_id is not None:
        location_name = (await location.get_by_id(db, location_id)).name

    arriving: list[tuple[int, float | None]] = []  # (filament_id, price_per_unit) per unit
    for line, qty in requests:
        if qty >= line.quantity:
            line.arrived_at = now
            arriving.extend([(line.filament_id, line.price_per_unit)] * line.quantity)
        else:
            # Split: shrink the open line, add a new arrived line for the delivered quantity.
            line.quantity -= qty
            order.lines.append(
                models.OrderLine(
                    filament_id=line.filament_id,
                    quantity=qty,
                    price_per_unit=line.price_per_unit,
                    arrived_at=now,
                ),
            )
            arriving.extend([(line.filament_id, line.price_per_unit)] * qty)

    await db.commit()
    order = await get_by_id(db, order_id)
    await order_changed(order, EventType.UPDATED)

    created: list[models.Spool] = []
    if create_spools:
        for filament_id, price in arriving:
            created.append(
                await spool.create(db=db, filament_id=filament_id, price=price, location=location_name),
            )
    return created
```
Add `from spoolman.exceptions import ItemNotFoundError` is already imported at the top; add nothing else (the `location`/`spool` imports are local to avoid an import cycle). Also add `models.Spool` is already reachable via the existing `from spoolman.database import ... models ...` import.

- [ ] **Step 4: Add the arrive endpoint to the router**

In `spoolman/api/v1/order.py`, add the import for the `Spool` response model — change the models import line to:
```python
from spoolman.api.v1.models import Message, Order, OrderEvent, Spool
```
Then add these models near the top (after `OrderParameters`):
```python
class ArriveLine(BaseModel):
    line_id: int = Field(description="ID of the order line to mark arrived.")
    quantity: int | None = Field(
        None,
        ge=1,
        description="Delivered quantity. Omit for the whole line; a value below the line's count splits it.",
    )


class ArriveParameters(BaseModel):
    lines: list[ArriveLine] | None = Field(
        None,
        description="Lines to mark arrived. Omit to arrive every still-outstanding line in full.",
    )
    create_spools: bool = Field(default=False, description="Create one spool per arriving unit.")
    location_id: int | None = Field(None, description="Location entity ID to assign to the created spools.")


class ArriveResponse(BaseModel):
    spools: list[Spool] = Field(description="Spools created for the arriving quantities (empty when create_spools=false).")
```
And add the endpoint (after the `update` endpoint, before `delete`):
```python
@router.post(
    "/{order_id}/arrive",
    name="Mark order arrived",
    description=(
        "Mark order lines arrived. Omit `lines` to arrive every outstanding line; a `quantity` below a line's "
        "count splits it into an arrived part and a still-open remainder. With `create_spools`, one spool per "
        "arriving unit is created, carrying the line price and (optional) location."
    ),
    response_model_exclude_none=True,
    response_model=ArriveResponse,
    responses={400: {"model": Message}, 404: {"model": Message}},
)
async def arrive(  # noqa: ANN201
    db: Annotated[AsyncSession, Depends(get_db_session)],
    order_id: int,
    body: ArriveParameters,
):
    try:
        spools = await order.arrive(
            db=db,
            order_id=order_id,
            lines=[line.model_dump() for line in body.lines] if body.lines is not None else None,
            create_spools=body.create_spools,
            location_id=body.location_id,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=Message(message=str(e)).model_dump())
    return ArriveResponse(spools=[Spool.from_db(s) for s in spools])
```

- [ ] **Step 5: Run the arrive test to verify it passes**

Run: `uv run pytest tests/integration/test_order_arrive.py -q`
Expected: PASS (all 4 cases, including the 5-spool 4-white/1-black scenario and the 2/2 split).

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest tests/integration -q`
Expected: all pass.

- [ ] **Step 7: Add a CHANGELOG bullet, lint, format, commit**

In `CHANGELOG.md`, under `## Unreleased` (after the Orders bullet), add:
```markdown
- **New: order arrival** (#298) — `POST /order/{id}/arrive` marks lines arrived and optionally turns the delivered quantities into spools (carrying each line's price and an optional location). Partial deliveries split a line into an arrived part and an outstanding remainder, so split shipments need no extra order states.
```
Run:
```bash
uv run ruff check spoolman/ migrations/ tests/
uv run ruff format spoolman/ migrations/ tests/
git add -A
git commit -m "feat(#298): order arrive endpoint with quantity split + spool creation

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: clean; commit succeeds.

---

## Task 5: Filament `on_order` computed field

**Files:**
- Modify: `spoolman/database/filament.py` (add `get_on_order`)
- Modify: `spoolman/api/v1/models.py` (add `OnOrderInfo`, `on_order` field + `from_db` kwarg)
- Modify: `spoolman/api/v1/filament.py` (wire `on_order` into `find` and `get`)
- Test: `tests/integration/test_filament_on_order.py`

**Interfaces:**
- Consumes: `models.Order`/`OrderLine`.
- Produces: `filament.get_on_order(db, filament_ids) -> dict[int, tuple[int, datetime]]` mapping filament id → (oldest-open-order id, its ordered_at); API `Filament.on_order: OnOrderInfo | None` populated on list/detail only.

- [ ] **Step 1: Write the failing on_order test**

Create `tests/integration/test_filament_on_order.py`:
```python
"""Integration tests for the filament on_order computed field (#298 Phase 1).

on_order is the oldest OPEN order (an order with an un-arrived line) containing the filament, as
{order_id, ordered_at}; null when nothing of the filament is outstanding. It is populated only on the
filament list and detail endpoints (like spool_count), and clears when the line arrives.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
ORDER = "/api/v1/order"


async def _filament(client: AsyncClient, name: str = "PLA") -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_no_order_means_no_on_order(client: AsyncClient):
    fid = await _filament(client)
    assert "on_order" not in (await client.get(f"{FIL}/{fid}")).json()  # excluded when null
    assert "on_order" not in (await client.get(FIL)).json()[0]


async def test_open_order_sets_on_order(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 1}]})).json()

    detail = (await client.get(f"{FIL}/{fid}")).json()
    assert detail["on_order"]["order_id"] == order["id"]
    assert detail["on_order"]["ordered_at"] == order["ordered_at"]

    listed = (await client.get(FIL)).json()
    assert listed[0]["on_order"]["order_id"] == order["id"]


async def test_oldest_open_order_wins(client: AsyncClient):
    fid = await _filament(client)
    older = (
        await client.post(ORDER, json={"ordered_at": "2026-01-01T00:00:00Z", "lines": [{"filament_id": fid, "quantity": 1}]})
    ).json()
    await client.post(
        ORDER,
        json={"ordered_at": "2026-06-01T00:00:00Z", "lines": [{"filament_id": fid, "quantity": 1}]},
    )
    assert (await client.get(f"{FIL}/{fid}")).json()["on_order"]["order_id"] == older["id"]


async def test_on_order_clears_when_line_arrives(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 1}]})).json()
    assert (await client.get(f"{FIL}/{fid}")).json()["on_order"]["order_id"] == order["id"]

    await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": False})
    assert "on_order" not in (await client.get(f"{FIL}/{fid}")).json()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_filament_on_order.py -q`
Expected: FAIL — `on_order` never appears (field doesn't exist / not wired).

- [ ] **Step 3: Add `get_on_order` to the filament database helper**

In `spoolman/database/filament.py`, add this function after `get_aggregates` (after line 229):
```python
async def get_on_order(db: AsyncSession, filament_ids: list[int]) -> dict[int, tuple[int, datetime]]:
    """Return {filament_id: (order_id, ordered_at)} for the OLDEST open order containing each filament.

    "Open" for a filament means the order has an un-arrived (arrived_at IS NULL) line for it. Filaments
    with nothing outstanding are omitted. Oldest is by ordered_at, tie-broken by order id. One query
    keeps the list read path free of an N+1 pattern (mirrors get_aggregates).
    """
    if not filament_ids:
        return {}
    stmt = (
        select(models.OrderLine.filament_id, models.Order.id, models.Order.ordered_at)
        .join(models.Order, models.Order.id == models.OrderLine.order_id)
        .where(models.OrderLine.arrived_at.is_(None), models.OrderLine.filament_id.in_(filament_ids))
        .order_by(models.OrderLine.filament_id, models.Order.ordered_at.asc(), models.Order.id.asc())
    )
    rows = (await db.execute(stmt)).all()
    result: dict[int, tuple[int, datetime]] = {}
    for fid, oid, ordered_at in rows:
        if int(fid) not in result:  # first row per filament is the oldest (ordered_at asc)
            result[int(fid)] = (int(oid), ordered_at)
    return result
```

- [ ] **Step 4: Add `OnOrderInfo` and the `on_order` field to the API model**

In `spoolman/api/v1/models.py`, add `OnOrderInfo` immediately before `class Filament` (before line 269):
```python
class OnOrderInfo(BaseModel):
    """The oldest open order containing a filament (#298); the HA/HACS on-order signal."""

    order_id: int = Field(description="ID of the oldest open order containing this filament.")
    ordered_at: SpoolmanDateTime = Field(description="When that order was placed. UTC Timezone.")
```
Add the field to `Filament`, immediately after `remaining_weight` (after line 465):
```python
    on_order: OnOrderInfo | None = Field(
        None,
        description=(
            "The oldest open order containing this filament type, as {order_id, ordered_at}, or null when nothing "
            "of it is outstanding. Only populated on the filament list and detail endpoints; null in "
            "nested/websocket payloads. This is the Home Assistant / HACS on-order signal."
        ),
    )
```
Add the kwarg to `Filament.from_db`'s signature (after `remaining_weight: float | None = None,`):
```python
        on_order: "tuple[int, datetime] | None" = None,
```
And pass it in the returned `Filament(...)` (after `remaining_weight=remaining_weight,`):
```python
            on_order=OnOrderInfo(order_id=on_order[0], ordered_at=on_order[1]) if on_order is not None else None,
```
(`datetime` is already imported at the top of `models.py`.)

- [ ] **Step 5: Wire `on_order` into the filament find and get endpoints**

In `spoolman/api/v1/filament.py`, in the `find` endpoint, after the `aggregates = await filament.get_aggregates(...)` line (currently ~492), add:
```python
    on_order_map = await filament.get_on_order(db, [db_item.id for db_item in db_items])
```
and add the `on_order` kwarg to the `Filament.from_db(...)` call in the `filaments_out` list comprehension:
```python
    filaments_out = [
        Filament.from_db(
            db_item,
            spool_count=aggregates.get(db_item.id, (None, None))[0],
            remaining_weight=aggregates.get(db_item.id, (None, None))[1],
            on_order=on_order_map.get(db_item.id),
        )
        for db_item in db_items
    ]
```
In the `get` endpoint (currently ~537), change the body to:
```python
async def get(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filament_id: int,
) -> Filament:
    db_item = await filament.get_by_id(db, filament_id)
    spool_count, remaining_weight = (await filament.get_aggregates(db, [filament_id])).get(filament_id, (0, 0.0))
    on_order = (await filament.get_on_order(db, [filament_id])).get(filament_id)
    return Filament.from_db(db_item, spool_count=spool_count, remaining_weight=remaining_weight, on_order=on_order)
```

- [ ] **Step 6: Run the on_order test to verify it passes**

Run: `uv run pytest tests/integration/test_filament_on_order.py -q`
Expected: PASS (all 4 cases, including oldest-wins and clearing on arrival).

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest tests/integration -q`
Expected: all pass (existing filament tests still pass; `on_order` is omitted by `response_model_exclude_none` when null, so their assertions are unchanged).

- [ ] **Step 8: Add a CHANGELOG bullet, lint, format, commit**

In `CHANGELOG.md`, under `## Unreleased` (after the arrival bullet), add:
```markdown
- **New: filament `on_order` field** (#298) — the filament list and detail endpoints now expose `on_order` = `{order_id, ordered_at}` of the oldest open order containing the filament (null when nothing is outstanding). Home Assistant / HACS automations can read it to quiet low-stock alerts once a replenishment is on its way.
```
Run:
```bash
uv run ruff check spoolman/ migrations/ tests/
uv run ruff format spoolman/ migrations/ tests/
git add -A
git commit -m "feat(#298): filament on_order computed field (oldest open order)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: clean; commit succeeds.

---

## Task 6: Client API model additions (no UI)

**Files:**
- Modify: `client/src/pages/filaments/model.tsx` (add `on_order`)
- Create: `client/src/pages/orders/model.tsx` (`IShop`, `IOrder`, `IOrderLine`)

**Interfaces:**
- Produces: TypeScript interfaces matching the Phase-1 API models, for later UI tasks to consume.

- [ ] **Step 1: Add `on_order` to `IFilament`**

In `client/src/pages/filaments/model.tsx`, add, immediately after the `remaining_weight?: number;` line (line 40):
```typescript
  // The oldest open order containing this filament (#298). Present only on list/detail; absent when
  // nothing is outstanding. The client's on-order pill / shopping-list state reads this.
  on_order?: { order_id: number; ordered_at: string };
```

- [ ] **Step 2: Create the orders/shops model file**

Create `client/src/pages/orders/model.tsx`:
```typescript
import { IFilament } from "../filaments/model";

// A shop where filament is (re)ordered (#298). Distinct from IVendor (the manufacturer).
export interface IShop {
  id: number;
  registered: string;
  name: string;
  homepage?: string;
  // Free-form region codes this shop ships to, e.g. ["CH", "EU"]. Absent means unspecified.
  ships_to?: string[];
  comment?: string;
}

// One filament line within an order (#298). arrived_at absent/null means still outstanding.
export interface IOrderLine {
  id: number;
  filament_id: number;
  quantity: number;
  price_per_unit?: number;
  arrived_at?: string;
  // Optionally hydrated client-side for display; not part of the API line payload.
  filament?: IFilament;
}

// A grouped (bulk) reorder (#298). state is derived server-side from the lines.
export interface IOrder {
  id: number;
  registered: string;
  shop?: IShop;
  ordered_at: string;
  order_number?: string;
  url?: string;
  comment?: string;
  lines: IOrderLine[];
  state: "open" | "arrived";
}
```

- [ ] **Step 3: Type-check and format the client**

Run:
```bash
cd /home/sam/spoolman/Spoolman/client
npx tsc --noEmit
npx prettier --write src/pages/orders/model.tsx src/pages/filaments/model.tsx
npm run lint
```
Expected: `tsc --noEmit` reports no errors; prettier reformats cleanly; lint passes.

- [ ] **Step 4: Commit**

Run:
```bash
cd /home/sam/spoolman/Spoolman
git add client/src/pages/filaments/model.tsx client/src/pages/orders/model.tsx
git commit -m "feat(#298): client API models — IFilament.on_order, IShop/IOrder/IOrderLine

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: commit succeeds. **This completes the Phase-1 backend + client-model PR.** Push and open the PR for Tasks 2–6; keep it open (or merge) before UI tasks. Run the full backend suite once more as a final gate: `uv run pytest tests/integration -q` (expected: all pass).

---

## Task 7: MOCKUP GATE — produce mockups, present, STOP for approval

**This task produces NO product code. It is a hard gate. Do not start Task 8+ until Sam approves the mockups.**

**Files:**
- Existing: `ui-review/298-mock-1-shoppinglist.png`, `298-mock-2-dialog.png`, `298-mock-3-filament-show.png`, `298-mock-4-arrival.png` (the earlier #298 mockups — flat-field wording).
- Create/update: re-labelled order-based mockups + two new ones, under `ui-review/`.

- [ ] **Step 1: Review the four existing mockups**

Run: open each of `ui-review/298-mock-1-shoppinglist.png`, `298-mock-2-dialog.png`, `298-mock-3-filament-show.png`, `298-mock-4-arrival.png` and note wording that assumes the reverted flat model (e.g. "ordered_at", "order note", product-scoped "mark ordered").

- [ ] **Step 2: Re-label the four mockups to the order/shop model**

Update each mockup so the copy reflects first-class Orders + Shops:
- Shopping list (mock 1): the low-stock row's calm blue pill reads `Ordered · <age> · <shop>`, sourced from the filament's `on_order`.
- Mark-as-ordered dialog (mock 2): fields are **shop autocomplete** (with "create new shop" inline), optional url, order number, quantity, price-per-unit — labelled as creating a one-line order, not editing filament fields.
- Filament show (mock 3): shows the on-order state referencing the order (link to the order), not flat fields.
- Arrival (mock 4): the spool-create banner offers "complete this filament's order line".

- [ ] **Step 3: Produce two NEW mockups**

- `ui-review/298-mock-5-orders-page.png`: the Orders list/detail page (appears in nav only when ≥1 order exists) — columns shop, ordered date, state pill (open/arrived), line count; a detail view listing lines with per-line arrived state.
- `ui-review/298-mock-6-split-arrival.png`: the order "Arrived" flow with per-line delivered-quantity inputs (the 4-ordered / 2-delivered split case, showing "2 will arrive, 2 stay on order").

- [ ] **Step 4: Present to Sam and STOP**

Present all six mockups (four re-labelled + two new) to Sam for review. **STOP here.** Record approval before any UI implementation. Do not proceed to Task 8 without explicit approval. If Sam requests changes, iterate on the mockups only.

---

> **Tasks 8–12 are UI implementation. They are BLOCKED on Task 7 approval.** Each is a shippable unit with its own branch/PR (`claude/orders-ui-us1`, `...-us2`, `...-us3`, `...-us5`, `...-e2e`). The pure-logic helpers below are fully specified with TDD; the exact JSX/layout must match the approved mockups (adjust spacing, copy, and component composition to the approved design — the data flow, endpoints, and i18n keys below are fixed). All new user-facing strings are added English-only to `client/public/locales/en/common.json`.

## Task 8 (UI, gated): US1 — "Mark as ordered" dialog + Ordered pill

**Goal:** From a low-stock row, "Mark as ordered" opens one dialog (shop autocomplete with inline-create, optional url/order number/quantity/price-per-unit); on submit a one-line order is created via `POST /order`. The row then shows a calm blue pill `Ordered · <age> · <shop>` driven by the filament's `on_order`.

**Files:**
- Create: `client/src/pages/orders/orderPill.tsx` + `client/src/pages/orders/orderPill.test.tsx`
- Create: `client/src/pages/orders/markOrderedDialog.tsx`
- Create: `client/src/pages/orders/useShops.ts` (react-query hook: list/create shop via `/shop`)
- Modify: the low-stock row component in `client/src/pages/home/index.tsx` (shopping list) and/or `client/src/pages/filaments/` list to render the pill + entry point
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic, testable now):**
- Produces: `formatOrderedPill(onOrder: {order_id: number; ordered_at: string}, shopName: string | undefined, now?: Date): string` → e.g. `"Ordered · 3d · 3DJake"` (shop omitted when unknown: `"Ordered · 3d"`).

- [ ] **Step 1: Write the failing pill-format unit test**

Create `client/src/pages/orders/orderPill.test.tsx`:
```typescript
import { describe, it, expect } from "vitest";
import { formatOrderedPill } from "./orderPill";

describe("formatOrderedPill", () => {
  const now = new Date("2026-07-19T00:00:00Z");
  it("shows age and shop", () => {
    const s = formatOrderedPill({ order_id: 1, ordered_at: "2026-07-16T00:00:00Z" }, "3DJake", now);
    expect(s).toBe("Ordered · 3d · 3DJake");
  });
  it("omits the shop when unknown", () => {
    const s = formatOrderedPill({ order_id: 1, ordered_at: "2026-07-18T00:00:00Z" }, undefined, now);
    expect(s).toBe("Ordered · 1d");
  });
  it("uses today for a same-day order", () => {
    const s = formatOrderedPill({ order_id: 1, ordered_at: "2026-07-19T00:00:00Z" }, "Prusa", now);
    expect(s).toBe("Ordered · today · Prusa");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd client && npx vitest run src/pages/orders/orderPill.test.tsx`
Expected: FAIL — `./orderPill` has no `formatOrderedPill` export.

- [ ] **Step 3: Implement `formatOrderedPill` (and the pill component skeleton)**

Create `client/src/pages/orders/orderPill.tsx` with the pure function and a small presentational component:
```typescript
export function formatOrderedPill(
  onOrder: { order_id: number; ordered_at: string },
  shopName: string | undefined,
  now: Date = new Date(),
): string {
  const days = Math.floor((now.getTime() - new Date(onOrder.ordered_at).getTime()) / 86_400_000);
  const age = days <= 0 ? "today" : `${days}d`;
  return shopName ? `Ordered · ${age} · ${shopName}` : `Ordered · ${age}`;
}
```
Then add the calm-blue pill component (Ant Design `Tag color="blue"`) rendering `formatOrderedPill(...)`, matching the approved mock 1 styling. Wire it wherever a low-stock row is rendered (home shopping list; filament list): render the pill when `filament.on_order` is set; otherwise render the "Mark as ordered" entry point (see Step 5).

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `cd client && npx vitest run src/pages/orders/orderPill.test.tsx`
Expected: PASS.

- [ ] **Step 5: Build the Mark-as-ordered dialog + shop hook**

Create `client/src/pages/orders/useShops.ts` — a react-query hook wrapping `GET /shop` (list, for autocomplete) and `POST /shop` (inline-create, tolerating a 409 by re-fetching and selecting the existing shop by name). Create `client/src/pages/orders/markOrderedDialog.tsx` — an Ant `Modal` + `Form` with: shop `AutoComplete` (options from `useShops`, free-text creates a shop on submit), optional `url`, `order_number`, `quantity` (default 1, min 1), `price_per_unit`. On submit: ensure the shop exists (create if new), then `POST /order` with body `{ shop_id, order_number, url, lines: [{ filament_id, quantity, price_per_unit }] }`. On success, invalidate the filament query so `on_order` refreshes and the pill appears. Match the approved mock 2 layout and copy. Add all strings to `client/public/locales/en/common.json` under a new `orders` namespace (keys: `orders.markOrdered`, `orders.shop`, `orders.createShop`, `orders.quantity`, `orders.pricePerUnit`, `orders.orderNumber`, `orders.url`, `orders.pill` etc.).

- [ ] **Step 6: Type-check, lint, format, run all client unit tests**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/orders && npx vitest run
```
Expected: no type errors, lint clean, all unit tests pass.

- [ ] **Step 7: Commit**

Run (from repo root):
```bash
git add client/ && git commit -m "feat(#298): US1 mark-as-ordered dialog + on-order pill

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 9 (UI, gated): US2 — bulk order from the shopping list

**Goal:** On the dashboard shopping list, multi-select low-stock rows → "Create order" builds ONE order with one line per selected filament, quantities editable before save.

**Files:**
- Create: `client/src/pages/orders/bulkOrder.ts` + `client/src/pages/orders/bulkOrder.test.ts` (pure selection→order-body mapping)
- Create: `client/src/pages/orders/createOrderModal.tsx` (multi-line editable quantities)
- Modify: `client/src/pages/home/index.tsx` (selection state + "Create order" action on the shopping list built from `lowStockFilaments`, see `client/src/pages/home/analytics.ts`)
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic):**
- Produces: `buildOrderBody(selected: { filament_id: number; quantity: number }[], shopId?: number): { shop_id?: number; lines: { filament_id: number; quantity: number }[] }`.

- [ ] **Step 1: Write the failing mapping test**

Create `client/src/pages/orders/bulkOrder.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { buildOrderBody } from "./bulkOrder";

describe("buildOrderBody", () => {
  it("maps selected filaments to one order with one line each", () => {
    const body = buildOrderBody(
      [
        { filament_id: 10, quantity: 2 },
        { filament_id: 11, quantity: 1 },
      ],
      5,
    );
    expect(body).toEqual({
      shop_id: 5,
      lines: [
        { filament_id: 10, quantity: 2 },
        { filament_id: 11, quantity: 1 },
      ],
    });
  });
  it("omits shop_id when no shop chosen", () => {
    const body = buildOrderBody([{ filament_id: 10, quantity: 1 }]);
    expect(body).toEqual({ lines: [{ filament_id: 10, quantity: 1 }] });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd client && npx vitest run src/pages/orders/bulkOrder.test.ts`
Expected: FAIL — no `buildOrderBody` export.

- [ ] **Step 3: Implement `buildOrderBody`**

Create `client/src/pages/orders/bulkOrder.ts`:
```typescript
export function buildOrderBody(
  selected: { filament_id: number; quantity: number }[],
  shopId?: number,
): { shop_id?: number; lines: { filament_id: number; quantity: number }[] } {
  const lines = selected.map((s) => ({ filament_id: s.filament_id, quantity: s.quantity }));
  return shopId === undefined ? { lines } : { shop_id: shopId, lines };
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd client && npx vitest run src/pages/orders/bulkOrder.test.ts`
Expected: PASS.

- [ ] **Step 5: Build the multi-select + Create-order modal**

Add row selection to the shopping list in `client/src/pages/home/index.tsx` (Ant `Table` `rowSelection` or checkboxes) and a "Create order" button enabled when ≥1 row is selected. Create `client/src/pages/orders/createOrderModal.tsx`: a table of the selected filaments with an editable quantity per row (default from shortfall or 1), an optional shop autocomplete (reusing `useShops`), submitting `buildOrderBody(...)` via `POST /order`. On success invalidate the filaments query so each selected row shows the Ordered pill. Match approved mock 1 (bulk variant). Add i18n keys (`orders.createOrder`, `orders.selected`, ...).

- [ ] **Step 6: Type-check, lint, format, unit tests; commit**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/orders src/pages/home && npx vitest run
cd .. && git add client/ && git commit -m "feat(#298): US2 bulk order from shopping list

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: all green; commit succeeds.

---

## Task 10 (UI, gated): US3 — arrival banner + order "Arrived" flow with split

**Goal:** Creating a spool for an on-order filament shows a banner offering to complete that filament's line. The order page's "Arrived" flow accepts per-line delivered quantities (splitting on a partial), calling `POST /order/{id}/arrive`.

**Files:**
- Create: `client/src/pages/orders/arriveModal.tsx` (per-line quantity inputs; body from `ArriveParameters`)
- Create: `client/src/pages/orders/onOrderBanner.tsx` (spool-create banner)
- Modify: the spool create page `client/src/pages/spools/create.tsx` (render the banner when the chosen filament's `on_order` is set)
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic):**
- Produces: `buildArriveBody(lines: { line_id: number; quantity: number; delivered: number }[], createSpools: boolean, locationId?: number)` → the `{ lines?: [{line_id, quantity?}], create_spools, location_id? }` body, omitting `quantity` when `delivered >= quantity` (whole line) and omitting a line entirely when `delivered === 0`.

- [ ] **Step 1: Write the failing arrive-body test**

Create `client/src/pages/orders/arriveModal.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { buildArriveBody } from "./arriveModal";

describe("buildArriveBody", () => {
  it("omits quantity for a fully delivered line and drops zero-delivered lines", () => {
    const body = buildArriveBody(
      [
        { line_id: 1, quantity: 4, delivered: 2 }, // partial -> split
        { line_id: 2, quantity: 1, delivered: 1 }, // full -> no quantity
        { line_id: 3, quantity: 3, delivered: 0 }, // nothing -> omitted
      ],
      true,
      7,
    );
    expect(body).toEqual({
      lines: [
        { line_id: 1, quantity: 2 },
        { line_id: 2 },
      ],
      create_spools: true,
      location_id: 7,
    });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd client && npx vitest run src/pages/orders/arriveModal.test.ts`
Expected: FAIL — no `buildArriveBody` export.

- [ ] **Step 3: Implement `buildArriveBody` (and the modal skeleton)**

In `client/src/pages/orders/arriveModal.tsx`, export:
```typescript
export function buildArriveBody(
  lines: { line_id: number; quantity: number; delivered: number }[],
  createSpools: boolean,
  locationId?: number,
): { lines: ({ line_id: number; quantity?: number })[]; create_spools: boolean; location_id?: number } {
  const out = lines
    .filter((l) => l.delivered > 0)
    .map((l) => (l.delivered >= l.quantity ? { line_id: l.line_id } : { line_id: l.line_id, quantity: l.delivered }));
  const body: { lines: ({ line_id: number; quantity?: number })[]; create_spools: boolean; location_id?: number } = {
    lines: out,
    create_spools: createSpools,
  };
  if (locationId !== undefined) body.location_id = locationId;
  return body;
}
```
Then build the modal: a row per outstanding line with a delivered-quantity `InputNumber` (0..quantity, default = quantity), a `create_spools` switch, an optional location select, submitting `buildArriveBody(...)` to `POST /order/{id}/arrive`. Show the split preview ("2 will arrive, 2 stay on order") per mock 6. On success invalidate the order + filament queries.

- [ ] **Step 4: Run it to verify it passes**

Run: `cd client && npx vitest run src/pages/orders/arriveModal.test.ts`
Expected: PASS.

- [ ] **Step 5: Build the spool-create banner**

Create `client/src/pages/orders/onOrderBanner.tsx` — an Ant `Alert` shown on the spool create page when the selected filament's `on_order` is set, offering "This filament is on order (order #<id>) — mark a line arrived?" that opens the arrive modal scoped to that filament's outstanding line. Wire it into `client/src/pages/spools/create.tsx`. Add i18n keys (`orders.arrived`, `orders.delivered`, `orders.willArrive`, `orders.stayOnOrder`, `orders.banner`, ...).

- [ ] **Step 6: Type-check, lint, format, unit tests; commit**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/orders src/pages/spools && npx vitest run
cd .. && git add client/ && git commit -m "feat(#298): US3 arrival flow with split + spool-create banner

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: green; commit succeeds.

---

## Task 11 (UI, gated): US5 — conditional Orders nav/page + Shops under Settings

**Goal:** The Orders nav item and page appear only once ≥1 order exists. Shops are managed under Settings (and via the inline autocomplete). No new columns/pills intrude on default views when there are zero orders.

**Files:**
- Create: `client/src/pages/orders/index.tsx` (Orders list + detail; react-admin resource or a plain page under `/orders`)
- Modify: `client/src/App.tsx` (register the `/orders` route + conditional nav item — render the menu entry only when the orders count > 0; reuse the pattern the Locations/Printers entries use, lines ~105/231)
- Create: `client/src/pages/settings/shopsSettings.tsx` (Shops CRUD table) + register it in `client/src/pages/settings/index.tsx`
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic):**
- Produces: `shouldShowOrdersNav(orderCount: number): boolean` → `orderCount > 0`.

- [ ] **Step 1: Write the failing nav-visibility test**

Create `client/src/pages/orders/nav.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { shouldShowOrdersNav } from "./index";

describe("shouldShowOrdersNav", () => {
  it("hides the nav item with zero orders", () => {
    expect(shouldShowOrdersNav(0)).toBe(false);
  });
  it("shows it with at least one order", () => {
    expect(shouldShowOrdersNav(1)).toBe(true);
    expect(shouldShowOrdersNav(9)).toBe(true);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd client && npx vitest run src/pages/orders/nav.test.ts`
Expected: FAIL — no `shouldShowOrdersNav` export.

- [ ] **Step 3: Implement `shouldShowOrdersNav` + the Orders page**

In `client/src/pages/orders/index.tsx`, export `export function shouldShowOrdersNav(orderCount: number): boolean { return orderCount > 0; }` and build the Orders list/detail page (columns: shop, ordered date, state pill via `orderPill.tsx`, line count; detail lists lines with per-line arrived state and an "Arrived" button opening the Task 10 arrive modal). Match approved mock 5. Fetch orders via `GET /order` (react-query or react-admin dataProvider). Wire the nav gate in `App.tsx`: read the order count (a lightweight `GET /order?limit=1` reading `x-total-count`) and render the Orders menu item only when `shouldShowOrdersNav(count)`.

- [ ] **Step 4: Run it to verify it passes**

Run: `cd client && npx vitest run src/pages/orders/nav.test.ts`
Expected: PASS.

- [ ] **Step 5: Build the Shops settings panel**

Create `client/src/pages/settings/shopsSettings.tsx` — a table with create/edit/delete of shops via `/shop` (name, homepage, ships_to as a tag input, comment), surfacing the 409 delete-restriction message when a shop still has orders. Register it in `client/src/pages/settings/index.tsx` alongside the other panels (see the existing `printerSettings.tsx` / `usersSettings.tsx` registration). Add i18n keys (`settings.shops.*`, `orders.state.open`, `orders.state.arrived`, ...).

- [ ] **Step 6: Type-check, lint, format, unit tests; commit**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/orders src/pages/settings src/App.tsx && npx vitest run
cd .. && git add client/ && git commit -m "feat(#298): US5 conditional Orders nav/page + Shops settings

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: green; commit succeeds.

---

## Task 12 (UI, gated): e2e journeys

**Goal:** Playwright journeys covering mark-as-ordered (US1), bulk order (US2), and the arrival banner/split (US3).

**Files:**
- Create: `client/e2e/journeys/orders.spec.ts` (follow the conventions in `client/e2e/journeys/print-dialog.spec.ts`)

- [ ] **Step 1: Prepare the e2e build env**

Run:
```bash
cd client
echo "VITE_APIURL=/api/v1" > .env.production
npm run build
```
Expected: production build succeeds (this is required before the e2e run per the repo convention).

- [ ] **Step 2: Write the journeys (they must fail first against an un-built/older bundle, then pass)**

Create `client/e2e/journeys/orders.spec.ts` following `print-dialog.spec.ts`'s structure. Three journeys:
1. **mark-as-ordered:** create a filament with a `low_stock_threshold` and a below-threshold spool so it shows on the shopping list → click "Mark as ordered" → fill shop (inline create) + quantity/price → submit → assert the calm blue `Ordered · … · <shop>` pill appears and the filament detail's on-order state is set.
2. **bulk order:** two low-stock filaments → multi-select on the shopping list → "Create order" → edit quantities → submit → assert one order exists with two lines (via the Orders page, now visible in nav) and both rows show the pill.
3. **arrival banner + split:** an order of quantity 4 for one filament → open the spool create page for that filament → assert the on-order banner appears → open the arrive flow → deliver 2 → assert 2 spools created and the order still shows `open` with 2 outstanding.

- [ ] **Step 3: Run the e2e suite**

Run: `cd client && npm run test:e2e -- orders.spec.ts` (use the repo's actual e2e script name; check `package.json` `scripts` — likely `test:e2e` or `playwright test`).
Expected: all three journeys pass.

- [ ] **Step 4: Lint, format, commit**

Run:
```bash
cd client && npm run lint && npx prettier --write e2e/journeys/orders.spec.ts
cd .. && git add client/ && git commit -m "test(#298): e2e journeys — mark-as-ordered, bulk order, arrival split

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Expected: green; commit succeeds. This completes Phase-1 UI.

---

## Self-Review (author's spec-coverage check)

- **PR 0 revert** (spec §"PR 0 revert", Decisions #3): Task 1 removes the 3 columns, migration `e8b3c6d9f2a5`, API fields (models.py + filament.py), DB plumbing, the #309 test, the changelog bullet; verifies head → `d4e7a1b9c6f2` and a fresh upgrade. ✓
- **Shop entity** (spec §"Data model", §"API /shop CRUD"): Task 2 — name (unique)/homepage/ships_to (comma-string ↔ JSON array)/comment/registered, CRUD + WS + find. ✓
- **Order + OrderLine** (spec §"Data model", §"API /order"): Task 3 — `purchase_order`/`order_line` tables (reserved-word rename noted), nested lines, full-replace-on-PATCH, derived state, WS, deletion semantics (order→cascade, shop→restrict 409, filament→restrict 403). ✓ (SQLite FK-not-enforced handled via app-level checks — Global Constraints.)
- **arrive endpoint** (spec §"API", US3): Task 4 — omitted lines = all outstanding, quantity split, `create_spools`, price carry, `location_id` → spool location name, returns created spools. Named 4-white/1-black test. ✓
- **on_order computed field** (spec §"API", edge "oldest", US6): Task 5 — oldest open order, list+detail only, null nested, oldest-wins + clears-on-arrival tests. ✓
- **Client models** (map Task 6): Task 6 — `IFilament.on_order`, `IShop`/`IOrder`/`IOrderLine`. ✓
- **UX US1/US2/US3/US5/US6** (spec §"UX"): Tasks 8/9/10/11 (mockup-gated) + US6 satisfied by the on_order field (Task 5). US5 opt-out = conditional nav (Task 11). ✓
- **Mockup gate** (project rule): Task 7 STOPS for approval before any UI. ✓
- **OUT of scope, correctly deferred to Phase 2** (spec §"Phasing"): SpoolmanDB catalog, `purchase_options` endpoint, `purchase_regions` setting, US4 — not in this plan. ✓
- **Edge cases** (spec §"Edge cases"): zero-line order = arrived (test in Task 3); multiple open orders → oldest (Task 5); un-arriving via PATCH lines full-replace (Task 3 semantics); split bookkeeping (Task 4); quantity ≥ 1 validation (arrive + line params). ✓
