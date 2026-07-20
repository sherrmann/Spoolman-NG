declare global {
  interface Window {
    SPOOLMAN_BASE_PATH: string;
  }
}

/**
 * Returns the base path of the application.
 *
 * If a base path is set, this returns e.g. "/spoolman". If none is set, it returns "".
 *
 * @return {string} The base path of the application. If the `SPOOLMAN_BASE_PATH`
 * window variable is set and not empty, it is returned. Otherwise, the
 * default base path "" is returned.
 */
export function getBasePath(): string {
  if (window.SPOOLMAN_BASE_PATH && window.SPOOLMAN_BASE_PATH.length > 0) {
    return window.SPOOLMAN_BASE_PATH;
  } else {
    return "";
  }
}

/**
 * A function that returns the Spoolman API URL
 * This returns e.g. "/spoolman/api/v1" if the base path is "/spoolman"
 *
 * @return {string} The API URL
 */
export function getAPIURL(): string {
  if (!import.meta.env.VITE_APIURL) {
    throw new Error("VITE_APIURL is not set");
  }
  return getBasePath() + import.meta.env.VITE_APIURL;
}

/**
 * Guards against rendering a user-supplied URL (e.g. an order or shop URL) as a clickable
 * `<a href>`. React does not sanitize hrefs, so passing an unvalidated string through lets a
 * `javascript:` (or other non-http(s)) scheme execute when clicked — a stored-XSS vector.
 *
 * @param url The candidate URL, or undefined.
 * @return {string | undefined} `url` unchanged if it parses as an absolute `http:` or `https:`
 * URL; otherwise `undefined` (including when `url` itself is undefined or unparseable).
 */
export function safeHttpUrl(url: string | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? url : undefined;
  } catch {
    return undefined;
  }
}
