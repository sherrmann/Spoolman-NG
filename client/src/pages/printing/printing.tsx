import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { ReactElement, ReactNode } from "react";
import { v4 as uuidv4 } from "uuid";
import { useGetSetting, useSetSetting } from "../../utils/querySettings";

dayjs.extend(utc);

export interface PrintSettings {
  id: string;
  name?: string;
  margin?: { top: number; bottom: number; left: number; right: number };
  printerMargin?: { top: number; bottom: number; left: number; right: number };
  spacing?: { horizontal: number; vertical: number };
  columns?: number;
  rows?: number;
  skipItems?: number;
  itemCopies?: number;
  paperSize?: string;
  customPaperSize?: { width: number; height: number };
  borderShowMode?: "none" | "border" | "grid";
  // #71: "auto" (default) leaves @page size to the printer driver — today's behavior. "label" emits an
  // explicit @page size matching the paper dimensions so roll/label printers (e.g. Brother QL) print
  // at the right geometry/orientation. Old presets lack the key and default to "auto".
  pageSizeMode?: "auto" | "label";
}

export interface QRCodePrintSettings {
  showContent?: boolean;
  showQRCodeMode?: "no" | "simple" | "withIcon";
  textSize?: number;
  // QR image padding in mm (#59). Optional — old presets default to 2 at read time.
  qrPadding?: number;
  // QR error-correction level (#106). Higher = more redundancy but denser modules. Old presets default to "H".
  qrErrorLevel?: "L" | "M" | "Q" | "H";
  // Show a colored swatch of the filament colour next to the label text (#114). Default off.
  showColorSwatch?: boolean;
  // Where the QR sits relative to the text (#79/#107): "left" (side by side, default), "top" or "bottom".
  qrPlacement?: "left" | "top" | "bottom";
  // Lay the label text out in this many CSS columns (#133). Default 1.
  textColumns?: number;
  // Optional custom template for the QR payload (#137). Empty/undefined ⇒ the standard scanner payload.
  customQrPayload?: string;
  // Optional 1D barcode printed alongside the QR (#138). Default "none".
  barcode1d?: "none" | "code128";
  printSettings: PrintSettings;
}

export interface SpoolQRCodePrintSettings {
  template?: string;
  labelSettings: QRCodePrintSettings;
}

export function useGetPrintSettings(settingKey = "print_presets"): SpoolQRCodePrintSettings[] | undefined {
  const { data } = useGetSetting(settingKey);
  if (!data) return;
  const parsed: SpoolQRCodePrintSettings[] =
    data && data.value ? JSON.parse(data.value) : ([] as SpoolQRCodePrintSettings[]);
  // Loop through all parsed and generate a new ID field if it's not set
  return parsed.map((settings) => {
    if (!settings.labelSettings.printSettings.id) {
      settings.labelSettings.printSettings.id = uuidv4();
    }
    return settings;
  });
}

export function useSetPrintSettings(
  settingKey = "print_presets",
): (spoolQRCodePrintSettings: SpoolQRCodePrintSettings[]) => void {
  const mut = useSetSetting(settingKey);

  return (spoolQRCodePrintSettings: SpoolQRCodePrintSettings[]) => {
    mut.mutate(spoolQRCodePrintSettings);
  };
}

interface GenericObject {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
  extra: { [key: string]: string };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getTagValue(tag: string, obj: GenericObject): any {
  // Split tag by .
  const tagParts = tag.split(".");
  if (tagParts[0] === "extra") {
    const extraValue = obj.extra[tagParts[1]];
    if (extraValue === undefined) {
      return "?";
    }
    return JSON.parse(extraValue);
  }

  const value = obj[tagParts[0]] ?? "?";
  // check if value is itself an object. If so, recursively call this and remove the first part of the tag
  if (typeof value === "object") {
    return getTagValue(tagParts.slice(1).join("."), value);
  }
  return value;
}

// Datetime tags render raw (an ISO UTC string) unless a format is given, in which case they are
// converted to local time and formatted with dayjs. Matched on the last path segment so both
// `registered` and `filament.registered` / `vendor.registered` work. Issue #58.
const DATETIME_TAGS = new Set(["registered", "first_used", "last_used"]);

// Private-use sentinel marking a conditional block that resolved to nothing, so a line that becomes
// empty solely because of it can be dropped without a blank line remaining. Issue #64.
const SUPPRESSED = "\uE000";

// A `{tag:fmt}` spec splits on the FIRST colon — a datetime format (e.g. "YYYY-MM-DD HH:mm") itself
// contains colons, which must stay with the format, not the tag.
function splitTagAndFormat(rawTag: string): [string, string | undefined] {
  const colon = rawTag.indexOf(":");
  if (colon === -1) return [rawTag, undefined];
  return [rawTag.slice(0, colon), rawTag.slice(colon + 1)];
}

// Apply an optional `{tag:fmt}` format. No format ⇒ the raw value (byte-identical to before this
// feature). Datetime tags use dayjs in local time; a numeric decimal pattern (e.g. "0.0") rounds a
// number via toFixed. Anything else falls back to the raw value. Issue #58.
function formatTagValue(tagName: string, value: unknown, fmt: string | undefined): string {
  if (fmt === undefined) return `${value}`;

  const lastPart = tagName.split(".").pop() ?? tagName;
  if (DATETIME_TAGS.has(lastPart)) {
    const parsed = dayjs.utc(value as never).local();
    return parsed.isValid() ? parsed.format(fmt) : `${value}`;
  }

  // A decimal pattern like "0", "0.0", "0.00" ⇒ that many decimal places.
  const numeric = fmt.match(/^0*(?:\.(0+))?$/);
  if (numeric && typeof value === "number") {
    return value.toFixed(numeric[1]?.length ?? 0);
  }
  return `${value}`;
}

function applyBold(text: string): ReactNode[] {
  // Even index: outside asterisks, odd index: inside asterisks (to be bolded).
  return text
    .split(/\*\*([\w\W]*?)\*\*/g)
    .map((part, index) => (index % 2 === 0 ? <span key={index}>{part}</span> : <b key={index}>{part}</b>));
}

// Substitute every `{tag}` / `{prefix{tag}suffix}` occurrence in the template against `obj`, returning
// the raw substituted string (SUPPRESSED sentinels for unresolved conditional blocks still present).
// Shared by the label renderer and the QR-payload renderer so both use identical tag semantics.
function substituteTemplateTags(template: string, obj: GenericObject): string {
  // Find all {tags} in the template string and loop over them
  const matches = [...template.matchAll(/{(?:[^}{]|{[^}{]*})*}/gs)];
  let label_text = template;
  matches.forEach((match) => {
    if ((match[0].match(/{/g) || []).length == 1) {
      const [tag, fmt] = splitTagAndFormat(match[0].replace(/[{}]/g, ""));
      // `{size:N}` is a line directive, not a data tag — leave it for the line renderer below.
      if (tag === "size") return;
      const tagValue = getTagValue(tag, obj);
      const rendered = tagValue === "?" ? "?" : formatTagValue(tag, tagValue, fmt);
      label_text = label_text.replace(match[0], rendered);
    } else if ((match[0].match(/{/g) || []).length == 2) {
      const structure = match[0].match(/{(.*?){(.*?)}(.*?)}/);
      if (structure != null) {
        const [tag, fmt] = splitTagAndFormat(structure[2]);
        const tagValue = getTagValue(tag, obj);
        if (tagValue == "?") {
          // #64: mark it so an otherwise-empty line can be removed entirely below.
          label_text = label_text.replace(match[0], SUPPRESSED);
        } else {
          label_text = label_text.replace(match[0], structure[1] + formatTagValue(tag, tagValue, fmt) + structure[3]);
        }
      }
    }
  });
  return label_text;
}

// #137: render a template to a plain single-line-safe string for use as the QR payload. Same tag
// substitution as the label body, but no line/size/bold handling — a scannable payload is one string.
// Unresolved conditional blocks collapse to nothing.
export function renderLabelTemplateString(template: string, obj: GenericObject): string {
  return substituteTemplateTags(template, obj).split(SUPPRESSED).join("");
}

export function renderLabelContents(template: string, obj: GenericObject): ReactElement {
  const label_text = substituteTemplateTags(template, obj);

  // #64: a line that is empty only because a conditional block was suppressed is dropped (its newline
  // consumed) so no blank line prints; lines the user left blank on purpose are untouched. Then strip
  // any leftover sentinels from surviving lines.
  const lines = label_text
    .split("\n")
    .filter((line) => !(line.includes(SUPPRESSED) && line.split(SUPPRESSED).join("").trim() === ""))
    .map((line) => line.split(SUPPRESSED).join(""));

  return (
    <>
      {lines.map((line, idx) => {
        // #58: a leading `{size:N}` scales this whole line to N× the base font size.
        const sizeMatch = line.match(/^{size:([\d.]+)}/);
        const scale = sizeMatch ? parseFloat(sizeMatch[1]) : undefined;
        const content = sizeMatch ? line.slice(sizeMatch[0].length) : line;
        return (
          <span key={idx} style={scale && !Number.isNaN(scale) ? { fontSize: `${scale}em` } : undefined}>
            {applyBold(content)}
            {idx < lines.length - 1 && <br />}
          </span>
        );
      })}
    </>
  );
}
