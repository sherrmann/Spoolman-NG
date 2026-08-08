import { render } from "@testing-library/react";
import dayjs from "dayjs";
import "dayjs/locale/de";
import "dayjs/locale/en";
import { afterAll, describe, expect, it } from "vitest";
import en from "../../public/locales/en/common.json";
import {
  CARD_FIELD_LABEL_KEYS,
  CardValueContext,
  COLOR_NAMES,
  cardDiffRows,
  cardFieldLabel,
  cardValueMode,
  cardValueRows,
  colorNameKey,
  formatCardValue,
  isDecorativeRow,
} from "./chatCardFields";

// The confirm-card is the last thing a user reads before destroying something (#378), so what
// these tests pin is that no raw schema vocabulary survives to the screen: not the key names,
// not the raw floats, not `true`/`false`, not `∅`, and — on an update — not two blocks the
// reader has to diff by eye.

/** Identity translate: the assertions then read as "this exact catalog key was used". */
const t = (key: string) => key;

const context: CardValueContext = { t, currency: { format: (value) => `€${value.toFixed(2)}` } };

/** Resolves a dotted key against the real English catalog, so typos in the map are caught. */
function lookup(key: string): string | undefined {
  return key.split(".").reduce<unknown>((node, part) => {
    if (node !== null && typeof node === "object" && part in node) {
      return (node as Record<string, unknown>)[part];
    }
    return undefined;
  }, en) as string | undefined;
}

function text(key: string, value: unknown, ctx: CardValueContext = context): string {
  return render(<>{formatCardValue(key, value, ctx)}</>).container.textContent ?? "";
}

/**
 * Every key the AI tool layer can put in a card's before/after. Kept in the test so a new tool
 * field that lands without a label fails here rather than showing a user `outstanding_units`.
 */
const BACKEND_CARD_KEYS = [
  // spool
  "id",
  "filament",
  "material",
  "color_hex",
  "remaining_weight_g",
  "location",
  "lot_nr",
  "archived",
  "comment",
  "price",
  "used_weight_g",
  "initial_weight_g",
  // filament (curated DB column names)
  "name",
  "density",
  "diameter",
  "weight",
  "spool_weight",
  "article_number",
  "settings_extruder_temp",
  "settings_bed_temp",
  "low_stock_threshold",
  "vendor",
  "spool_count",
  // order
  "shop",
  "order_number",
  "ordered_at",
  "lines",
  "units",
  "status",
  "outstanding_units",
  "spools_created",
];

describe("confirm-card labels (#378)", () => {
  it("has a label for every key the tool layer can emit", () => {
    const unmapped = BACKEND_CARD_KEYS.filter((key) => !(key in CARD_FIELD_LABEL_KEYS));
    expect(unmapped).toEqual([]);
  });

  it("maps every field onto a translation the client already ships", () => {
    const broken = Object.entries(CARD_FIELD_LABEL_KEYS).filter(([, key]) => typeof lookup(key) !== "string");
    expect(broken).toEqual([]);
  });

  it("labels a field with the same wording the rest of the UI uses", () => {
    expect(cardFieldLabel("order_number", t)).toBe("orders.order_number");
    expect(cardFieldLabel("outstanding_units", t)).toBe("orders.outstanding");
    expect(cardFieldLabel("initial_weight_g", t)).toBe("spool.fields.initial_weight");
    expect(cardFieldLabel("settings_extruder_temp", t)).toBe("filament.fields.settings_extruder_temp");
    // …and those keys really do read like a UI, not a schema.
    expect(lookup(cardFieldLabel("order_number", t))).toBe("Order #");
    expect(lookup(cardFieldLabel("outstanding_units", t))).toBe("Outstanding");
  });

  it("never lets a raw schema key reach the screen, even for an unmapped field", () => {
    expect(cardFieldLabel("some_future_field_g", t)).toBe("Some future field");
    expect(cardFieldLabel("some_future_field_g", t)).not.toContain("_");
  });
});

describe("confirm-card value formatting (#378)", () => {
  afterAll(() => dayjs.locale("en"));

  it("renders an unset value as words, not ∅", () => {
    expect(text("comment", null)).toBe("chat.confirm.not_set");
    expect(text("comment", undefined)).toBe("chat.confirm.not_set");
    expect(text("comment", "")).toBe("chat.confirm.not_set");
  });

  it("renders ordered_at as a date only, dropping a time that decides nothing", () => {
    dayjs.locale("en");
    expect(text("ordered_at", "2026-07-20 09:00")).toBe("July 20, 2026");
    expect(text("ordered_at", "2026-07-20")).toBe("July 20, 2026");
  });

  it("keeps a meaningful time on other datetime fields but drops midnight", () => {
    dayjs.locale("en");
    expect(text("last_used", "2026-07-20 09:30")).toBe("July 20, 2026 09:30");
    expect(text("last_used", "2026-07-20 00:00")).toBe("July 20, 2026");
  });

  it("formats dates in the active locale", () => {
    dayjs.locale("de");
    expect(text("ordered_at", "2026-07-20 09:00")).toBe("20. Juli 2026");
    dayjs.locale("en");
  });

  it("leaves a value that is not really a date alone", () => {
    // Lenient parsing accepts a partial match and silently drops the part it did not
    // understand, so a date field must only be reformatted when the whole value parses.
    expect(text("ordered_at", "2026-07-20 morning")).toBe("2026-07-20 morning");
    expect(text("ordered_at", "sometime in July")).toBe("sometime in July");
    expect(text("lot_nr", "2026-13-99")).toBe("2026-13-99");
  });

  it("renders weights through the client's existing formatWeight", () => {
    expect(text("initial_weight_g", 1000.0)).toBe("1 kg");
    expect(text("remaining_weight_g", 782.5)).toBe("782.5 g");
    expect(text("used_weight_g", 217.6)).toBe("217.6 g");
    expect(text("weight", 1000)).toBe("1 kg");
    expect(text("spool_weight", 190)).toBe("190 g");
    expect(text("low_stock_threshold", 200)).toBe("200 g");
  });

  it("renders temperatures, diameter and density with their units", () => {
    expect(text("settings_extruder_temp", 215)).toBe("215 °C");
    expect(text("settings_bed_temp", 60)).toBe("60 °C");
    expect(text("diameter", 1.75)).toBe("1.75 mm");
    expect(text("density", 1.24)).toBe("1.24 g/cm³");
  });

  it("renders prices through the app's configured currency formatter", () => {
    expect(text("price", 24.99)).toBe("€24.99");
  });

  it("renders booleans as the app's Yes/No, never true/false", () => {
    expect(text("archived", true)).toBe("yes");
    expect(text("archived", false)).toBe("no");
    expect(text("archived", true)).not.toContain("true");
  });

  it("capitalises a status, reusing the order screen's own words", () => {
    expect(text("status", "open")).toBe("chat.confirm.status_open");
    expect(text("status", "arrived")).toBe("orders.state.arrived");
    expect(text("status", "partial")).toBe("Partial");
  });

  it("renders a list of order lines as text, not [object Object]", () => {
    expect(text("lines", ["2 x Acme - PLA", "1 x Acme - PETG"])).toBe("2 x Acme - PLA, 1 x Acme - PETG");
  });

  it("renders a colour as a swatch plus its name", () => {
    const { container } = render(<>{formatCardValue("color_hex", "FF0000", context)}</>);
    expect(container.querySelector("[data-testid='chat-card-swatch']")).not.toBeNull();
    expect(container.textContent).toBe("chat.confirm.color.red");
    expect(text("color_hex", "0066CC")).toBe("chat.confirm.color.blue");
  });

  it("keeps the hex for an 8-digit colour, whose alpha no name can express", () => {
    // "FF0000CC" and "FF0000" would otherwise both read "Red" — dropping the opacity silently.
    expect(text("color_hex", "FF0000CC")).toBe("chat.confirm.color.red (#FF0000CC)");
    expect(text("color_hex", "FF0000")).not.toContain("#");
  });

  it("passes an unparseable colour through rather than inventing a name", () => {
    expect(text("color_hex", "not-a-colour")).toBe("not-a-colour");
  });
});

describe("colour naming (#378)", () => {
  it("names the basic colours", () => {
    const cases: Record<string, string> = {
      "000000": "black",
      FFFFFF: "white",
      "808080": "grey",
      FF0000: "red",
      FF8000: "orange",
      FFFF00: "yellow",
      "00FF00": "green",
      "00FFFF": "cyan",
      "0000FF": "blue",
      "800080": "purple",
      FF80C0: "pink",
      "8B4513": "brown",
      F5F0DC: "beige",
    };
    for (const [hex, name] of Object.entries(cases)) {
      expect(colorNameKey(hex), hex).toBe(`chat.confirm.color.${name}`);
    }
  });

  it("ships a translation for every name it can produce", () => {
    for (const name of COLOR_NAMES) {
      expect(lookup(`chat.confirm.color.${name}`), name).toBeTypeOf("string");
    }
  });

  it("returns null for anything that is not a hex triplet", () => {
    expect(colorNameKey("FF00")).toBeNull();
    expect(colorNameKey("zzzzzz")).toBeNull();
  });
});

describe("which rows a confirm-card shows (#378)", () => {
  it("reads the payload shape to decide between a listing and a diff", () => {
    expect(cardValueMode({}, { location: "Shelf A" })).toBe("create");
    expect(cardValueMode({ id: 1 }, {})).toBe("delete");
    expect(cardValueMode({ location: "A" }, { location: "B" })).toBe("diff");
    expect(cardValueMode({}, {})).toBe("empty");
  });

  it("hides the rows that decide nothing on a create or delete", () => {
    const rows = cardValueRows({
      id: 7,
      filament: "Acme - PLA Meta",
      initial_weight_g: 1000.0,
      location: "Shelf A",
      lot_nr: null,
      archived: false,
    });
    expect(rows.map(([key]) => key)).toEqual(["filament", "initial_weight_g", "location"]);
  });

  it("keeps a non-default archived flag, which does decide something", () => {
    expect(isDecorativeRow("archived", true)).toBe(false);
    expect(isDecorativeRow("archived", false)).toBe(true);
  });

  it("shows one row per changed field and nothing for the unchanged ones", () => {
    const rows = cardDiffRows(
      { color_hex: "FF0000CC", settings_extruder_temp: 210, material: "PLA" },
      { color_hex: "0066CC", settings_extruder_temp: 215, material: "PLA" },
    );
    expect(rows.map((row) => row.key)).toEqual(["color_hex", "settings_extruder_temp"]);
  });

  it("keeps an unset value visible inside a diff — that is the change", () => {
    const rows = cardDiffRows({ comment: null }, { comment: "winter batch" });
    expect(rows).toEqual([{ key: "comment", before: null, after: "winter batch" }]);
    expect(text("comment", rows[0].before)).toBe("chat.confirm.not_set");
  });

  it("treats a key absent from one side as unset, not as unchanged", () => {
    const rows = cardDiffRows({ outstanding_units: 5 }, { spools_created: 5 });
    expect(rows).toEqual([
      { key: "outstanding_units", before: 5, after: null },
      { key: "spools_created", before: null, after: 5 },
    ]);
  });

  it("compares list values by content, not by identity", () => {
    expect(cardDiffRows({ lines: ["2 x PLA"] }, { lines: ["2 x PLA"] })).toEqual([]);
    expect(cardDiffRows({ lines: ["2 x PLA"] }, { lines: ["3 x PLA"] })).toHaveLength(1);
  });
});
