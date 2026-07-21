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
 * The color to display for a spool's swatch: the parent filament's color, formatted into the
 * shape SpoolIcon accepts. Color is a property of the filament, not the spool. Returns undefined
 * when the filament has no color (SpoolIcon then draws its neutral placeholder).
 */
export function getSpoolEffectiveColor(spool: ISpool): SpoolColor | undefined {
  return colorFromParts(
    spool.filament.color_hex,
    spool.filament.multi_color_hexes,
    spool.filament.multi_color_direction,
  );
}
