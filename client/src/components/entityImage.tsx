import { useEffect, useState } from "react";
import { apiFetch } from "../utils/authReloadHandler";
import { getAPIURL } from "../utils/url";

// Authenticated loading of entity reference photos (#88). A plain <img src> cannot carry the
// Authorization header (the API token lives in localStorage, not a cookie), so images are fetched
// with apiFetch and rendered from object URLs. Fetched images are kept in a module-level cache and
// revalidated with If-None-Match on the next mount: gallery scrolling re-renders from the cache
// immediately (a 304 costs no bytes), while a photo replaced elsewhere still shows up without a
// page reload. Object URLs are only revoked on explicit invalidation, never on unmount, so a
// cached entry stays usable across mounts.

const cache = new Map<string, { etag: string | null; objectUrl: string }>();

/** The image endpoint of a filament; also the cache key for the hooks below. */
export function filamentImageUrl(filamentId: number): string {
  return `${getAPIURL()}/filament/${filamentId}/image`;
}

/** Drop the cached copy (after an upload or delete) so the next fetch revalidates from scratch. */
export function invalidateEntityImage(url: string): void {
  const entry = cache.get(url);
  if (entry) {
    URL.revokeObjectURL(entry.objectUrl);
    cache.delete(url);
  }
}

/**
 * Object URL for an authenticated image GET, or null while loading / when url is null / on error.
 * Bump `version` to force a revalidation within a mounted view (after an upload in the same page).
 */
export function useEntityImage(url: string | null, version = 0): string | null {
  const [src, setSrc] = useState<string | null>(() => (url ? (cache.get(url)?.objectUrl ?? null) : null));

  useEffect(() => {
    if (!url) {
      setSrc(null);
      return;
    }
    let cancelled = false;
    const cached = cache.get(url) ?? null;
    setSrc(cached?.objectUrl ?? null);
    (async () => {
      const headers: Record<string, string> = {};
      if (cached?.etag) {
        headers["If-None-Match"] = cached.etag;
      }
      const response = await apiFetch(url, { headers });
      if (response.status === 304) {
        return; // The cached copy is current.
      }
      if (!response.ok) {
        // Deleted on the server (or never existed): drop the stale copy and fall back.
        invalidateEntityImage(url);
        if (!cancelled) setSrc(null);
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      cache.set(url, { etag: response.headers.get("etag"), objectUrl });
      if (!cancelled) setSrc(objectUrl);
    })().catch(() => {
      // Network error: keep whatever is shown (the cached copy or the caller's fallback).
    });
    return () => {
      cancelled = true;
    };
  }, [url, version]);

  return src;
}
