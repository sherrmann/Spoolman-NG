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
- **2026-07-19 low-stock redesign (Sam) supersedes the original Task 8–12 text:** the dashboard's separate per-spool "Low Stock" and per-filament "Shopping List" tabs merge into one per-filament "Low Stock" view (global gram fallback via a new `low_stock_fallback_g` instance setting, inline per-row threshold editing), and "Low Stock" + "Orders" become always-visible main-menu items (the earlier conditional-Orders-nav rule is dropped). See spec §"Low-stock redesign" and Decisions #6; the rewritten Tasks 8–12 below are authoritative.

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

> **Tasks 8–12 are UI implementation. They are BLOCKED on Task 7 approval.** They implement the **2026-07-19 low-stock redesign** (spec §"Low-stock redesign", Decisions #6): the dashboard's two low-stock tabs — per-spool "Low Stock" and per-filament "Shopping List" — collapse into **one per-filament "Low Stock" tab**, and **"Low Stock" and "Orders" become always-visible main-menu items**. The approved mockups are `ui-review/orders-mock-A-shoppinglist.png` (merged Low Stock — dashboard tab + full page), `ui-review/orders-mock-B-dialog.png` (US1 mark-as-ordered), `ui-review/orders-mock-C-orders-page.png` (Orders page), and `ui-review/orders-mock-D-arrival-split.png` (US3 split arrival). Each task is a shippable unit with its own branch/PR (`claude/orders-ui-lowstock`, `…-pages`, `…-order-create`, `…-arrival`, `…-e2e`). Pure-logic helpers are specified with **TDD — write the failing test first**; the JSX/layout must match the approved mockups (adjust spacing, copy, and composition to the approved design — the data flow, endpoints, and i18n keys below are fixed). **Project rule:** after implementing each UI task, screenshot the running UI and compare it against the matching approved mock (`ui-review/orders-mock-A/B/C/D.png`) before committing. All new user-facing strings are added English-only to `client/public/locales/en/common.json`.

## Task 8 (UI, gated): Merged per-filament Low Stock — fallback setting, sectioning logic, dashboard tab & KPI

**Branch:** `claude/orders-ui-lowstock`.

**Goal:** Replace the dashboard's two low-stock tabs (per-spool "Low Stock" + per-filament "Shopping List") with a single per-filament **"Low Stock"** tab. A filament is flagged when its server-computed aggregate `remaining_weight` is at or below its own `low_stock_threshold` when set, else at or below a **new instance setting `low_stock_fallback_g`** (absolute grams, ships at 200 so Low Stock works out of the box — US5; `0` disables the fallback). Explicit-threshold rows sort above fallback-caught rows with light section separation (so the *reason* is visible); on-order filaments sink to the bottom of their section under the calm blue `Ordered · <age> · <shop>` pill (linking to the order). Every row carries an inline threshold-edit affordance (PATCH `filament.low_stock_threshold`). The dashboard KPI badge counts the merged filament list. `lowStockSpools()` is deleted.

**Files:**
- Modify (backend): `spoolman/settings.py` — register `low_stock_fallback_g`
- Test (backend): `tests/integration/test_setting_low_stock_fallback.py`
- Modify: `client/src/pages/home/analytics.ts` — replace `lowStockFilaments`→`computeLowStock`; delete `lowStockSpools`
- Modify: `client/src/pages/home/analytics.test.ts` — drop the `lowStockSpools` blocks; rewrite `lowStockFilaments` as `computeLowStock`
- Modify: `client/src/pages/home/analytics.bench.ts` — drop the `lowStockSpools` benchmark
- Modify: `client/src/utils/settings.ts` — add `useLowStockFallbackG`
- Create: `client/src/pages/orders/orderPill.tsx` + `client/src/pages/orders/orderPill.test.tsx`
- Create: `client/src/pages/lowstock/thresholdEdit.tsx`
- Create: `client/src/pages/lowstock/openOrders.ts` + `client/src/pages/lowstock/openOrders.test.ts`
- Modify: `client/src/pages/home/index.tsx` — merge the two tabs into one "Low Stock" tab; KPI badge from `computeLowStock(...).count`
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic, testable now):**
- `computeLowStock(filaments: IFilament[], fallbackG: number): LowStockSections` → `{ explicit: LowStockRow[]; fallback: LowStockRow[]; count: number }`.
- `formatOrderedPill(onOrder, shopName, now?): string` → e.g. `"Ordered · 3d · 3DJake"`.
- `openOrdersByFilament(orders: IOrder[]): Map<number, { order_id: number; shop_name?: string }>` — the oldest open order per filament (mirrors the server `on_order` rule).

- [ ] **Step 1: Register the `low_stock_fallback_g` setting (backend) + failing integration test**

In `spoolman/settings.py`, add after the `unit_scaling` registration (line 92):
```python
# Global fallback low-stock threshold in absolute grams (#298 low-stock redesign). The merged
# per-filament Low Stock view flags a filament with no explicit low_stock_threshold once its aggregate
# remaining weight drops to/below this. Ships at 200 g so Low Stock is truthful out of the box (US5);
# set to 0 to disable the fallback (only explicit thresholds flag).
register_setting("low_stock_fallback_g", SettingType.NUMBER, json.dumps(200))
```
Create `tests/integration/test_setting_low_stock_fallback.py`:
```python
"""Integration test for the low_stock_fallback_g instance setting (#298 low-stock redesign).

The merged per-filament Low Stock view flags a filament with no explicit low_stock_threshold once its
aggregate remaining weight drops to/below this global fallback (absolute grams). It ships registered
with a sensible default so Low Stock works out of the box (US5); it is settable and type-checked.
"""

import json

from httpx import AsyncClient

SETTING = "/api/v1/setting/low_stock_fallback_g"
HEADERS = {"content-type": "application/json"}


async def test_fallback_setting_has_shipped_default(client: AsyncClient):
    resp = await client.get(SETTING)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_set"] is False  # unset -> the registered default is returned
    assert json.loads(body["value"]) == 200


async def test_fallback_setting_is_settable(client: AsyncClient):
    assert (await client.post(SETTING, content=json.dumps(json.dumps(350)), headers=HEADERS)).status_code == 200
    body = (await client.get(SETTING)).json()
    assert body["is_set"] is True
    assert json.loads(body["value"]) == 350


async def test_fallback_setting_rejects_non_number(client: AsyncClient):
    bad = await client.post(SETTING, content=json.dumps(json.dumps("lots")), headers=HEADERS)
    assert bad.status_code == 400, bad.text
```
Run: `uv run pytest tests/integration/test_setting_low_stock_fallback.py -q`
Expected: PASS (the setting is registered, so the default/settable/type-check cases all hold).

- [ ] **Step 2: Rewrite the analytics unit tests for `computeLowStock` (they must fail first)**

In `client/src/pages/home/analytics.test.ts`: remove `lowStockSpools` from the import from `./analytics` and delete the entire `describe("lowStockSpools", …)` block. Replace the `describe("lowStockFilaments", …)` block with (importing `computeLowStock` instead of `lowStockFilaments`):
```typescript
describe("computeLowStock", () => {
  const F = 200; // fallback grams

  it("flags a filament at or below its explicit threshold, not one strictly above", () => {
    const below = filament({ id: 1, low_stock_threshold: 500, remaining_weight: 400 });
    const at = filament({ id: 2, low_stock_threshold: 500, remaining_weight: 500 });
    const above = filament({ id: 3, low_stock_threshold: 500, remaining_weight: 600 });
    const { explicit, count } = computeLowStock([below, at, above], F);
    expect(explicit.map((r) => r.filament.id)).toEqual([1, 2]);
    expect(count).toBe(2);
  });

  it("uses the gram fallback for filaments without an explicit threshold", () => {
    const caught = filament({ id: 1, remaining_weight: 150 }); // <= 200 fallback
    const fine = filament({ id: 2, remaining_weight: 250 }); // > 200 fallback
    const { explicit, fallback } = computeLowStock([caught, fine], F);
    expect(explicit).toEqual([]);
    expect(fallback.map((r) => r.filament.id)).toEqual([1]);
    expect(fallback[0].reason).toBe("fallback");
  });

  it("disables the fallback when fallbackG <= 0 (only explicit thresholds flag)", () => {
    const noThreshold = filament({ id: 1, remaining_weight: 10 });
    const explicitLow = filament({ id: 2, low_stock_threshold: 100, remaining_weight: 50 });
    const { explicit, fallback } = computeLowStock([noThreshold, explicitLow], 0);
    expect(fallback).toEqual([]);
    expect(explicit.map((r) => r.filament.id)).toEqual([2]);
  });

  it("never flags a filament whose aggregate remaining weight is not populated", () => {
    expect(computeLowStock([filament({ low_stock_threshold: 500 })], F).count).toBe(0);
  });

  it("orders each section by largest shortfall first", () => {
    const small = filament({ id: 1, low_stock_threshold: 500, remaining_weight: 450 }); // short 50
    const large = filament({ id: 2, low_stock_threshold: 1000, remaining_weight: 100 }); // short 900
    const mid = filament({ id: 3, low_stock_threshold: 800, remaining_weight: 500 }); // short 300
    expect(computeLowStock([small, large, mid], F).explicit.map((r) => r.filament.id)).toEqual([2, 3, 1]);
  });

  it("sinks on-order filaments to the bottom of their section", () => {
    const plain = filament({ id: 1, low_stock_threshold: 500, remaining_weight: 400 }); // short 100, not ordered
    const ordered = filament({
      id: 2,
      low_stock_threshold: 1000,
      remaining_weight: 100, // short 900, but on order -> sinks below the smaller shortfall
      on_order: { order_id: 7, ordered_at: "2026-07-10T00:00:00Z" },
    });
    expect(computeLowStock([ordered, plain], F).explicit.map((r) => r.filament.id)).toEqual([1, 2]);
  });
});
```
Run: `cd client && npx vitest run src/pages/home/analytics.test.ts`
Expected: FAIL — `computeLowStock` is not exported yet (and `lowStockSpools` import is gone).

- [ ] **Step 3: Implement `computeLowStock` and delete `lowStockSpools` in `analytics.ts`**

In `client/src/pages/home/analytics.ts`: delete `LOW_STOCK_THRESHOLD` **only if** nothing else uses it (grep first — `getWeightPct` uses its own literal; keep the export if referenced elsewhere), delete the `lowStockSpools` function, and replace the `LowStockFilament` interface + `lowStockFilaments` function with:
```typescript
export interface LowStockRow {
  filament: IFilament;
  remaining: number;
  threshold: number;
  /** Why this row is listed: its own threshold, or the global gram fallback. Drives section separation. */
  reason: "explicit" | "fallback";
  /** Oldest open order for this filament, if any — drives the "Ordered" pill and the sink-to-bottom sort. */
  onOrder?: { order_id: number; ordered_at: string };
}

export interface LowStockSections {
  /** Rows flagged by their own low_stock_threshold; largest shortfall first, on-order rows last. */
  explicit: LowStockRow[];
  /** Rows flagged only by the global gram fallback; same ordering. */
  fallback: LowStockRow[];
  /** Total flagged filaments across both sections — the dashboard KPI badge count. */
  count: number;
}

/** On-order rows sink to the bottom of their section; otherwise largest shortfall first. */
function compareLowStockRows(a: LowStockRow, b: LowStockRow): number {
  const ao = a.onOrder ? 1 : 0;
  const bo = b.onOrder ? 1 : 0;
  if (ao !== bo) return ao - bo;
  return b.threshold - b.remaining - (a.threshold - a.remaining);
}

/**
 * Merged per-filament Low Stock (#298 redesign — supersedes lowStockSpools and the old lowStockFilaments).
 * A filament is flagged when its server-computed aggregate remaining weight is at or below its own
 * low_stock_threshold when set, else at or below the global fallback `fallbackG` (absolute grams; a value
 * <= 0 disables the fallback). Explicit-threshold and fallback-caught rows are returned in separate
 * sections so the UI can show WHY each is listed; within each, on-order filaments sink last.
 */
export function computeLowStock(filaments: IFilament[], fallbackG: number): LowStockSections {
  const explicit: LowStockRow[] = [];
  const fallback: LowStockRow[] = [];
  for (const f of filaments) {
    if (f.remaining_weight == null) continue;
    const hasExplicit = f.low_stock_threshold != null;
    const threshold = hasExplicit ? (f.low_stock_threshold as number) : fallbackG;
    if (threshold <= 0) continue; // fallback disabled, or a nonsensical explicit 0
    if (f.remaining_weight > threshold) continue;
    const row: LowStockRow = {
      filament: f,
      remaining: f.remaining_weight,
      threshold,
      reason: hasExplicit ? "explicit" : "fallback",
      onOrder: f.on_order,
    };
    (hasExplicit ? explicit : fallback).push(row);
  }
  explicit.sort(compareLowStockRows);
  fallback.sort(compareLowStockRows);
  return { explicit, fallback, count: explicit.length + fallback.length };
}
```
In `client/src/pages/home/analytics.bench.ts`, remove the `lowStockSpools` import + its benchmark case (or repoint it to `computeLowStock(filaments, 200)`).
Run: `cd client && npx vitest run src/pages/home/analytics.test.ts`
Expected: PASS.

- [ ] **Step 4: Add `useLowStockFallbackG` to the settings util**

In `client/src/utils/settings.ts`, add:
```typescript
/**
 * Global fallback low-stock threshold in absolute grams (#298 low-stock redesign). A filament with no
 * explicit low_stock_threshold is flagged once its aggregate remaining weight drops to/below this.
 * Ships at 200 g so Low Stock works out of the box (US5); 0 disables the fallback.
 */
export function useLowStockFallbackG(): number {
  return JSON.parse(useGetSetting("low_stock_fallback_g").data?.value ?? "200");
}
```

- [ ] **Step 5: Write the failing pill-format unit test**

Create `client/src/pages/orders/orderPill.test.tsx`:
```typescript
import { describe, it, expect } from "vitest";
import { formatOrderedPill } from "./orderPill";

describe("formatOrderedPill", () => {
  const now = new Date("2026-07-19T00:00:00Z");
  it("shows age and shop", () => {
    expect(formatOrderedPill({ order_id: 1, ordered_at: "2026-07-16T00:00:00Z" }, "3DJake", now)).toBe(
      "Ordered · 3d · 3DJake",
    );
  });
  it("omits the shop when unknown", () => {
    expect(formatOrderedPill({ order_id: 1, ordered_at: "2026-07-18T00:00:00Z" }, undefined, now)).toBe("Ordered · 1d");
  });
  it("uses 'today' for a same-day order", () => {
    expect(formatOrderedPill({ order_id: 1, ordered_at: "2026-07-19T00:00:00Z" }, "Prusa", now)).toBe(
      "Ordered · today · Prusa",
    );
  });
});
```
Run: `cd client && npx vitest run src/pages/orders/orderPill.test.tsx`
Expected: FAIL — no `formatOrderedPill` export.

- [ ] **Step 6: Implement the pill (`formatOrderedPill` + `OrderedPill` component)**

Create `client/src/pages/orders/orderPill.tsx`:
```typescript
import { Tag } from "antd";
import { Link } from "react-router";

/** Compose the calm on-order pill text: "Ordered · <age> · <shop>" ("today" same-day; shop omitted when unknown). */
export function formatOrderedPill(
  onOrder: { order_id: number; ordered_at: string },
  shopName: string | undefined,
  now: Date = new Date(),
): string {
  const days = Math.floor((now.getTime() - new Date(onOrder.ordered_at).getTime()) / 86_400_000);
  const age = days <= 0 ? "today" : `${days}d`;
  return shopName ? `Ordered · ${age} · ${shopName}` : `Ordered · ${age}`;
}

/** Calm blue pill for an on-order Low Stock row; links through to the order (#298). */
export function OrderedPill({
  onOrder,
  shopName,
  orderHref,
}: {
  onOrder: { order_id: number; ordered_at: string };
  shopName?: string;
  orderHref: string;
}) {
  return (
    <Link to={orderHref} onClick={(e) => e.stopPropagation()}>
      <Tag color="blue" style={{ cursor: "pointer" }}>
        {formatOrderedPill(onOrder, shopName)}
      </Tag>
    </Link>
  );
}
```
Run: `cd client && npx vitest run src/pages/orders/orderPill.test.tsx`
Expected: PASS.

- [ ] **Step 7: Write + implement `openOrdersByFilament` (oldest-open map for pills)**

Create `client/src/pages/lowstock/openOrders.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { openOrdersByFilament } from "./openOrders";
import { IOrder } from "../orders/model";

const order = (o: Partial<IOrder>): IOrder => ({
  id: 1,
  registered: "",
  ordered_at: "2026-07-10T00:00:00Z",
  lines: [],
  state: "open",
  ...o,
});

describe("openOrdersByFilament", () => {
  it("maps a filament to its open order id and shop name", () => {
    const m = openOrdersByFilament([
      order({ id: 5, shop: { id: 1, registered: "", name: "3DJake" }, lines: [{ id: 1, filament_id: 10, quantity: 1 }] }),
    ]);
    expect(m.get(10)).toEqual({ order_id: 5, shop_name: "3DJake" });
  });
  it("prefers the oldest open order for a filament", () => {
    const m = openOrdersByFilament([
      order({ id: 5, ordered_at: "2026-07-15T00:00:00Z", lines: [{ id: 1, filament_id: 10, quantity: 1 }] }),
      order({ id: 6, ordered_at: "2026-07-01T00:00:00Z", lines: [{ id: 2, filament_id: 10, quantity: 1 }] }),
    ]);
    expect(m.get(10)?.order_id).toBe(6);
  });
  it("ignores arrived lines and arrived orders", () => {
    const m = openOrdersByFilament([
      order({ id: 5, state: "arrived", lines: [{ id: 1, filament_id: 10, quantity: 1, arrived_at: "2026-07-11T00:00:00Z" }] }),
    ]);
    expect(m.has(10)).toBe(false);
  });
});
```
Run it (`cd client && npx vitest run src/pages/lowstock/openOrders.test.ts`) — FAIL — then create `client/src/pages/lowstock/openOrders.ts`:
```typescript
import { IOrder } from "../orders/model";

/**
 * Map each on-order filament to the OLDEST open order that contains it (#298), for the Low Stock
 * "Ordered · <age> · <shop>" pill and its order link. Mirrors the server's `on_order = oldest open`
 * rule so the pill and the filament's on_order field agree.
 */
export function openOrdersByFilament(orders: IOrder[]): Map<number, { order_id: number; shop_name?: string }> {
  const oldest = new Map<number, { order_id: number; ordered_at: string; shop_name?: string }>();
  for (const order of orders) {
    if (order.state !== "open") continue;
    for (const line of order.lines) {
      if (line.arrived_at) continue;
      const prev = oldest.get(line.filament_id);
      if (!prev || new Date(order.ordered_at).getTime() < new Date(prev.ordered_at).getTime()) {
        oldest.set(line.filament_id, { order_id: order.id, ordered_at: order.ordered_at, shop_name: order.shop?.name });
      }
    }
  }
  const out = new Map<number, { order_id: number; shop_name?: string }>();
  for (const [fid, v] of oldest) out.set(fid, { order_id: v.order_id, shop_name: v.shop_name });
  return out;
}
```
Re-run the test: PASS.

- [ ] **Step 8: Build the inline threshold-edit affordance**

Create `client/src/pages/lowstock/thresholdEdit.tsx` — a small edit control shown on **every** Low Stock row that PATCHes `filament.low_stock_threshold` and invalidates the filament list so the row re-sections/re-sorts:
```typescript
import { EditOutlined } from "@ant-design/icons";
import { useInvalidate, useTranslate, useUpdate } from "@refinedev/core";
import { InputNumber, Popover, Tooltip } from "antd";
import { useState } from "react";

/** Inline low-stock-threshold editor on every Low Stock row (#298 redesign). */
export function ThresholdEdit({ filamentId, value }: { filamentId: number; value?: number }) {
  const t = useTranslate();
  const { mutate } = useUpdate();
  const invalidate = useInvalidate();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<number | null>(value ?? null);

  const save = () => {
    mutate(
      { resource: "filament", id: filamentId, values: { low_stock_threshold: draft }, successNotification: false },
      { onSuccess: () => invalidate({ resource: "filament", invalidates: ["list"] }) },
    );
    setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      content={
        <InputNumber autoFocus min={0} value={draft} addonAfter="g" onChange={setDraft} onPressEnter={save} onBlur={save} />
      }
    >
      <Tooltip title={t("lowstock.edit_threshold")}>
        <EditOutlined onClick={(e) => e.stopPropagation()} style={{ opacity: 0.6, cursor: "pointer" }} />
      </Tooltip>
    </Popover>
  );
}
```

- [ ] **Step 9: Merge the two dashboard tabs into one "Low Stock" tab + repoint the KPI badge**

In `client/src/pages/home/index.tsx`:
1. In the `./analytics` import block, remove `lowStockSpools as computeLowStockSpools` and change `lowStockFilaments as computeLowStockFilaments` to `computeLowStock`. Add imports:
```typescript
import { useLowStockFallbackG } from "../../utils/settings";
import { IOrder } from "../orders/model";
import { openOrdersByFilament } from "../lowstock/openOrders";
import { OrderedPill } from "../orders/orderPill";
import { ThresholdEdit } from "../lowstock/thresholdEdit";
```
2. Replace the calculation lines (currently `const lowStockSpools = …`, `const hasLowStock = …`, `const lowStockFilamentsData = …`, `const hasShoppingList = …`) with:
```typescript
const fallbackG = useLowStockFallbackG();
const lowStock = computeLowStock(allFilaments, fallbackG);
const hasLowStock = lowStock.count > 0;
const openOrders = useList<IOrder>({ resource: "order", pagination: { mode: "off" } });
const orderMap = openOrdersByFilament(openOrders.result?.data ?? []);
```
3. In the KPI "total weight" card, replace every `lowStockSpools.length` reference (the `color`, `opacity`, condition, and badge count) with `lowStock.count`, e.g. `{lowStock.count > 0 ? (<><WarningOutlined /> {lowStock.count} {t("home.low_stock").toUpperCase()}</>) : …}`.
4. Replace **both** the old `key: "lowstock"` (per-spool) and `key: "shopping"` tab objects with this single merged tab object (keep `defaultActiveKey={hasLowStock ? "lowstock" : "materials"}`):
```tsx
{
  key: "lowstock",
  label: (
    <span>
      {hasLowStock && <WarningOutlined style={{ color: "#ff716c" }} />} {t("home.low_stock")}
    </span>
  ),
  children: (
    <div className="dash-section" style={{ background: S.low }}>
      {lowStock.count === 0 ? (
        <div className="dash-empty">{t("home.all_stocked")}</div>
      ) : (
        <>
          {([
            ["explicit", lowStock.explicit] as const,
            ["fallback", lowStock.fallback] as const,
          ]).map(([reason, rows]) =>
            rows.length === 0 ? null : (
              <div key={reason}>
                <div className="dash-section-subhead" style={{ opacity: 0.5 }}>
                  {reason === "explicit"
                    ? t("lowstock.section.explicit")
                    : t("lowstock.section.fallback", { grams: fallbackG })}
                </div>
                <div className="low-stock-list">
                  {rows.map(({ filament, remaining, threshold, onOrder }) => {
                    const hex = "#" + (filament.color_hex ?? "555555").replace("#", "");
                    const order = onOrder ? orderMap.get(filament.id) : undefined;
                    return (
                      <div
                        key={filament.id}
                        className="low-stock-item"
                        style={{ background: S.lowest }}
                        onClick={() => navigate(showUrl("filament", filament.id))}
                      >
                        <div className="low-stock-left">
                          <div
                            className="low-stock-color-dot"
                            style={{
                              backgroundColor: hex,
                              boxShadow: isDark ? `0 0 14px ${hex}50` : `0 1px 3px rgba(0,0,0,0.12)`,
                            }}
                          />
                          <div className="low-stock-info">
                            <h4>{getFilamentName(filament)}</h4>
                            <p>
                              {t("spool.fields.material")}: {filament.material ?? "?"}
                            </p>
                          </div>
                        </div>
                        <div className="low-stock-right" onClick={(e) => e.stopPropagation()}>
                          {onOrder ? (
                            <OrderedPill
                              onOrder={onOrder}
                              shopName={order?.shop_name}
                              orderHref={`/orders?highlight=${onOrder.order_id}`}
                            />
                          ) : null}
                          <div className="low-stock-weight" style={{ color: "#d7383b" }}>
                            {formatWeight(remaining, 0)} <span className="total">/ {formatWeight(threshold, 0)}</span>
                          </div>
                          <ThresholdEdit filamentId={filament.id} value={filament.low_stock_threshold} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ),
          )}
        </>
      )}
    </div>
  ),
},
```
Add the `.dash-section-subhead` rule to `client/src/pages/home/home.css` (small, muted, letter-spaced label). The old `home.shopping_list*` i18n keys are now unused — leaving them is harmless; the merged empty state reuses `home.all_stocked`.

- [ ] **Step 10: Add i18n keys**

In `client/public/locales/en/common.json`, add a `lowstock` namespace (and keep `home.low_stock` = "Low Stock"):
```json
"lowstock": {
  "title": "Low Stock",
  "edit_threshold": "Set alert threshold",
  "section": {
    "explicit": "Below your set threshold",
    "fallback": "Below the {{grams}} g default"
  }
}
```
(Further `lowstock.*`/`orders.*` keys are added by Tasks 9–11.)

- [ ] **Step 11: Type-check, lint, format, unit tests; screenshot; commit**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/home src/pages/orders src/pages/lowstock src/utils/settings.ts && npx vitest run
cd .. && uv run ruff check spoolman/ tests/ && uv run ruff format spoolman/ tests/ && uv run pytest tests/integration/test_setting_low_stock_fallback.py -q
```
Expected: all green. Then run the app, open the dashboard, and **screenshot the merged "Low Stock" tab; compare against `ui-review/orders-mock-A-shoppinglist.png`** (single tab, explicit-above-fallback sections, inline threshold edit). Commit:
```bash
git add -A && git commit -m "feat(#298): merged per-filament Low Stock + low_stock_fallback_g setting

Single dashboard Low Stock tab (explicit thresholds above the gram-fallback
section, on-order rows sink last), inline threshold edit per row, KPI badge on
the merged count; lowStockSpools removed. New instance setting low_stock_fallback_g
(default 200 g) drives the fallback.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 9 (UI, gated): Always-visible Low Stock & Orders nav + Low Stock full page + Orders list page

**Branch:** `claude/orders-ui-pages`.

**Goal:** Register **"Low Stock"** and **"Orders"** as always-visible main-menu items with routes (superseding the old conditional-nav rule — US5 amended). Build the Low Stock full page: the same merged list in a larger layout, sections, inline threshold edit on every row, and the Ordered pill — the reorder/shopping destination and future home of the #299 purchase links. Build the Orders list page: order #, shop, ordered date, a lines summary with arrived counts, the derived state pill, and a "New order" button (the per-order "Arrived…" action is wired in Task 11). With zero orders and zero thresholds both pages empty-state cleanly (US5).

**Files:**
- Modify: `client/src/App.tsx` — register `lowstock` + `order` resources (icons + `list` paths, both always visible) and their routes; mirror the Locations resource (App.tsx lines 148–155) and its route (line 231)
- Create: `client/src/pages/lowstock/index.tsx` (full page; reuses `computeLowStock`, `ThresholdEdit`, `OrderedPill`, `openOrdersByFilament`, `useLowStockFallbackG`)
- Create: `client/src/pages/orders/index.tsx` (Orders list; reuses the state pill)
- Create: `client/src/pages/orders/ordersState.ts` + `client/src/pages/orders/ordersState.test.ts` (pure lines-summary helper)
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic):**
- `summarizeLines(order: IOrder): { total: number; arrived: number; outstanding: number; filaments: number }` — the Orders-list summary column.

- [ ] **Step 1: Write the failing lines-summary test**

Create `client/src/pages/orders/ordersState.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { summarizeLines } from "./ordersState";
import { IOrder } from "./model";

const order = (o: Partial<IOrder>): IOrder => ({
  id: 1,
  registered: "",
  ordered_at: "2026-07-10T00:00:00Z",
  lines: [],
  state: "open",
  ...o,
});

describe("summarizeLines", () => {
  it("rolls quantities into total/arrived/outstanding + filament count", () => {
    const s = summarizeLines(
      order({
        lines: [
          { id: 1, filament_id: 1, quantity: 4, arrived_at: "2026-07-11T00:00:00Z" },
          { id: 2, filament_id: 2, quantity: 3 },
        ],
      }),
    );
    expect(s).toEqual({ total: 7, arrived: 4, outstanding: 3, filaments: 2 });
  });
  it("reports zero for a note-only order", () => {
    expect(summarizeLines(order({ lines: [] }))).toEqual({ total: 0, arrived: 0, outstanding: 0, filaments: 0 });
  });
});
```
Run: `cd client && npx vitest run src/pages/orders/ordersState.test.ts` → FAIL.

- [ ] **Step 2: Implement `summarizeLines`**

Create `client/src/pages/orders/ordersState.ts`:
```typescript
import { IOrder } from "./model";

export interface LinesSummary {
  total: number;
  arrived: number;
  outstanding: number;
  filaments: number;
}

/** Roll an order's lines into counts for the Orders-list summary column (#298). */
export function summarizeLines(order: IOrder): LinesSummary {
  let total = 0;
  let arrived = 0;
  for (const l of order.lines) {
    total += l.quantity;
    if (l.arrived_at) arrived += l.quantity;
  }
  return { total, arrived, outstanding: total - arrived, filaments: order.lines.length };
}
```
Run the test again → PASS.

- [ ] **Step 3: Register both nav items + routes in `App.tsx`**

Add `WarningOutlined` and `ShoppingCartOutlined` to the `@ant-design/icons` import. In the `resources={[…]}` array, add (both **always visible**; the amended US5 drops the conditional-nav rule) right after the `locations` resource:
```tsx
{
  name: "lowstock",
  list: "/lowstock",
  meta: { canDelete: false, label: t("lowstock.title"), icon: <WarningOutlined /> },
},
{
  name: "order",
  list: "/orders",
  meta: { canDelete: false, label: t("orders.title"), icon: <ShoppingCartOutlined /> },
},
```
(The resource `name: "order"` maps to the `/order` API via the dataProvider — matching `useList<IOrder>({ resource: "order" })` — while its menu entry links to the `/orders` page.) Add the routes next to the `/locations` route:
```tsx
<Route path="/lowstock" element={<LoadablePage name="lowstock" />} />
<Route path="/orders" element={<LoadablePage name="orders" />} />
```

- [ ] **Step 4: Build the Low Stock full page**

Create `client/src/pages/lowstock/index.tsx` — a full-width page rendering the same merged list as the dashboard tab, in a larger layout, using the shared helpers:
```typescript
import { useList, useTranslate } from "@refinedev/core";
import { List } from "@refinedev/antd";
import { Empty, Typography } from "antd";
import { useLowStockFallbackG } from "../../utils/settings";
import { computeLowStock, getFilamentName } from "../home/analytics";
import { IFilament } from "../filaments/model";
import { IOrder } from "../orders/model";
import { OrderedPill } from "../orders/orderPill";
import { openOrdersByFilament } from "./openOrders";
import { ThresholdEdit } from "./thresholdEdit";
```
The component: fetch `filament` (pagination off) and `order` (pagination off), compute `computeLowStock(filaments, useLowStockFallbackG())`, build `openOrdersByFilament(orders)`, and render the two sections (explicit above fallback) with per-row: filament name/colour, remaining/threshold, `<ThresholdEdit>`, and `<OrderedPill>` when on order. Empty state via antd `Empty` + copy `lowstock.empty`. This page also hosts the US1 "Mark as ordered" per-row action and the US2 multi-select "Create order" button — both wired in Task 10 (leave a clearly-marked placeholder region for them, or a disabled button, so this task ships a truthful read-only page). Match `ui-review/orders-mock-A-shoppinglist.png` (full-page variant).

- [ ] **Step 5: Build the Orders list page**

Create `client/src/pages/orders/index.tsx` — a table of orders from `GET /order` (react-admin `useTable`/`useList` on resource `order`). Columns: order number, shop name (`order.shop?.name` or "—"), ordered date (formatted with the app's date util), lines summary from `summarizeLines` ("4 of 7 arrived · 2 filaments"), and a derived **state pill** — `<Tag color="blue">Open</Tag>` / `<Tag color="green">Arrived</Tag>` from `order.state` (`orders.state.open`/`orders.state.arrived`). A top-right **"New order"** button (opens the create-order flow; wired to the Task 10 modal). Each row: an expandable detail listing its lines with per-line arrived state (✓ / outstanding), and an **"Arrived…"** action button (opens the Task 11 arrive modal — leave the handler as a marked stub in this task). Empty-state cleanly (`orders.empty`) so zero orders reads fine (US5). Match `ui-review/orders-mock-C-orders-page.png`.

- [ ] **Step 6: Add i18n keys**

In `client/public/locales/en/common.json`, extend the `lowstock` namespace and add an `orders` namespace:
```json
"lowstock": { "empty": "Nothing to reorder — you're well stocked." },
"orders": {
  "title": "Orders",
  "empty": "No orders yet.",
  "new_order": "New order",
  "order_number": "Order #",
  "shop": "Shop",
  "ordered_at": "Ordered",
  "lines_summary": "{{arrived}} of {{total}} arrived · {{filaments}} filaments",
  "arrived_action": "Arrived…",
  "state": { "open": "Open", "arrived": "Arrived" }
}
```
(Merge these into the objects created in Task 8 rather than duplicating the keys.)

- [ ] **Step 7: Type-check, lint, format, unit tests; screenshots; commit**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/lowstock src/pages/orders src/App.tsx && npx vitest run
```
Expected: all green. Run the app and **screenshot the Low Stock full page (vs `ui-review/orders-mock-A-shoppinglist.png`) and the Orders page (vs `ui-review/orders-mock-C-orders-page.png`)**; confirm both nav items are always present and both pages empty-state cleanly with no data. Commit:
```bash
cd .. && git add client/ && git commit -m "feat(#298): always-visible Low Stock & Orders nav + pages

Low Stock full page (merged list, sections, inline threshold edit, Ordered pill)
and Orders list page (state pill, lines summary, New order); both registered as
always-visible main-menu items, superseding the conditional-nav rule (US5 amended).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 10 (UI, gated): US1 Mark-as-ordered dialog + US2 bulk order

**Branch:** `claude/orders-ui-order-create`.

**Goal:** **US1** — from any low-stock row (dashboard tab + full page), "Mark as ordered" opens the approved dialog (`ui-review/orders-mock-B-dialog.png`): a shop `AutoComplete` (creating a shop inline if it doesn't exist), an **order-date `DatePicker` defaulted to today (backdatable → `ordered_at`)**, a quantity, an optional price-per-unit, an optional order link (`url`), and an optional order number. On submit a one-line order is created (`POST /order`); the row then shows the Ordered pill. **US2** — on the Low Stock full page, multi-select rows → "Create order" builds one order with a line per selected filament, quantities editable before save.

**Files:**
- Create: `client/src/pages/orders/orderBody.ts` + `client/src/pages/orders/orderBody.test.ts` (pure body builders)
- Create: `client/src/pages/orders/useShops.ts` (list + inline-create shop via `/shop`, tolerating a 409)
- Create: `client/src/pages/orders/markOrderedDialog.tsx` (US1 single-line dialog)
- Create: `client/src/pages/orders/createOrderModal.tsx` (US2 bulk, editable per-line quantities)
- Modify: `client/src/pages/lowstock/index.tsx` (per-row "Mark as ordered" action + multi-select + "Create order")
- Modify: `client/src/pages/home/index.tsx` (per-row "Mark as ordered" action on the dashboard tab)
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic):**
- `buildMarkOrderedBody(input)` and `buildBulkOrderBody(selected, orderedAt, shopId?)` → the `POST /order` body (nested `lines`, `ordered_at` carried so a backdated pick is honoured).

- [ ] **Step 1: Write the failing order-body test**

Create `client/src/pages/orders/orderBody.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { buildMarkOrderedBody, buildBulkOrderBody } from "./orderBody";

describe("buildMarkOrderedBody", () => {
  it("builds a one-line order with shop, price, number, url and the (backdated) ordered_at", () => {
    expect(
      buildMarkOrderedBody({
        filament_id: 10,
        quantity: 2,
        orderedAt: "2026-07-01T00:00:00Z",
        shopId: 5,
        pricePerUnit: 19.9,
        orderNumber: "4711",
        url: "https://shop/4711",
      }),
    ).toEqual({
      shop_id: 5,
      order_number: "4711",
      url: "https://shop/4711",
      ordered_at: "2026-07-01T00:00:00Z",
      lines: [{ filament_id: 10, quantity: 2, price_per_unit: 19.9 }],
    });
  });
  it("omits shop/price/number/url when not given", () => {
    expect(buildMarkOrderedBody({ filament_id: 10, quantity: 1, orderedAt: "2026-07-19T00:00:00Z" })).toEqual({
      ordered_at: "2026-07-19T00:00:00Z",
      lines: [{ filament_id: 10, quantity: 1 }],
    });
  });
});

describe("buildBulkOrderBody", () => {
  it("maps selected filaments to one order with one line each", () => {
    expect(
      buildBulkOrderBody(
        [
          { filament_id: 10, quantity: 2 },
          { filament_id: 11, quantity: 1 },
        ],
        "2026-07-19T00:00:00Z",
        5,
      ),
    ).toEqual({
      shop_id: 5,
      ordered_at: "2026-07-19T00:00:00Z",
      lines: [
        { filament_id: 10, quantity: 2 },
        { filament_id: 11, quantity: 1 },
      ],
    });
  });
  it("omits shop_id when no shop chosen", () => {
    expect(buildBulkOrderBody([{ filament_id: 10, quantity: 1 }], "2026-07-19T00:00:00Z")).toEqual({
      ordered_at: "2026-07-19T00:00:00Z",
      lines: [{ filament_id: 10, quantity: 1 }],
    });
  });
});
```
Run: `cd client && npx vitest run src/pages/orders/orderBody.test.ts` → FAIL.

- [ ] **Step 2: Implement the body builders**

Create `client/src/pages/orders/orderBody.ts`:
```typescript
export interface OrderLineInput {
  filament_id: number;
  quantity: number;
  price_per_unit?: number;
}

export interface NewOrderBody {
  shop_id?: number;
  order_number?: string;
  url?: string;
  ordered_at: string;
  lines: OrderLineInput[];
}

/** POST /order body for the US1 single-line "Mark as ordered" dialog. */
export function buildMarkOrderedBody(input: {
  filament_id: number;
  quantity: number;
  orderedAt: string;
  shopId?: number;
  pricePerUnit?: number;
  orderNumber?: string;
  url?: string;
}): NewOrderBody {
  const line: OrderLineInput = { filament_id: input.filament_id, quantity: input.quantity };
  if (input.pricePerUnit !== undefined) line.price_per_unit = input.pricePerUnit;
  const body: NewOrderBody = { ordered_at: input.orderedAt, lines: [line] };
  if (input.shopId !== undefined) body.shop_id = input.shopId;
  if (input.orderNumber) body.order_number = input.orderNumber;
  if (input.url) body.url = input.url;
  return body;
}

/** POST /order body for the US2 bulk order: one line per selected filament. */
export function buildBulkOrderBody(selected: OrderLineInput[], orderedAt: string, shopId?: number): NewOrderBody {
  const body: NewOrderBody = { ordered_at: orderedAt, lines: selected.map((s) => ({ ...s })) };
  if (shopId !== undefined) body.shop_id = shopId;
  return body;
}
```
Run the test again → PASS.

- [ ] **Step 3: Build the shop hook**

Create `client/src/pages/orders/useShops.ts` — a react-query hook exposing `shops` (`GET /shop`, for the autocomplete) and `ensureShop(name): Promise<number>` which returns an existing shop's id (case-insensitive name match) or `POST /shop` to create it, tolerating a 409 (duplicate name from a race) by refetching and matching by name. Use `apiFetch`/`getAPIURL` like `client/src/utils/querySettings.ts`, and invalidate the `shop` list on create.

- [ ] **Step 4: Build the Mark-as-ordered dialog (US1)**

Create `client/src/pages/orders/markOrderedDialog.tsx` — an antd `Modal` + `Form` opened from a low-stock row for a single `filament`. Fields (match `ui-review/orders-mock-B-dialog.png`):
- shop `AutoComplete` — options from `useShops`, free text allowed (creates a shop on submit via `ensureShop`);
- order date `DatePicker` — **`initialValues={{ ordered_at: dayjs() }}` (today), backdatable**; converted to `ordered_at` on submit (`values.ordered_at.utc().format()`);
- `quantity` `InputNumber` (default 1, min 1);
- `price_per_unit` `InputNumber` (optional);
- `order_number` `Input` (optional);
- `url` `Input` (optional).

On submit: `const shopId = name ? await ensureShop(name) : undefined;` then `POST /order` with `buildMarkOrderedBody({ filament_id, quantity, orderedAt, shopId, pricePerUnit, orderNumber, url })` (via `useCreate`/`apiFetch`). On success invalidate the `filament` and `order` lists so `on_order` refreshes and the pill appears. Wire a "Mark as ordered" button/link onto each **non-on-order** low-stock row in both `home/index.tsx` (dashboard tab) and `lowstock/index.tsx` (on-order rows show the pill instead).

- [ ] **Step 5: Build the bulk Create-order modal (US2)**

Create `client/src/pages/orders/createOrderModal.tsx` — opened from the Low Stock full page's multi-select. It shows a table of the selected filaments with an editable quantity per row (default = `Math.max(1, Math.ceil(shortfall / spoolWeight))` or simply 1), an optional shop `AutoComplete` (reusing `useShops`), and an order-date `DatePicker` (today, backdatable). Submit `buildBulkOrderBody(selected, orderedAt, shopId)` via `POST /order`; on success invalidate the `filament` + `order` lists so each row shows the Ordered pill. Add antd `rowSelection` + a "Create order" button (enabled when ≥1 row is selected) to `lowstock/index.tsx`. Match the bulk variant of `ui-review/orders-mock-A-shoppinglist.png`.

- [ ] **Step 6: Add i18n keys**

Extend the `orders` namespace in `client/public/locales/en/common.json`:
```json
"orders": {
  "mark_ordered": "Mark as ordered",
  "create_order": "Create order",
  "shop": "Shop",
  "shop_placeholder": "Type a shop name (creates it if new)",
  "order_date": "Order date",
  "quantity": "Quantity",
  "price_per_unit": "Price / spool",
  "order_number_field": "Order number",
  "url": "Order link",
  "selected_count": "{{count}} selected"
}
```

- [ ] **Step 7: Type-check, lint, format, unit tests; screenshot; commit**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/orders src/pages/lowstock src/pages/home && npx vitest run
```
Expected: all green. Run the app, open the dialog from a low-stock row, and **screenshot it against `ui-review/orders-mock-B-dialog.png`** (confirm the order-date field defaults to today and is backdatable). Commit:
```bash
cd .. && git add client/ && git commit -m "feat(#298): US1 mark-as-ordered dialog + US2 bulk order

Shop autocomplete with inline create, order-date DatePicker defaulted to today
(backdatable -> ordered_at), quantity/price/number/url; single-line order on
submit. Bulk multi-select on the Low Stock page builds one order per selection.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 11 (UI, gated): US3 arrival dialog (split) + spool-create banner

**Branch:** `claude/orders-ui-arrival`.

**Goal:** From the Orders page, "Arrived…" opens the approved arrival dialog (`ui-review/orders-mock-D-arrival-split.png`): a row per line with a **checkbox**, an **"N of M outstanding"** quantity `InputNumber` (default = outstanding), already-arrived lines shown **disabled with a ✓**, a **create-spools toggle** (carrying each line's price), and an optional location; submit `POST /order/{id}/arrive` with per-line quantities (a partial delivery splits the line). Also: creating a spool for an on-order filament shows a banner offering to complete that filament's outstanding line.

**Files:**
- Create: `client/src/pages/orders/arriveModal.tsx` (per-line checkboxes + quantities; body builder)
- Create: `client/src/pages/orders/onOrderBanner.tsx` (spool-create banner)
- Modify: `client/src/pages/orders/index.tsx` (wire the "Arrived…" action → `arriveModal`)
- Modify: `client/src/pages/spools/create.tsx` (render the banner when the chosen filament's `on_order` is set)
- Modify: `client/public/locales/en/common.json`

**Interfaces (pure logic):**
- `buildArriveBody(lines, createSpools, locationId?)` → `{ lines: [{line_id, quantity?}], create_spools, location_id? }`, omitting `quantity` for a fully delivered line, dropping unselected/zero lines, and setting `location_id` only when given.

- [ ] **Step 1: Write the failing arrive-body test (the mock-D split scenario)**

Create `client/src/pages/orders/arriveModal.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { buildArriveBody } from "./arriveModal";

describe("buildArriveBody", () => {
  it("splits a partial line, keeps a full line as-is, and drops unselected lines", () => {
    const body = buildArriveBody(
      [
        { line_id: 1, quantity: 2, outstanding: 4, selected: true }, // partial -> split
        { line_id: 2, quantity: 1, outstanding: 1, selected: true }, // full -> no quantity
        { line_id: 3, quantity: 3, outstanding: 3, selected: false }, // unchecked -> omitted
      ],
      true,
      7,
    );
    expect(body).toEqual({
      lines: [{ line_id: 1, quantity: 2 }, { line_id: 2 }],
      create_spools: true,
      location_id: 7,
    });
  });
  it("omits location_id when no location chosen and drops zero-quantity lines", () => {
    const body = buildArriveBody([{ line_id: 1, quantity: 0, outstanding: 2, selected: true }], false);
    expect(body).toEqual({ lines: [], create_spools: false });
  });
});
```
Run: `cd client && npx vitest run src/pages/orders/arriveModal.test.ts` → FAIL.

- [ ] **Step 2: Implement `buildArriveBody`**

In `client/src/pages/orders/arriveModal.tsx`, export:
```typescript
export interface ArriveLineInput {
  line_id: number;
  quantity: number;
  outstanding: number;
  selected: boolean;
}

export function buildArriveBody(
  lines: ArriveLineInput[],
  createSpools: boolean,
  locationId?: number,
): { lines: { line_id: number; quantity?: number }[]; create_spools: boolean; location_id?: number } {
  const out = lines
    .filter((l) => l.selected && l.quantity > 0)
    .map((l) => (l.quantity >= l.outstanding ? { line_id: l.line_id } : { line_id: l.line_id, quantity: l.quantity }));
  const body: { lines: { line_id: number; quantity?: number }[]; create_spools: boolean; location_id?: number } = {
    lines: out,
    create_spools: createSpools,
  };
  if (locationId !== undefined) body.location_id = locationId;
  return body;
}
```
Run the test again → PASS.

- [ ] **Step 3: Build the arrival dialog**

In the same file, build the modal from a given `order`. For each line:
- **arrived** (`line.arrived_at` set): render a disabled row with the filament name and a green ✓ (`orders.arrived_check`), no input;
- **outstanding**: a `Checkbox` (default checked), the filament name, and an `InputNumber` (min 1, max = outstanding, default = outstanding) labelled **"{{delivered}} of {{outstanding}} outstanding"** (`orders.n_of_m`). Show a live split preview per line when `delivered < outstanding` ("{{delivered}} will arrive, {{rest}} stay on order" — `orders.split_preview`).

A `create_spools` `Switch` (default on) and an optional location `Select` sit below the list. On submit, call `buildArriveBody(rows, createSpools, locationId)` and `POST /order/{order.id}/arrive` (via `apiFetch`/`useCustomMutation`); on success invalidate the `order`, `filament`, and `spool` lists so the state pill, the low-stock pills, and the spool count all refresh. Wire the Orders-page "Arrived…" action (Task 9 stub) to open this modal for its order. Match `ui-review/orders-mock-D-arrival-split.png`.

- [ ] **Step 4: Build the spool-create banner**

Create `client/src/pages/orders/onOrderBanner.tsx` — an antd `Alert type="info"` shown on the spool create page when the selected filament's `on_order` is set: "This filament is on order (order #{{id}}) — mark its line arrived?" (`orders.banner`), with an action button that opens the arrive modal scoped to that filament's `on_order.order_id`. Render `<OnOrderBanner filament={selectedFilament} />` in `client/src/pages/spools/create.tsx` near the filament-selection field, guarded by `selectedFilament?.on_order`.

- [ ] **Step 5: Add i18n keys**

Extend the `orders` namespace:
```json
"orders": {
  "arrived_check": "Arrived",
  "n_of_m": "{{delivered}} of {{outstanding}} outstanding",
  "split_preview": "{{delivered}} will arrive, {{rest}} stay on order",
  "create_spools": "Create spools for the delivered items",
  "location": "Location",
  "banner": "This filament is on order (order #{{id}}) — mark its line arrived?",
  "mark_arrived": "Mark arrived"
}
```

- [ ] **Step 6: Type-check, lint, format, unit tests; screenshot; commit**

Run:
```bash
cd client && npx tsc --noEmit && npm run lint && npx prettier --write src/pages/orders src/pages/spools && npx vitest run
```
Expected: all green. Run the app, open the arrival dialog on a multi-quantity order, deliver a partial quantity, and **screenshot it against `ui-review/orders-mock-D-arrival-split.png`** (checkboxes, "N of M outstanding", disabled ✓ rows, create-spools toggle). Commit:
```bash
cd .. && git add client/ && git commit -m "feat(#298): US3 split arrival dialog + spool-create banner

Per-line checkboxes with 'N of M outstanding' quantities (partial -> split),
already-arrived lines disabled with a check, create-spools toggle carrying price;
POST /order/{id}/arrive. Spool-create banner offers to complete an on-order line.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 12 (UI, gated): e2e journeys

**Branch:** `claude/orders-ui-e2e`.

**Goal:** Playwright journeys covering the redesign end-to-end: mark-as-ordered (US1), bulk order (US2), split arrival + banner (US3), and the merged low-stock sections + always-visible nav.

**Files:**
- Create: `client/e2e/journeys/orders.spec.ts` (follow the conventions in `client/e2e/journeys/print-dialog.spec.ts` and `home.spec.ts` — API-seed via `request`, antd button/radio labels clicked by text)

- [ ] **Step 1: Prepare the e2e build env**

Run:
```bash
cd client
echo "VITE_APIURL=/api/v1" > .env.production
npm run build
```
Expected: the production build succeeds (required before the e2e run per the repo convention).

- [ ] **Step 2: Write the journeys**

Create `client/e2e/journeys/orders.spec.ts` following `print-dialog.spec.ts`'s structure (a `seedFilament`/`seedSpool`/`seedOrder` helper via `request.post(\`${APP_BASE_URL}/api/v1/…\`)`). Four journeys — **do not** click any real browser Print; interact with antd controls by their visible text:
1. **merged low-stock sections + nav:** seed one filament with a `low_stock_threshold` below its stock and one filament with no threshold but stock below the 200 g fallback → open the dashboard → assert there is a single **"Low Stock"** tab and **no "Shopping List" tab**, that both the "Below your set threshold" and "Below the … default" section headers appear, and that **"Low Stock"** and **"Orders"** nav items are both visible.
2. **mark-as-ordered (US1):** from the Low Stock page (`/lowstock`), click "Mark as ordered" on a row → fill the shop autocomplete (inline create) + quantity/price → confirm the order-date field defaults to today → submit → assert the calm blue `Ordered · … · <shop>` pill appears on the row (and the filament's `on_order` is set via an API check).
3. **bulk order (US2):** two low-stock filaments → `/lowstock` → multi-select both rows → "Create order" → edit quantities → submit → assert the Orders page (always in nav) lists one order summarising two filaments and both rows show the Ordered pill.
4. **split arrival (US3):** API-seed an order of quantity 4 for one filament → Orders page → "Arrived…" → set delivered = 2 with create-spools on → submit → assert 2 spools now exist and the order still shows **Open** / "2 of 4 arrived". Then open the spool create page for that filament and assert the on-order banner appears.

- [ ] **Step 3: Run the e2e suite**

Run: `cd client && npm run test:e2e -- orders.spec.ts`
Expected: all four journeys pass.

- [ ] **Step 4: Lint, format, commit**

Run:
```bash
cd client && npm run lint && npx prettier --write e2e/journeys/orders.spec.ts
cd .. && git add client/ && git commit -m "test(#298): e2e journeys — merged low-stock, mark-as-ordered, bulk, split arrival

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
- **UX US1/US2/US3/US5/US6 + 2026-07-19 low-stock redesign** (spec §"UX", §"Low-stock redesign", Decisions #6): Task 8 (merged per-filament Low Stock, the `low_stock_fallback_g` setting, dashboard tab + KPI badge), Task 9 (always-visible Low Stock & Orders nav + pages, inline threshold edit), Task 10 (US1 mark-as-ordered dialog — shop autocomplete + order-date DatePicker defaulted to today; US2 bulk order), Task 11 (US3 split arrival dialog + spool-create banner), Task 12 (e2e). US5 works-without-config via the shipped 200 g fallback + always-visible-but-empty Orders page; US6 satisfied by the on_order field (Task 5). ✓ (All mockup-gated on Task 7; screenshots vs `ui-review/orders-mock-A/B/C/D.png` after each UI task.)
- **Mockup gate** (project rule): Task 7 STOPS for approval before any UI. ✓
- **OUT of scope, correctly deferred to Phase 2** (spec §"Phasing"): SpoolmanDB catalog, `purchase_options` endpoint, `purchase_regions` setting, US4 — not in this plan. ✓
- **Edge cases** (spec §"Edge cases"): zero-line order = arrived (test in Task 3); multiple open orders → oldest (Task 5); un-arriving via PATCH lines full-replace (Task 3 semantics); split bookkeeping (Task 4); quantity ≥ 1 validation (arrive + line params). ✓
