import { IFilament } from "../filaments/model";

// A shop where filament is (re)ordered (#298). Distinct from IVendor (the manufacturer).
export interface IShop {
  id: number;
  registered: string;
  name: string;
  homepage?: string;
  // Free-form region codes this shop ships to, e.g. ["CH", "EU"]. Absent means unspecified.
  ships_to?: string[];
  comment?: string;
}

// One filament line within an order (#298). arrived_at absent/null means still outstanding.
export interface IOrderLine {
  id: number;
  filament_id: number;
  quantity: number;
  price_per_unit?: number;
  arrived_at?: string;
  // Optionally hydrated client-side for display; not part of the API line payload.
  filament?: IFilament;
}

// A grouped (bulk) reorder (#298). state is derived server-side from the lines.
export interface IOrder {
  id: number;
  registered: string;
  shop?: IShop;
  ordered_at: string;
  order_number?: string;
  url?: string;
  comment?: string;
  lines: IOrderLine[];
  state: "open" | "arrived";
}
