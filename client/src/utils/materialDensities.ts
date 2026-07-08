// Common 3D-printing filament material densities in g/cm³, used to suggest a default
// density when a known material is entered and the density field is still blank. Values
// are typical manufacturer figures; the user can always override. Issue #54.
export const MATERIAL_DENSITIES: Record<string, number> = {
  PLA: 1.24,
  "PLA+": 1.24,
  PETG: 1.27,
  PET: 1.38,
  ABS: 1.04,
  ASA: 1.07,
  TPU: 1.21,
  TPE: 1.2,
  PA: 1.14,
  NYLON: 1.14,
  PC: 1.2,
  POLYCARBONATE: 1.2,
  HIPS: 1.04,
  PVA: 1.23,
  PP: 0.9,
  PEEK: 1.3,
  PVB: 1.09,
};

/**
 * Suggest a density (g/cm³) for a material name, matching case-insensitively against the
 * known-materials table. Returns undefined for unknown or empty input.
 */
export function suggestDensityForMaterial(material: string | undefined | null): number | undefined {
  if (!material) return undefined;
  return MATERIAL_DENSITIES[material.trim().toUpperCase()];
}
