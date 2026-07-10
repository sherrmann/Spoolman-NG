// Server profile shape and URL handling. baseUrl always includes the scheme
// and any SPOOLMAN_BASE_PATH sub-path, and never ends with a slash — e.g.
// "http://nas:7912" or "https://x.example.com/spoolman".

export interface ServerProfile {
  baseUrl: string;
  name?: string;
}

/**
 * Normalize user input into a usable base URL, or null when it can't be one.
 * A missing scheme defaults to http:// — the common LAN deployment.
 */
export function normalizeBaseUrl(input: string): string | null {
  let value = input.trim();
  if (!value) {
    return null;
  }
  if (!/^https?:\/\//i.test(value)) {
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
      return null; // some other scheme — not a Spoolman server URL
    }
    value = `http://${value}`;
  }
  value = value.replace(/\/+$/, "");
  // scheme://host[:port][/path...] with a non-empty host. The path is one
  // optional group (its class may itself match "/"), not a repeated
  // segment group — repetition would be ambiguous and open to exponential
  // backtracking (CodeQL js/redos).
  if (!/^https?:\/\/[^/\s?#]+(\/[^\s?#]*)?$/i.test(value)) {
    return null;
  }
  return value;
}

/** "http://nas:7912/spoolman" -> "http://nas:7912" (origin only, for link policy). */
export function originOf(baseUrl: string): string {
  const match = baseUrl.match(/^(https?:\/\/[^/]+)/i);
  return match ? match[1] : baseUrl;
}

export function apiUrl(baseUrl: string, path: string): string {
  return `${baseUrl}/api/v1${path}`;
}

export function appUrl(baseUrl: string, path: string): string {
  return `${baseUrl}${path}`;
}
