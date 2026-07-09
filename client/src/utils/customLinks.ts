// Shared shape + parser for the settings-backed custom-link lists: sidebar links (#92) and per-spool
// action links (#140). Both settings store a JSON array of {name, url}.
export interface CustomLink {
  name: string;
  url: string;
}

/** Parse a setting whose value is a JSON array of {name, url}; tolerant of an unset/blank value. */
export function parseCustomLinks(value: string | undefined): CustomLink[] {
  try {
    const parsed = JSON.parse(value ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((l) => l && typeof l.name === "string" && typeof l.url === "string");
  } catch {
    return [];
  }
}
