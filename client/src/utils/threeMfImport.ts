import { strFromU8, unzipSync } from "fflate";
import { ISpool } from "../pages/spools/model";

// Client-side reader for a *sliced* .3mf project (#105). Bambu Studio / OrcaSlicer write a
// `Metadata/slice_info.config` into the 3mf (a zip) that lists, per plate, each filament's type,
// colour and the grams it consumed. This parses that so the matching spools can be selected and
// their usage adjusted in bulk. Pure and network-free so it can be unit-tested; the apply step lives
// in importExport.ts.

export interface ThreeMfFilament {
  /** The filament id within the 3mf (an AMS slot), used as a stable react key. */
  key: string;
  /** Material type, e.g. "PLA". */
  type?: string;
  /** Colour as #RRGGBB (upper-case, alpha dropped), or undefined if unknown. */
  colorHex?: string;
  /** Grams consumed, summed across every plate in the project. */
  usedWeight: number;
}

const SLICE_INFO_PATH = "Metadata/slice_info.config";

/** Normalise a 3mf colour (#RGB.. / RRGGBB / RRGGBBAA, with or without a leading #) to #RRGGBB. */
export function normalizeHex(color: string | null | undefined): string | undefined {
  if (!color) {
    return undefined;
  }
  const hex = color.replace(/^#/, "");
  if (hex.length < 6) {
    return undefined;
  }
  return `#${hex.slice(0, 6).toUpperCase()}`;
}

/** Parse a Bambu/Orca slice_info.config XML into per-filament usage, summed across all plates. */
export function parseSliceInfo(xml: string): ThreeMfFilament[] {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.querySelector("parsererror")) {
    throw new Error("Invalid 3MF slice-info XML");
  }
  const byId = new Map<string, ThreeMfFilament>();
  for (const el of Array.from(doc.querySelectorAll("filament"))) {
    const id = el.getAttribute("id") ?? String(byId.size + 1);
    const usedWeight = Number.parseFloat(el.getAttribute("used_g") ?? "0") || 0;
    const existing = byId.get(id);
    if (existing) {
      existing.usedWeight += usedWeight;
    } else {
      byId.set(id, {
        key: id,
        type: el.getAttribute("type") ?? undefined,
        colorHex: normalizeHex(el.getAttribute("color")),
        usedWeight,
      });
    }
  }
  return Array.from(byId.values()).filter((f) => f.usedWeight > 0);
}

/** Unzip a .3mf and extract per-filament usage from its slice_info.config. */
export function parseThreeMf(bytes: Uint8Array): ThreeMfFilament[] {
  let files: Record<string, Uint8Array>;
  try {
    files = unzipSync(bytes);
  } catch {
    throw new Error("Not a valid 3MF (zip) file");
  }
  const entry = files[SLICE_INFO_PATH];
  if (!entry) {
    throw new Error("This 3MF has no slice info — export a sliced project from Bambu Studio or OrcaSlicer");
  }
  return parseSliceInfo(strFromU8(entry));
}

/** A spool's primary colour hex for matching: its filament's colour. */
export function spoolPrimaryHex(spool: ISpool): string | undefined {
  const raw = spool.filament.color_hex ?? spool.filament.multi_color_hexes?.split(",")[0];
  return normalizeHex(raw);
}

/**
 * Best spool match for a 3mf filament: an exact colour match, preferring one whose material also
 * matches. Returns the spool id, or undefined when no colour matches (the user then picks manually,
 * since a sliced project's colours won't always line up with an in-stock spool).
 */
export function autoMatchSpoolId(tmf: ThreeMfFilament, spools: ISpool[]): number | undefined {
  if (!tmf.colorHex) {
    return undefined;
  }
  const colorMatches = spools.filter((s) => spoolPrimaryHex(s) === tmf.colorHex);
  if (colorMatches.length === 0) {
    return undefined;
  }
  const withMaterial = tmf.type
    ? colorMatches.find((s) => (s.filament.material ?? "").toLowerCase() === tmf.type?.toLowerCase())
    : undefined;
  return (withMaterial ?? colorMatches[0]).id;
}
