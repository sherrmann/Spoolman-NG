import { IVendor } from "../vendors/model";

export interface IFilament {
  id: number;
  registered: string;
  name?: string;
  vendor?: IVendor;
  material?: string;
  price?: number;
  density: number;
  diameter: number;
  weight?: number;
  spool_weight?: number;
  article_number?: string;
  comment?: string;
  settings_extruder_temp?: number;
  settings_bed_temp?: number;
  // Manufacturer recommended temperature ranges (#112). Absent means no range recorded.
  settings_extruder_temp_min?: number;
  settings_extruder_temp_max?: number;
  settings_bed_temp_min?: number;
  settings_bed_temp_max?: number;
  // SpoolmanDB catalog descriptors preserved on local import (#91 / #567). Absent means unknown.
  spool_type?: "plastic" | "cardboard" | "metal";
  finish?: "matte" | "glossy";
  pattern?: "marble" | "sparkle";
  translucent?: boolean;
  glow?: boolean;
  color_hex?: string;
  multi_color_hexes?: string;
  multi_color_direction?: string;
  external_id?: string;
  // Per-filament reorder settings (#109 / #116).
  low_stock_threshold?: number;
  reserve_count?: number;
  // When a label was last printed for this filament (#93). Absent means never printed.
  label_printed_at?: string;
  // True when a reference photo is attached (#88); the bytes come from GET /filament/{id}/image.
  // Absent means no photo.
  has_image?: boolean;
  // Server-computed aggregates, only present on the filament list/detail endpoints (#49 / #53).
  spool_count?: number;
  remaining_weight?: number;
  // The oldest open order containing this filament (#298). Present only on list/detail; absent when
  // nothing is outstanding. The client's on-order pill / shopping-list state reads this.
  on_order?: { order_id: number; ordered_at: string };
  extra: { [key: string]: string };
}

// IFilamentParsedExtras is the same as IFilament, but with the extra field parsed into its real types
export type IFilamentParsedExtras = Omit<IFilament, "extra"> & { extra?: { [key: string]: unknown } };
