// The Location entity (#103). Distinct from the string-based board plumbing: this is the
// name-registry row that carries custom fields. `Spool.location` remains a plain string.
export interface ILocation {
  id: number;
  registered: string;
  name: string;
  comment?: string;
  // Server-computed aggregate, only present on the location list/detail endpoints.
  spool_count?: number;
  extra: { [key: string]: string };
}

// Same as ILocation but with the extra field parsed into its real types (for form editing).
export type ILocationParsedExtras = Omit<ILocation, "extra"> & { extra?: { [key: string]: unknown } };
