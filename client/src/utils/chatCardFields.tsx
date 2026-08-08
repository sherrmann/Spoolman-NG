import { Typography } from "antd";
import dayjs from "dayjs";
import { ReactNode } from "react";
import { DATE_FORMAT_LONG, DATE_TIME_FORMAT_LONG } from "./dateFormat";
import { formatWeight, numberFormatter } from "./parsing";

const { Text } = Typography;

/**
 * Rendering of the key/value payloads on the AI chat's confirm-cards (#378).
 *
 * The server hands the client raw model rows — `{ initial_weight_g: 1000.0, archived: false,
 * color_hex: "FF0000CC", ordered_at: "2026-07-20 09:00" }` — and the card used to print them
 * verbatim as `key: String(value)`. A confirm-card is the last thing a user reads before
 * destroying something, so it has to read like the rest of the UI, not like a database row:
 * every key gets a human label from the catalog the app already ships in 31 languages, and
 * every value is formatted by what it actually is.
 *
 * Kept out of chatDrawer.tsx (and free of hooks) so the label map, the formatters and the diff
 * are unit-testable without mounting a drawer.
 */

/** The subset of refine's translate function this module needs. */
export type TranslateFn = (key: string) => string;

/** What a formatted value needs from the app's settings — supplied by the caller's hooks. */
export interface CardValueContext {
  t: TranslateFn;
  /** `useCurrencyFormatter()`'s result, so prices use the configured currency and rounding. */
  currency: { format: (value: number) => string };
}

/**
 * Every key the AI tool layer can put in a card's `before`/`after`, mapped to an i18n key the
 * client already ships. Nothing here is a new translation: these are the same labels the spool,
 * filament, manufacturer and order screens use, so the card names a field exactly as the form
 * the user would otherwise edit does.
 *
 * Note the filament keys are DB column names (`settings_extruder_temp`, `weight`), not the tool
 * argument names (`extruder_temp`, `weight_g`) — the preview builders feed curated columns
 * straight into the card.
 */
export const CARD_FIELD_LABEL_KEYS: Readonly<Record<string, string>> = {
  // Spool
  id: "spool.fields.id",
  filament: "spool.fields.filament",
  location: "spool.fields.location",
  lot_nr: "spool.fields.lot_nr",
  archived: "spool.fields.archived",
  initial_weight_g: "spool.fields.initial_weight",
  remaining_weight_g: "spool.fields.remaining_weight",
  used_weight_g: "spool.fields.used_weight",
  // Shared between spool and filament
  material: "spool.fields.material",
  comment: "spool.fields.comment",
  price: "spool.fields.price",
  color_hex: "filament.fields.color_hex",
  // Filament (also covers the location/manufacturer `name`)
  name: "filament.fields.name",
  vendor: "filament.fields.vendor",
  density: "filament.fields.density",
  diameter: "filament.fields.diameter",
  weight: "filament.fields.weight",
  spool_weight: "filament.fields.spool_weight",
  article_number: "filament.fields.article_number",
  settings_extruder_temp: "filament.fields.settings_extruder_temp",
  settings_bed_temp: "filament.fields.settings_bed_temp",
  low_stock_threshold: "filament.fields.low_stock_threshold",
  spool_count: "filament.fields.spool_count",
  spools_created: "filament.fields.spool_count",
  // Order
  shop: "orders.shop",
  order_number: "orders.order_number",
  ordered_at: "orders.ordered_at",
  lines: "orders.lines_summary_title",
  units: "orders.quantity",
  status: "orders.state_title",
  outstanding_units: "orders.outstanding",
};

/**
 * The human label for a card field. A key the map does not know still must not reach the screen
 * as `snake_case_g`, so it degrades to a de-underscored, sentence-cased form — untranslated, but
 * readable, and only ever hit if the tool layer grows a field before this map does.
 */
export function cardFieldLabel(key: string, t: TranslateFn): string {
  const translationKey = CARD_FIELD_LABEL_KEYS[key];
  if (translationKey) return t(translationKey);
  const words = key.replace(/_g$/, "").replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// --- value formatting ------------------------------------------------------------------

/** Gram-valued fields, which go through the client's existing formatWeight (1000 -> "1 kg"). */
const WEIGHT_KEYS = new Set(["weight", "weight_g", "spool_weight", "low_stock_threshold"]);

function isWeightKey(key: string): boolean {
  return WEIGHT_KEYS.has(key) || key.endsWith("_weight_g");
}

/** Date-valued fields. `_at` covers `ordered_at`; the rest are the model's timestamp columns. */
const DATE_KEYS = new Set(["registered", "first_used", "last_used"]);

function isDateKey(key: string): boolean {
  return DATE_KEYS.has(key) || key.endsWith("_at");
}

// What the tool layer emits: "2026-07-20", "2026-07-20 09:00", or an ISO timestamp. Parsed
// strictly so a value that merely starts with digits (a lot number, say) is never mistaken
// for a date and silently reformatted.
const DATE_INPUT_FORMATS = ["YYYY-MM-DDTHH:mm:ss", "YYYY-MM-DD HH:mm:ss", "YYYY-MM-DD HH:mm", "YYYY-MM-DD"];

function formatDate(key: string, raw: string): string | null {
  const parsed = dayjs(raw, DATE_INPUT_FORMATS, true);
  if (!parsed.isValid()) return null;
  // `ordered_at` is a purchase date: the hour it was placed decides nothing about the order,
  // so it renders date-only even when the payload carries a time.
  if (key === "ordered_at") return parsed.format(DATE_FORMAT_LONG);
  const midnight = parsed.hour() === 0 && parsed.minute() === 0 && parsed.second() === 0;
  return parsed.format(midnight ? DATE_FORMAT_LONG : DATE_TIME_FORMAT_LONG);
}

function asNumber(value: unknown): number | null {
  const numeric = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(numeric) ? numeric : null;
}

/** "open" is the only order status without an existing standalone label; "arrived" reuses its. */
const STATUS_LABEL_KEYS: Readonly<Record<string, string>> = {
  open: "chat.confirm.status_open",
  arrived: "orders.state.arrived",
};

function formatStatus(value: string, t: TranslateFn): string {
  const translationKey = STATUS_LABEL_KEYS[value.toLowerCase()];
  if (translationKey) return t(translationKey);
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// --- colour ----------------------------------------------------------------------------

/** The basic-colour vocabulary a hex is named with. Keys live under `chat.confirm.color.*`. */
export const COLOR_NAMES = [
  "black",
  "white",
  "grey",
  "red",
  "orange",
  "yellow",
  "green",
  "cyan",
  "blue",
  "purple",
  "pink",
  "brown",
  "beige",
] as const;

/**
 * Name a 6-digit RGB hex with a basic colour word, via HSL rather than nearest-RGB distance:
 * plain RGB distance calls every dark colour "black" and every pale one "white", which is
 * exactly the pair of mistakes that would matter on a filament swatch. Returns the i18n key,
 * or null if the input is not a hex triplet.
 */
export function colorNameKey(rgbHex: string): string | null {
  if (!/^[0-9a-f]{6}$/i.test(rgbHex)) return null;
  const r = parseInt(rgbHex.slice(0, 2), 16) / 255;
  const g = parseInt(rgbHex.slice(2, 4), 16) / 255;
  const b = parseInt(rgbHex.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const lightness = (max + min) / 2;
  const chroma = max - min;
  const saturation = chroma === 0 ? 0 : chroma / (1 - Math.abs(2 * lightness - 1));

  const key = (name: (typeof COLOR_NAMES)[number]) => `chat.confirm.color.${name}`;

  // Achromatic first, so near-greys are never given a hue they don't perceptibly have.
  if (saturation < 0.12) {
    if (lightness < 0.18) return key("black");
    if (lightness > 0.85) return key("white");
    return key("grey");
  }

  let hue: number;
  if (max === r) hue = 60 * (((g - b) / chroma) % 6);
  else if (max === g) hue = 60 * ((b - r) / chroma + 2);
  else hue = 60 * ((r - g) / chroma + 4);
  if (hue < 0) hue += 360;

  if (lightness < 0.12) return key("black");
  if (lightness > 0.92 && saturation < 0.35) return key("white");
  // A dark, muted orange is brown, and a pale warm one is beige — both common filament colours
  // that a pure hue lookup would mislabel "orange".
  if (hue >= 15 && hue < 50 && lightness < 0.4) return key("brown");
  if (hue >= 20 && hue < 70 && lightness > 0.75) return key("beige");
  if (hue < 15 || hue >= 340) return key("red");
  if (hue < 45) return key("orange");
  if (hue < 70) return key("yellow");
  if (hue < 165) return key("green");
  if (hue < 200) return key("cyan");
  if (hue < 260) return key("blue");
  if (hue < 310) return key("purple");
  return key("pink");
}

/** A colour swatch plus its name — and, for an 8-digit value, the hex a name cannot express. */
function ColorValue({ value, t }: { value: string; t: TranslateFn }) {
  const normalised = value.trim().replace(/^#/, "").toUpperCase();
  const nameKey = /^[0-9A-F]{6}([0-9A-F]{2})?$/.test(normalised) ? colorNameKey(normalised.slice(0, 6)) : null;
  if (!nameKey) return <>{value}</>;
  // An 8-digit hex carries an alpha channel: two spools whose colour differs only in opacity
  // would both read "Red". Keep the hex alongside the name so no information a 6-digit name
  // would have carried is dropped.
  const hasAlpha = normalised.length === 8;
  return (
    <span>
      <span
        aria-hidden
        data-testid="chat-card-swatch"
        style={{
          display: "inline-block",
          width: 11,
          height: 11,
          borderRadius: 3,
          border: "1px solid rgba(140,140,140,0.5)",
          background: `#${normalised}`,
          verticalAlign: -1,
          marginInlineEnd: 6,
        }}
      />
      {t(nameKey)}
      {hasAlpha ? ` (#${normalised})` : ""}
    </span>
  );
}

/**
 * Render one card value as the UI would show it elsewhere: weights via formatWeight, prices via
 * the configured currency, dates locale-formatted, booleans as the app's Yes/No, colours as a
 * swatch and a name. Anything unrecognised still falls back to its string form, so a new field
 * degrades to today's behaviour rather than vanishing.
 */
export function formatCardValue(key: string, value: unknown, context: CardValueContext): ReactNode {
  const { t, currency } = context;

  if (value === null || value === undefined || value === "") {
    return (
      <Text type="secondary" italic>
        {t("chat.confirm.not_set")}
      </Text>
    );
  }

  if (typeof value === "boolean") return t(value ? "yes" : "no");

  if (key === "color_hex" && typeof value === "string") return <ColorValue value={value} t={t} />;

  if (key === "status" && typeof value === "string") return formatStatus(value, t);

  if (Array.isArray(value)) return value.map((entry) => String(entry)).join(", ");

  if (isDateKey(key) && typeof value === "string") {
    const formatted = formatDate(key, value);
    if (formatted !== null) return formatted;
  }

  const numeric = asNumber(value);
  if (numeric !== null) {
    if (isWeightKey(key)) return formatWeight(numeric);
    if (key === "price") return currency.format(numeric);
    if (key.endsWith("_temp")) return `${numberFormatter(numeric)} °C`;
    if (key === "diameter") return `${numberFormatter(numeric)} mm`;
    if (key === "density") return `${numberFormatter(numeric)} g/cm³`;
    return numberFormatter(numeric);
  }

  return String(value);
}

// --- which rows a card shows -----------------------------------------------------------

/**
 * Whether a row decides nothing about a create or a delete and should be left off the card.
 *
 * Only ever applied to the single-sided cards: `id` is already in the title ("Delete spool #1"),
 * an unset field is not part of what is being created or removed, and a default that carries no
 * information for the action (`archived: false` on a spool being created) is noise. Deliberately
 * NOT applied inside an update diff, where an unset value on one side IS the change.
 */
export function isDecorativeRow(key: string, value: unknown): boolean {
  if (key === "id") return true;
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value) && value.length === 0) return true;
  if (key === "archived" && value === false) return true;
  return false;
}

/** The rows a create/delete card shows, in payload order, minus the ones that decide nothing. */
export function cardValueRows(values: Record<string, unknown>): [string, unknown][] {
  return Object.entries(values).filter(([key, value]) => !isDecorativeRow(key, value));
}

export interface CardDiffRow {
  key: string;
  before: unknown;
  after: unknown;
}

function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * One row per CHANGED field, over the union of both sides' keys. A field missing from a side is
 * normalised to null so it renders as "not set → value" — the reader should never have to diff
 * two blocks by eye, and an unchanged field is not part of the decision.
 */
export function cardDiffRows(before: Record<string, unknown>, after: Record<string, unknown>): CardDiffRow[] {
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return keys
    .map((key) => ({ key, before: before[key] ?? null, after: after[key] ?? null }))
    .filter((row) => !sameValue(row.before, row.after));
}

/**
 * How a card's payload should be read. The tool layer builds a create with an empty `before`, a
 * delete with an empty `after`, and an update with both — so the shape of the payload, not the
 * tool name, decides whether the card is a listing or a diff.
 */
export function cardValueMode(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): "create" | "delete" | "diff" | "empty" {
  const hasBefore = Object.keys(before).length > 0;
  const hasAfter = Object.keys(after).length > 0;
  if (hasBefore && hasAfter) return "diff";
  if (hasAfter) return "create";
  if (hasBefore) return "delete";
  return "empty";
}
