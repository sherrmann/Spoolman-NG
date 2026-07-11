// Pure logic for the in-app updater: version comparison and parsing the
// GitHub "latest release" payload. All I/O (network, download, install intent)
// lives in src/update/updater.ts so this stays unit-testable.

/** owner/repo whose releases carry the companion APK. */
export const UPDATE_REPO = "sherrmann/Spoolman-NG";

/** The APK asset is named after the git ref, e.g. spoolman-companion-v2026.7.8.apk. */
const APK_ASSET = /^spoolman-companion.*\.apk$/i;

export interface LatestRelease {
  /** Release tag, e.g. "v2026.7.8". */
  tag: string;
  /** Tag without a leading "v", e.g. "2026.7.8" — comparable to the app version. */
  version: string;
  /** Direct download URL for the companion APK, or null when none is attached. */
  apkUrl: string | null;
  /** The release page, for a "view release" fallback. */
  htmlUrl: string;
  /** Release notes (markdown), if present. */
  notes: string;
}

/** Strip a leading "v"/"V" so "v2026.7.8" and "2026.7.8" compare equal. */
export function normalizeVersion(value: string): string {
  return value.trim().replace(/^v/i, "");
}

/**
 * Split a dotted version into numeric components, ignoring any pre-release
 * suffix. "2026.7.8" -> [2026, 7, 8]; non-numeric parts become 0.
 */
function parseVersion(value: string): number[] {
  return normalizeVersion(value)
    .split(/[.+-]/)
    .map((part) => {
      const n = Number.parseInt(part, 10);
      return Number.isNaN(n) ? 0 : n;
    });
}

/** -1 if a < b, 0 if equal, 1 if a > b — component-wise, shorter side zero-padded. */
export function compareVersions(a: string, b: string): -1 | 0 | 1 {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x < y) {
      return -1;
    }
    if (x > y) {
      return 1;
    }
  }
  return 0;
}

/** True when latestTag is a strictly newer version than the installed one. */
export function isUpdateAvailable(currentVersion: string, latestTag: string): boolean {
  return compareVersions(latestTag, currentVersion) > 0;
}

/**
 * Parse the GitHub /releases/latest payload into a LatestRelease, or null when
 * it is malformed. Picks the first asset whose name looks like the companion
 * APK; apkUrl is null when no such asset is attached (e.g. a build that failed).
 */
export function parseLatestRelease(payload: unknown): LatestRelease | null {
  if (typeof payload !== "object" || payload === null) {
    return null;
  }
  const obj = payload as Record<string, unknown>;
  const tag = typeof obj.tag_name === "string" ? obj.tag_name : null;
  if (!tag) {
    return null;
  }
  const htmlUrl = typeof obj.html_url === "string" ? obj.html_url : "";
  const notes = typeof obj.body === "string" ? obj.body : "";
  let apkUrl: string | null = null;
  if (Array.isArray(obj.assets)) {
    for (const asset of obj.assets) {
      if (
        typeof asset === "object" &&
        asset !== null &&
        typeof (asset as { name?: unknown }).name === "string" &&
        APK_ASSET.test((asset as { name: string }).name) &&
        typeof (asset as { browser_download_url?: unknown }).browser_download_url === "string"
      ) {
        apkUrl = (asset as { browser_download_url: string }).browser_download_url;
        break;
      }
    }
  }
  return { tag, version: normalizeVersion(tag), apkUrl, htmlUrl, notes };
}
