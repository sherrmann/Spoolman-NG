import { IFilament } from "../filaments/model";

export enum WeightToEnter {
  used_weight = 1,
  remaining_weight = 2,
  measured_weight = 3,
}

export interface ISpool {
  id: number;
  registered: string;
  first_used?: string;
  last_used?: string;
  filament: IFilament;
  price?: number;
  initial_weight?: number;
  spool_weight?: number;
  remaining_weight?: number;
  used_weight: number;
  remaining_length?: number;
  used_length: number;
  // Per-spool measured diameter override (#101). Undefined ⇒ the filament's diameter is used.
  diameter?: number;
  // Per-spool color override (#74). Undefined ⇒ the filament's color is used.
  color_hex?: string;
  multi_color_hexes?: string;
  multi_color_direction?: string;
  location?: string;
  lot_nr?: string;
  comment?: string;
  archived: boolean;
  label_printed_at?: string;
  extra: { [key: string]: string };
}

// ISpoolParsedExtras is the same as ISpool, but with the extra field parsed into its real types
export type ISpoolParsedExtras = Omit<ISpool, "extra"> & { extra?: { [key: string]: unknown } };
