import { render } from "@testing-library/react";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { describe, expect, it } from "vitest";
import { parseScanResult } from "../../utils/scan";
import { renderLabelContents, renderLabelTemplateString } from "./printing";

dayjs.extend(utc);

// The label template engine (TESTING_CANDIDATES row 77), generalised from ISpool to
// any object in PR #4. Oracle: the rendered text/markup for hand-written templates —
// asserted through the DOM output, not the implementation. Covers tag substitution,
// nested lookups, extra-field JSON, conditional blocks, bold and newlines.
function textOf(template: string, obj: Record<string, unknown>): string {
  const { container } = render(renderLabelContents(template, obj as never));
  return container.textContent ?? "";
}

describe("renderLabelContents", () => {
  it("substitutes a simple {tag}", () => {
    expect(textOf("Name: {name}", { name: "PLA", extra: {} })).toBe("Name: PLA");
  });

  it("renders a missing tag as '?'", () => {
    expect(textOf("{material}", { extra: {} })).toBe("?");
  });

  it("resolves a nested {vendor.name}", () => {
    expect(textOf("{vendor.name}", { vendor: { name: "Acme" }, extra: {} })).toBe("Acme");
  });

  it("renders '?' for a missing nested field", () => {
    expect(textOf("{vendor.name}", { vendor: {}, extra: {} })).toBe("?");
  });

  it("JSON-decodes an {extra.*} value", () => {
    expect(textOf("{extra.color}", { extra: { color: '"Red"' } })).toBe("Red");
    // A numeric extra decodes to its number.
    expect(textOf("{extra.diameter}", { extra: { diameter: "1.75" } })).toBe("1.75");
  });

  it("keeps a conditional block when the inner tag resolves", () => {
    expect(textOf("{Diameter: {diameter} mm}", { diameter: 1.75, extra: {} })).toBe("Diameter: 1.75 mm");
  });

  it("drops a conditional block entirely when the inner tag is missing", () => {
    expect(textOf("{Diameter: {diameter} mm}", { extra: {} })).toBe("");
  });

  it("bolds **text** into a <b> element", () => {
    const { container } = render(renderLabelContents("**Bold** rest", { extra: {} } as never));
    const bold = container.querySelector("b");
    expect(bold?.textContent).toBe("Bold");
    expect(container.textContent).toBe("Bold rest");
  });

  it("turns a newline into a <br>", () => {
    const { container } = render(renderLabelContents("a\nb", { extra: {} } as never));
    expect(container.querySelector("br")).not.toBeNull();
    expect(container.textContent).toBe("ab");
  });

  // --- #58: value formatting -------------------------------------------------

  it("leaves a bare numeric {tag} untouched (backward compatible)", () => {
    expect(textOf("{remaining_weight}", { remaining_weight: 843.2589999999999, extra: {} })).toBe("843.2589999999999");
  });

  it("rounds a number with a {tag:0.0} decimal pattern", () => {
    expect(textOf("{remaining_weight:0.0}", { remaining_weight: 843.2589999999999, extra: {} })).toBe("843.3");
    expect(textOf("{remaining_weight:0}", { remaining_weight: 843.9, extra: {} })).toBe("844");
    expect(textOf("{remaining_weight:0.00}", { remaining_weight: 5, extra: {} })).toBe("5.00");
  });

  it("applies the number format inside a conditional block too", () => {
    expect(textOf("{Weight: {remaining_weight:0.0} g}", { remaining_weight: 843.25, extra: {} })).toBe(
      "Weight: 843.3 g",
    );
  });

  it("leaves a bare datetime {tag} as the raw value (backward compatible)", () => {
    const iso = "2026-07-08T13:30:00Z";
    expect(textOf("{registered}", { registered: iso, extra: {} })).toBe(iso);
  });

  it("formats a datetime {tag:fmt} in local time with dayjs", () => {
    const iso = "2026-07-08T13:30:00Z";
    const expected = dayjs.utc(iso).local().format("YYYY-MM-DD HH:mm");
    expect(textOf("{registered:YYYY-MM-DD HH:mm}", { registered: iso, extra: {} })).toBe(expected);
  });

  it("formats a nested datetime tag (filament.registered) in local time", () => {
    const iso = "2026-07-08T13:30:00Z";
    const expected = dayjs.utc(iso).local().format("YYYY-MM-DD");
    expect(textOf("{filament.registered:YYYY-MM-DD}", { filament: { registered: iso }, extra: {} })).toBe(expected);
  });

  // --- #58: per-line font size ----------------------------------------------

  it("scales a line prefixed with {size:N}", () => {
    const { container } = render(renderLabelContents("{size:2}Big\nsmall", { extra: {} } as never));
    expect(container.textContent).toBe("Bigsmall");
    const scaled = Array.from(container.querySelectorAll("span")).find(
      (s) => (s as HTMLElement).style.fontSize === "2em",
    );
    expect(scaled?.textContent).toBe("Big");
  });

  // --- #64: suppressed conditional block drops its blank line ----------------

  it("removes a line that is empty only because its conditional block was suppressed", () => {
    const { container } = render(
      renderLabelContents("ET: 210\n{BT: {settings_bed_temp} °C}\nLot", { extra: {} } as never),
    );
    expect(container.textContent).toBe("ET: 210Lot");
    // Two lines survive -> exactly one <br>; the suppressed middle line took its newline with it.
    expect(container.querySelectorAll("br")).toHaveLength(1);
  });

  it("keeps a conditional block's line when its tag resolves", () => {
    const { container } = render(
      renderLabelContents("ET: 210\n{BT: {settings_bed_temp} °C}\nLot", { settings_bed_temp: 60, extra: {} } as never),
    );
    expect(container.textContent).toBe("ET: 210BT: 60 °CLot");
    expect(container.querySelectorAll("br")).toHaveLength(2);
  });

  it("does not drop a blank line the template author wrote on purpose", () => {
    const { container } = render(renderLabelContents("A\n\nB", { extra: {} } as never));
    expect(container.querySelectorAll("br")).toHaveLength(2);
  });
});

// --- #137: custom QR payload template rendered to a plain string ------------
describe("renderLabelTemplateString", () => {
  it("substitutes tags into a plain string (no markup)", () => {
    expect(renderLabelTemplateString("WEB+SPOOLMAN:S-{id}", { id: 42, extra: {} } as never)).toBe("WEB+SPOOLMAN:S-42");
  });

  it("resolves nested tags", () => {
    expect(
      renderLabelTemplateString("{filament.vendor.name}/{id}", {
        id: 7,
        filament: { vendor: { name: "Acme" } },
        extra: {},
      } as never),
    ).toBe("Acme/7");
  });

  it("collapses a suppressed conditional block to nothing rather than leaving a sentinel", () => {
    expect(renderLabelTemplateString("A{-{missing}-}B", { extra: {} } as never)).toBe("AB");
  });

  it("keeps a resolved conditional block", () => {
    expect(renderLabelTemplateString("id{-{id}-}", { id: 5, extra: {} } as never)).toBe("id-5-");
  });

  it("produces a payload that still parses as a Spoolman scan target", () => {
    const payload = renderLabelTemplateString("WEB+SPOOLMAN:S-{id}", { id: 99, extra: {} } as never);
    expect(parseScanResult(payload)).toEqual({ resource: "spool", id: "99", path: "/spool/show/99" });
  });
});
