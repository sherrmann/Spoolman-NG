# Orders, Shops & region-aware purchase options — design

**Date:** 2026-07-19 · **Status:** approved (maintainer Sam) · **Scope:** Spoolman-NG core (this repo) + SpoolmanDB catalog fork · **Closes:** #298 (Phase 1), #299 (Phase 2)

## Context

Two open issues asked for adjacent things: #298 wants a spool's low-stock alarm to quiet down once a replacement is on its way ("ordered" state), and #299 wants region-aware "where can I buy this" links. A first pass at #298 landed today in PR #309 as three flat nullable columns on `filament` (`ordered_at`, `order_url`, `order_note`, migration `e8b3c6d9f2a5`). Those model on-order state as a property of a product type, which cannot group a bulk order, cannot capture arrival into spools, and has no place for a shop. Because #309 is merged but **unreleased**, we can revert it cleanly before it becomes wire-visible API. So we paused, and this is the design that replaces it: first-class Orders + Shops in core, plus a region-aware catalog artifact in SpoolmanDB. Wire-compatibility with upstream's v1 REST/WS API is a hard constraint — everything below is additive, and PR 0 removes the unreleased #309 fields before anyone depends on them.

## Goals / non-goals

**Goals**
- Calm a filament's low-stock alarm while replenishment is on its way.
- Group the lines of a single bulk order together.
- Capture an order's arrival into real spools, carrying per-unit prices.
- Answer "where can I buy this?" region-aware, from the catalog.
- Keep every part optional: a user who ignores orders sees today's UI unchanged.
- Give HACS/Home Assistant integrations a machine-readable on-order signal.

**Non-goals**
- Order lifecycle beyond `open`/`arrived` — no shipped, tracking, or partial arrivals.
- Catalog prices, customs, or shipping-cost modeling.
- Coupling a user's personal shops to any community store registry.

## Data model (Spoolman core)

New tables mirror existing entity conventions in `spoolman/database/models.py` (plain `String`/`Text`/`Integer`/`Float` columns, `registered` timestamp, child `*Field` tables for extras — no native JSON/ARRAY columns exist today).

- **Shop**: `name` (unique, required), `homepage` (nullable), `ships_to` (list of free-form region strings such as `"CH"`, `"EU"`, `"DE"`), `comment` (nullable), `registered`. `ships_to` is stored as a comma-separated string in a `Text` column — the fit for the current schema, which has no JSON/list columns; serialized to/from a JSON array at the API edge.
- **Order**: `shop_id` (nullable FK → shop), `ordered_at` (datetime, default now), `order_number` (nullable), `url` (nullable), `comment` (nullable), `state` (`open` | `arrived`), `arrived_at` (nullable), `registered`.
- **OrderLine**: `order_id` (FK → order), `filament_id` (FK → filament), `quantity` (int, `>= 1`, default 1), `price_per_unit` (nullable float). No unique constraint on `(order_id, filament_id)` — the same filament may appear twice in one order.
- **No new columns on `filament`.** "On order" is derived at read time from open order lines, not stored.

**Deletion semantics** (mirror the existing vendor↔filament restriction):
- Deleting a Shop is restricted while any Order references it.
- Deleting a Filament is restricted while any OrderLine references it.
- Deleting an Order cascades to its OrderLines.

**PR 0 revert:** drop the three unreleased flat fields from PR #309 — the `filament` columns (`ordered_at`, `order_url`, `order_note`), migration `e8b3c6d9f2a5`, their API fields in `spoolman/api/v1/models.py` and `spoolman/api/v1/filament.py`, the `spoolman/database/filament.py` plumbing, and their tests.

## API (v1, additive)

- **`/shop` CRUD** mirroring `/vendor`: list, get, create, patch, delete, plus WebSocket events and find/filter query params as fits the existing vendor pattern.
- **`/order` CRUD**: order lines are a nested array on the order payload; a PATCH that includes `lines` is a **full replace** of the line set, not a merge (omitting `lines` leaves them untouched). WebSocket events on create/update/delete.
- **`POST /order/{order_id}/arrive`**, body `{ create_spools: bool, location_id?: int }`: sets `state = arrived` and `arrived_at = now`; if `create_spools` is true, creates `quantity` spools per line, copying each line's `price_per_unit` into the new spool's `price` and assigning `location_id` when given; returns the list of created spools (empty when `create_spools` is false).
- **Filament `on_order` computed field** on list and detail: `{ order_id, ordered_at } | null`, the **oldest open** order containing that filament. It uses the same aggregate mechanics as `spool_count` / `remaining_weight` — computed on the top-level query, `null` in nested payloads. This is the HA/HACS hook.
- **New instance setting `purchase_regions`**: a list of region strings via the existing settings API. Unset = no region filtering.
- **New purchase-options endpoint** for a filament: the server fetches and caches the SpoolmanDB `purchase_options.json` artifact alongside the existing external-DB sync, then returns options for the filament matched by EAN when known, else by `external_id`, filtered to options whose `ships_to` intersects `purchase_regions` (all options when `purchase_regions` is unset).

## UX (progressive disclosure)

UI is progressively disclosed: nothing new is visible until the user opts in, and the Orders nav item appears only once at least one order exists. Per project rule, **UI implementation happens only after mockup review**. Affiliate links in the UI are labeled as such, and a global toggle switches every rendered link to its `url_plain` variant.

**US1 — quick reorder.** As a user seeing a low-stock filament, I want to mark it ordered in one step so its alarm quiets. From a low-stock row, "Mark as ordered" opens a single dialog: shop autocomplete (creating a shop inline if it doesn't exist), plus optional url, order number, quantity, and price-per-unit. On submit, a one-line order is created. *Acceptance:* the row shows a calm blue pill "Ordered · &lt;age&gt; · &lt;shop&gt;"; the filament's `on_order` becomes non-null; no page beyond the dialog is required.

**US2 — bulk order.** As a user restocking several filaments, I want one order covering all of them. From the dashboard shopping list, multi-select rows → "Create order" builds a single order with one line per selected filament, quantities editable before save. *Acceptance:* one order exists with N lines; each selected filament shows the Ordered pill; quantities persist as entered.

**US3 — arrival.** As a user whose order arrived, I want to turn it into spools without re-keying. Creating a spool for an on-order filament shows a banner offering to complete the order (create the spools per line, prices carried); alternatively the order page's "Arrived" button does the same via `POST /order/{id}/arrive`. *Acceptance:* spools are created with `price` = line `price_per_unit`; the order is `arrived`; the Ordered pills clear.

**US4 — where to buy.** As a user looking at a low-stock filament with a catalog match, I want region-filtered shop links. The filament view shows purchase options filtered by `purchase_regions`; clicking one can prefill the US1 "Mark as ordered" dialog with that shop. *Acceptance:* only options shipping to a configured region appear (all when unset); a click carries the shop into the dialog.

**US5 — opt-out.** As a user who never uses orders, I want the app to look essentially as it does today. No Orders nav item until an order exists; Shops are managed under Settings and via the inline autocomplete only; no new columns or pills intrude on default views. *Acceptance:* with zero orders, the only new UI anywhere is the small "Mark as ordered" affordance on low-stock rows (the entry point has to exist before the first order); everything else is unchanged.

**US6 — Home Assistant.** As an HA user, I want automations to stop nagging me about stock I've already reordered. Automations read the filament's `on_order` field to suppress or downgrade low-stock notifications. *Acceptance:* `on_order` is non-null exactly while an open order contains the filament, and reads through the v1 API and HACS integration unchanged.

## SpoolmanDB purchase_options (catalog side)

- **New fork-owned source directory** `purchase_options/*.json`, validated by a new `purchase_options.schema.json`. Fork-owned new files have zero upstream-sync conflict surface.
- **Compiled to a separate Pages artifact** `purchase_options.json` — never inlined into `filaments.json`. Inlining would multiply each option across the combinatorial weight × diameter × spool_type expansion (1.5–3× payload bloat on an already ~5.3MB file) and would collide with the weekly upstream sync. A separate artifact avoids both.
- **Entry shape:**
  ```json
  { "ean": "<8-14 digits>", "id": "<compiled filament id>",
    "options": [
      { "store": "string", "url": "string", "ships_to": ["CH", "EU"],
        "affiliate": false, "url_plain": "string (required when affiliate=true)" }
    ] }
  ```
  Each entry carries `ean` **or** `id` (or both). `affiliate` defaults to `false`; `url_plain` is required whenever `affiliate` is `true`.
- **Pipeline (`build.yml`):** extend the validate step to cover the new schema; add a small compile/merge step that emits `purchase_options.json`; the deploy step copies it to Pages alongside `filaments.json`.
- **Keyed lookup:** consumers try EAN first, then fall back to compiled `id`. EAN is the semantically correct key (a purchasable SKU), but catalog EAN coverage is near zero today (16 entries) — the compiled `id` bridges the gap until EAN coverage grows.

## Phasing

- **PR 0 — revert.** Drop the unreleased #309 flat fields (data model section above). Small, self-contained.
- **Phase 1 — Spoolman core** (closes #298): Shop/Order/OrderLine entities + migration, the `/shop` and `/order` APIs, the `arrive` endpoint, the `on_order` computed field, and the US1–US3/US5–US6 UX (post-mockup).
- **Phase 2 — catalog** (closes #299): SpoolmanDB schema + pipeline + seed data, the purchase-options endpoint and `purchase_regions` setting, and the US4 purchase-links UI. Affiliate labeling and the `url_plain` strip toggle land last and demand-gated, consistent with the transparent, user-controllable monetization plan.
- **Testing:** fast in-process integration tests under `tests/integration/` per endpoint, including arrival spool-creation and both deletion-restriction cases; e2e journeys for mark-as-ordered, bulk order, and the arrival banner; client unit tests for new pure logic (e.g. the shopping-list selection → order mapping); migrations are exercised automatically by the `tests_deployment` upgrade suites.

## Edge cases / error handling

- **Order with zero lines:** allowed (a note-only order); it surfaces no pills and no `on_order` signal.
- **Multiple open orders for one filament:** allowed; `on_order` reports the **oldest**, and the UI pill reflects that same order.
- **Reopening an arrived order:** allowed via PATCH `state` back to `open`; spools already created stay untouched.
- **Arrive with `create_spools=true` on a bad line:** `quantity >= 1` is enforced by validation; the filament FK is enforced by the schema — neither can produce a zero-quantity or orphan spool.
- **Shop delete with orders / filament delete with lines:** rejected with a 409-style restriction and a clear message, matching existing vendor-delete behavior.
- **Purchase-options fetch failure or absent artifact:** the endpoint returns an empty list; the UI shows nothing, so the feature is simply invisible.
- **`purchase_regions` unset:** all options are shown, unfiltered.

## Decisions log

1. **Two-state, grouped orders — not a full lifecycle.** `open`/`arrived` only; no shipped/tracking/partial arrivals. Keeps the model small and matches how a hobbyist actually tracks a reorder.
2. **Shop is a first-class entity**, distinct from Vendor (manufacturer). A reorder targets a shop, not a manufacturer, and shops carry region shipping info.
3. **Drop the #309 flat fields pre-release.** They are merged but unreleased, so reverting now avoids ever shipping product-type-scoped order state into the wire-stable v1 API.
4. **EAN + id-keyed, separate catalog artifact.** EAN is the right key but under-covered; compiled `id` bridges. A separate `purchase_options.json` avoids combinatorial payload bloat and upstream-sync conflicts.
5. **Multi-region preference list, not a single region.** Reflects Swiss cross-border shopping reality (a CH user routinely buys from DE/EU stores); `purchase_regions` is a list, matched by intersection.
6. **Affiliate links transparent and user-toggleable.** Labeled in the UI, with a global switch to `url_plain`; affiliate work is demand-gated and lands last.
