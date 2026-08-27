import type { APIRequestContext } from "@playwright/test";

/**
 * Seeding for this fork's Home dashboard tests.
 *
 * Data is created through the REST API rather than shipped as a fixture database: a checked-in
 * .db would have to be migrated forward on every schema change, and the point of these tests is
 * the page, not the storage layer. Names are suffixed per run so a retry -- or a shared instance
 * -- cannot collide with an earlier pass.
 */

let counter = 0;
export function unique(prefix: string): string {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter}`;
}

export interface Seeded {
  /** Filament carrying an explicit low_stock_threshold it falls under. */
  explicitLowName: string;
  /** Filament with no threshold of its own, falling under the global fallback. */
  fallbackLowName: string;
  /** The explicit-threshold filament also has an open order, so it shows the on-order pill. */
  orderedName: string;
  vendorName: string;
}

/** The global fallback, in grams. Filaments below this are low even with no threshold set. */
const FALLBACK_G = 150;

export async function seedInventory(api: APIRequestContext): Promise<Seeded> {
  const vendorName = unique("Vendor");
  const vendor = await post(api, "/vendor", { name: vendorName, empty_spool_weight: 190 });

  await post(api, "/setting/low_stock_fallback_g", `"${FALLBACK_G}"`, true);

  // Comfortably stocked, and in a second material so the material breakdown has more than one
  // bar and the "N materials" KPI footer is not trivially 1.
  const healthy = await filament(api, vendor.id, unique("Healthy"), "PETG", 1000, null);
  await post(api, "/spool", { filament_id: healthy.id, used_weight: 100, location: "Shelf A" });

  // Under its own threshold, and on order -- this row must show the pill.
  const explicit = await filament(api, vendor.id, unique("Explicit"), "PLA", 1000, 400);
  await post(api, "/spool", { filament_id: explicit.id, used_weight: 900, location: "Shelf B" });
  await post(api, "/order", {
    ordered_at: new Date(Date.now() - 6 * 864e5).toISOString(),
    order_number: unique("SO"),
    lines: [{ filament_id: explicit.id, quantity: 1, price_per_unit: 25 }],
  });

  // No threshold of its own, but under the global fallback.
  const fallback = await filament(api, vendor.id, unique("Fallback"), "PLA", 1000, null);
  await post(api, "/spool", { filament_id: fallback.id, used_weight: 950, location: "Shelf C" });

  return {
    explicitLowName: explicit.name,
    fallbackLowName: fallback.name,
    orderedName: explicit.name,
    vendorName,
  };
}

async function filament(
  api: APIRequestContext,
  vendorId: number,
  name: string,
  material: string,
  weight: number,
  lowStockThreshold: number | null,
) {
  const body: Record<string, unknown> = {
    name,
    vendor_id: vendorId,
    material,
    color_hex: "3A7BD5",
    price: 24.99,
    density: 1.24,
    diameter: 1.75,
    weight,
    spool_weight: 190,
  };
  if (lowStockThreshold !== null) body.low_stock_threshold = lowStockThreshold;
  return post(api, "/filament", body);
}

async function post(
  api: APIRequestContext,
  path: string,
  body: unknown,
  raw = false,
): Promise<{ id: number; name: string }> {
  const res = await api.post(`/api/v1${path}`, {
    headers: { "Content-Type": "application/json" },
    // Settings take the bare JSON value as the whole body, not an object wrapping it.
    data: raw ? (body as string) : JSON.stringify(body),
  });
  if (!res.ok()) throw new Error(`POST ${path} -> ${res.status()} ${await res.text()}`);
  const text = await res.text();
  return text ? JSON.parse(text) : { id: 0, name: "" };
}

/** Counts straight from the API, to compare against what the KPI cards render. */
export async function apiCounts(api: APIRequestContext) {
  const [spools, filaments, vendors] = await Promise.all(
    ["/spool?allow_archived=false", "/filament", "/vendor"].map(async (p) =>
      ((await (await api.get(`/api/v1${p}`)).json()) as unknown[]).length,
    ),
  );
  return { spools, filaments, vendors };
}

/**
 * One filament that is low purely because of the global fallback, with its own vendor and spool.
 *
 * Write tests each seed their own rather than sharing the fixture above: they mutate what they
 * touch (setting a threshold, placing an order), and a shared row would make the result depend
 * on which test ran first.
 */
export async function seedLowFilament(
	api: APIRequestContext,
	prefix: string,
): Promise<{ id: number; name: string }> {
	const vendor = await post(api, "/vendor", { name: unique(`${prefix}Vendor`) });
	const name = unique(prefix);
	const filament = await post(api, "/filament", {
		name,
		vendor_id: vendor.id,
		material: "PLA",
		color_hex: "AA3355",
		price: 20,
		density: 1.24,
		diameter: 1.75,
		weight: 1000,
		spool_weight: 190,
	});
	await post(api, "/spool", { filament_id: filament.id, used_weight: 950, location: "Shelf Z" });
	return { id: filament.id, name };
}

/** Open orders that include a line for this filament. */
export async function openOrdersFor(api: APIRequestContext, filamentId: number) {
	const orders = (await (await api.get("/api/v1/order")).json()) as {
		state: string;
		lines: { filament_id: number }[];
	}[];
	return orders.filter(
		(o) => o.state === "open" && o.lines.some((l) => l.filament_id === filamentId),
	);
}

/** The filament's own low-stock threshold, straight from the API. */
export async function thresholdOf(api: APIRequestContext, filamentId: number) {
	const f = (await (await api.get(`/api/v1/filament/${filamentId}`)).json()) as {
		low_stock_threshold?: number | null;
	};
	return f.low_stock_threshold ?? null;
}

/** A shop, two filaments and one open order with a line for each. */
export async function seedOrder(api: APIRequestContext, prefix: string) {
	const vendor = await post(api, "/vendor", { name: unique(`${prefix}Vendor`) });
	const shop = await post(api, "/shop", { name: unique(`${prefix}Shop`) });
	const mk = async (suffix: string) => {
		const name = unique(`${prefix}${suffix}`);
		const f = await post(api, "/filament", {
			name,
			vendor_id: vendor.id,
			material: "PLA",
			color_hex: "5566AA",
			price: 20,
			density: 1.24,
			diameter: 1.75,
			weight: 1000,
			spool_weight: 190,
		});
		return { id: f.id, name };
	};
	const first = await mk("A");
	const second = await mk("B");
	const orderNumber = unique(`${prefix}-SO`);
	const order = await post(api, "/order", {
		ordered_at: new Date(Date.now() - 3 * 864e5).toISOString(),
		order_number: orderNumber,
		shop_id: shop.id,
		lines: [
			{ filament_id: first.id, quantity: 2, price_per_unit: 20 },
			{ filament_id: second.id, quantity: 5, price_per_unit: 30 },
		],
	});
	return { orderId: order.id, orderNumber, shopName: shop.name, first, second };
}

/** One order straight from the API, for checking what a write actually persisted. */
export async function orderById(api: APIRequestContext, orderId: number) {
	return (await (await api.get(`/api/v1/order/${orderId}`)).json()) as {
		state: string;
		order_number?: string;
		lines: { id: number; filament_id: number; quantity: number; arrived_at?: string }[];
	};
}

/**
 * A Location *entity* row (`/api/v1/locations`), which is what an arrival's `location_id` names.
 *
 * Distinct from the `location` string carried on a spool: the entity registry is a separate
 * table, and `/api/v1/location` (singular) returns only the distinct spool strings, with no ids.
 */
export async function seedLocation(api: APIRequestContext, prefix: string) {
  const name = unique(prefix);
  const created = await post(api, "/locations", { name });
  return { id: created.id, name };
}

/** Every non-archived spool, for checking where an arrival put the ones it created. */
export async function allSpools(api: APIRequestContext) {
  return (await (await api.get("/api/v1/spool?allow_archived=false")).json()) as {
    id: number;
    location?: string;
    filament: { id: number };
  }[];
}

/** A filament with its own vendor, for a feature that hangs off one filament. */
export async function seedFilament(api: APIRequestContext, prefix: string) {
  const vendor = await post(api, "/vendor", { name: unique(`${prefix}Vendor`) });
  const name = unique(prefix);
  const filament = await post(api, "/filament", {
    name,
    vendor_id: vendor.id,
    material: "PLA",
    color_hex: "3A7BD5",
    price: 22,
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
    spool_weight: 190,
  });
  return { id: filament.id, name, vendorName: vendor.name as string };
}

/** One calibration session with its steps, straight from the API. */
export async function calibrationSession(api: APIRequestContext, sessionId: number) {
  return (await (await api.get(`/api/v1/calibration/session/${sessionId}`)).json()) as {
    status: string;
    steps: {
      step_type: string;
      outputs?: Record<string, unknown> | null;
      selected_values?: Record<string, unknown> | null;
    }[];
  };
}

/** The calibration sessions recorded against a filament. */
export async function calibrationSessions(api: APIRequestContext, filamentId: number) {
  return (await (
    await api.get(`/api/v1/calibration/session?filament_id=${filamentId}`)
  ).json()) as { id: number; status: string }[];
}
