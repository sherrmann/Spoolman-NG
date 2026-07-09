import { ISpool } from "../pages/spools/model";

/** The color shape SpoolIcon / the label swatch accept: a single hex, or a multi-color spec. */
export type SpoolColor = string | { colors: string[]; vertical: boolean };

/** Build a color object from raw color parts (a single hex or a multi-color list), or undefined. */
function colorFromParts(
  colorHex: string | undefined,
  multiColorHexes: string | undefined,
  direction: string | undefined,
): SpoolColor | undefined {
  if (multiColorHexes) {
    return { colors: multiColorHexes.split(","), vertical: direction === "longitudinal" };
  }
  return colorHex || undefined;
}

/**
 * The effective color to display for a spool (#74): the spool's own color override when set,
 * otherwise the parent filament's color. A single-color override replaces a multi-color filament
 * (and vice versa) — the override, when present, wins wholesale; there is no per-channel merge.
 * Returns undefined when neither the spool nor the filament has a color (SpoolIcon then draws its
 * neutral placeholder).
 */
export function getSpoolEffectiveColor(spool: ISpool): SpoolColor | undefined {
  const own = colorFromParts(spool.color_hex, spool.multi_color_hexes, spool.multi_color_direction);
  if (own !== undefined) {
    return own;
  }
  return colorFromParts(
    spool.filament.color_hex,
    spool.filament.multi_color_hexes,
    spool.filament.multi_color_direction,
  );
}
