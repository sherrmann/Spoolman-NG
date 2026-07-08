export interface IVendor {
  id: number;
  registered: string;
  name: string;
  comment?: string;
  empty_spool_weight?: number;
  external_id?: string;
  // Server-computed aggregates, only present on the vendor list/detail endpoints (#49).
  filament_count?: number;
  spool_count?: number;
  extra: { [key: string]: string };
}

// IVendorParsedExtras is the same as IVendor, but with the extra field parsed into its real types
export type IVendorParsedExtras = Omit<IVendor, "extra"> & { extra?: { [key: string]: unknown } };
