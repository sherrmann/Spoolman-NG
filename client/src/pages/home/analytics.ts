import dayjs from "dayjs";
import { IFilament } from "../filaments/model";
import { ISpool } from "../spools/model";

// Pure, framework-free dashboard analytics extracted from home/index.tsx so the
// KPI/inventory math can be unit-tested against hand-computed oracles and
// invariants rather than through a rendered component. See TESTING_STRATEGY.md.

// A spool with no weight information at all falls back to this nominal total so
// the low-stock ratio stays finite.
export const DEFAULT_TOTAL_WEIGHT = 1000;

export interface MaterialStat {
  count: number;
  weight: number;
}

/** Effective stock weight of one spool, using the remaining→initial→filament fallback. */
export function spoolStockWeight(spool: ISpool): number {
  return spool.remaining_weight ?? spool.initial_weight ?? spool.filament.weight ?? 0;
}

/** Total remaining filament weight across all spools (headline KPI). */
export function totalRemainingWeight(spools: ISpool[]): number {
  return spools.reduce((sum, s) => sum + spoolStockWeight(s), 0);
}

/** Effective full-spool price of one spool: its own price, falling back to its filament's. */
function effectiveSpoolPrice(s: ISpool): number | undefined {
  return s.price ?? s.filament.price;
}

/**
 * Estimated value of the filament currently in stock. Each spool contributes its effective
 * price (spool price, else filament price — the same fallback the backend applies when sorting
 * and costing) scaled by its remaining fraction, so a half-used spool counts half its price.
 * Spools with no weight information count as full; spools with no price anywhere contribute 0.
 */
export function totalValue(spools: ISpool[]): number {
  return spools.reduce((sum, s) => {
    const price = effectiveSpoolPrice(s);
    if (price == null) return sum;
    return sum + price * Math.min(1, Math.max(0, remainingFraction(s)));
  }, 0);
}

/** Number of distinct materials across the filament catalog; filaments without one don't count. */
export function distinctMaterialCount(filaments: IFilament[]): number {
  return new Set(filaments.map((f) => f.material).filter((m): m is string => !!m)).size;
}

/** Remaining stock fraction of one spool; a missing remaining weight counts as a full spool. */
function remainingFraction(s: ISpool): number {
  const total = s.initial_weight ?? s.filament.weight ?? DEFAULT_TOTAL_WEIGHT;
  return (s.remaining_weight ?? total) / total;
}

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

/** Human label for a filament: "Vendor - Name", falling back to the name or id. */
export function getFilamentName(filament: IFilament): string {
  const base = filament.name ?? filament.id.toString();
  if (filament.vendor && "name" in filament.vendor) {
    return `${filament.vendor.name} - ${base}`;
  }
  return base;
}

/** The most-recently-used spools, newest first, capped at `limit`. Does not mutate the input. */
export function recentSpools(spools: ISpool[], limit = 5): ISpool[] {
  return spools
    .filter((s) => s.last_used)
    .map((s) => [dayjs(s.last_used).valueOf(), s] as const)
    .sort((a, b) => b[0] - a[0])
    .slice(0, limit)
    .map(([, s]) => s);
}

/** Count + total weight grouped by material (default "Unknown"), heaviest group first. */
export function materialBreakdown(spools: ISpool[]): [string, MaterialStat][] {
  const map: Record<string, MaterialStat> = {};
  spools.forEach((s) => {
    const mat = s.filament.material ?? "Unknown";
    if (!map[mat]) map[mat] = { count: 0, weight: 0 };
    map[mat].count++;
    map[mat].weight += spoolStockWeight(s);
  });
  return Object.entries(map).sort((a, b) => b[1].weight - a[1].weight);
}

/** Spool count grouped by location (empty → `noLocationLabel`), most-populated first. */
export function locationBreakdown(spools: ISpool[], noLocationLabel: string): [string, number][] {
  const map: Record<string, number> = {};
  spools.forEach((s) => {
    const loc = s.location || noLocationLabel;
    map[loc] = (map[loc] ?? 0) + 1;
  });
  return Object.entries(map).sort((a, b) => b[1] - a[1]);
}

/** Spool count grouped by vendor name (unknown → "?"), most-populated first. */
export function vendorBreakdown(spools: ISpool[]): [string, number][] {
  const map: Record<string, number> = {};
  spools.forEach((s) => {
    const name = s.filament.vendor && "name" in s.filament.vendor ? s.filament.vendor.name : "?";
    map[name] = (map[name] ?? 0) + 1;
  });
  return Object.entries(map).sort((a, b) => b[1] - a[1]);
}

/** The vendor owning the most spools, or "-" when there are no spools. */
export function topVendor(spools: ISpool[]): string {
  return vendorBreakdown(spools)[0]?.[0] ?? "-";
}

/** Number of spools registered within the last `days` days relative to `now`. */
export function registeredWithinDays(spools: ISpool[], days: number, now: dayjs.Dayjs = dayjs()): number {
  const cutoff = now.subtract(days, "day");
  return spools.filter((s) => dayjs(s.registered).isAfter(cutoff)).length;
}

/** "#rrggbb" swatch for a spool, preferring its own colour override (#74), then the filament colour,
 * defaulting to a mid-grey when none is set. Multi-colour is out of scope for this single-swatch chart. */
export function getColorHex(spool: ISpool): string {
  return "#" + (spool.color_hex ?? spool.filament.color_hex ?? "555555").replace("#", "");
}

/** Human label for a spool: "Vendor - Name", falling back to the filament name or id. */
export function getSpoolName(spool: ISpool): string {
  if (spool.filament.vendor && "name" in spool.filament.vendor) {
    return `${spool.filament.vendor.name} - ${spool.filament.name}`;
  }
  return spool.filament.name ?? spool.filament.id.toString();
}

/** Remaining-weight percentage (0–100, clamped) for a progress bar. */
export function getWeightPct(spool: ISpool): number {
  const total = spool.initial_weight ?? spool.filament.weight ?? DEFAULT_TOTAL_WEIGHT;
  const remaining = spool.remaining_weight ?? total;
  return Math.max(0, Math.min(100, (remaining / total) * 100));
}

/** Age labels turn amber past this many days unused, red past STALE_ALERT_DAYS (#202). */
export const STALE_WARN_DAYS = 90;
export const STALE_ALERT_DAYS = 180;

/** Below this remaining fraction a spool counts as finished, not stale (#202). */
const DEPLETED_FRACTION = 0.02;

export interface StaleSpool {
  spool: ISpool;
  /** The date the staleness is measured from: last_used, or registered when never used. */
  staleSince: string;
  neverUsed: boolean;
}

/**
 * The least-recently-used active spools, oldest first (#202). Never-used spools rank by
 * their registration date — a two-year-old unopened spool outranks one printed months ago.
 * Near-empty spools are excluded: a finished spool is "stale" forever, but the right
 * action there is archiving, not drying.
 */
export function staleSpools(spools: ISpool[], limit = 5): StaleSpool[] {
  return spools
    .filter((s) => remainingFraction(s) >= DEPLETED_FRACTION)
    .map((s) => ({ spool: s, staleSince: s.last_used ?? s.registered, neverUsed: !s.last_used }))
    .sort((a, b) => dayjs(a.staleSince).valueOf() - dayjs(b.staleSince).valueOf())
    .slice(0, limit);
}
