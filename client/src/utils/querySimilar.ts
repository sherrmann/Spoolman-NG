import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

/** Names shorter than this are still being typed; asking the server wastes a request. */
const MIN_NAME_LENGTH = 2;
const DEBOUNCE_MS = 500;

export interface SimilarVendorMatch {
  id: number;
  name: string;
  probability: number | null;
}

export interface SimilarVendorResult {
  exact: SimilarVendorMatch | null;
  suggestion: SimilarVendorMatch | null;
}

const EMPTY_RESULT: SimilarVendorResult = { exact: null, suggestion: null };

/**
 * Debounced client for POST /vendor/similar: warns before creating a vendor that already
 * exists under another spelling. Debounces 500ms, skips names under two characters, and
 * cancels a request that is superseded by a newer keystroke before it resolves.
 *
 * A response is tagged with the (trimmed) name it was fetched for, and only ever returned while
 * that name is still the current one - so an in-flight or already-resolved answer for "e-sun"
 * never lingers on screen once the field has moved on to "e-sun pro", regardless of the order in
 * which requests happen to resolve.
 *
 * Silent on any failure - a read-only user's 403, a network error, or a non-OK response all
 * just yield nulls rather than surfacing anything, since this is a soft hint alongside the
 * local exact-match warning, never a blocking check.
 */
export function useSimilarVendor(name: string, excludeId?: number): SimilarVendorResult {
  const trimmed = name.trim();
  const [tagged, setTagged] = useState<{ name: string; result: SimilarVendorResult }>({
    name: "",
    result: EMPTY_RESULT,
  });

  useEffect(() => {
    if (trimmed.length < MIN_NAME_LENGTH) {
      setTagged({ name: trimmed, result: EMPTY_RESULT });
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => {
      apiFetch(`${getAPIURL()}/vendor/similar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed, exclude_id: excludeId }),
        signal: controller.signal,
      })
        .then((response) => (response.ok ? response.json() : null))
        .then((data: SimilarVendorResult | null) => {
          setTagged({
            name: trimmed,
            result: data ? { exact: data.exact ?? null, suggestion: data.suggestion ?? null } : EMPTY_RESULT,
          });
        })
        .catch(() => {
          // A superseded request's own tag can never win once a newer name has replaced it (see
          // the render-time check below), so there is nothing to protect here - just stay silent.
          if (!controller.signal.aborted) {
            setTagged({ name: trimmed, result: EMPTY_RESULT });
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, excludeId]);

  // The stored result only counts while it is still tagged with the name currently being asked
  // about. This is what makes a stale answer disappear the instant the name changes, rather than
  // lingering for up to a debounce period - and what makes response order irrelevant: an older
  // request resolving after a newer one can never overwrite what is shown, since by then its tag
  // no longer matches.
  return tagged.name === trimmed ? tagged.result : EMPTY_RESULT;
}

export interface SimilarFilamentMatch {
  id: number;
  name: string;
  probability: number | null;
}

export interface SimilarFilamentResult {
  exact: SimilarFilamentMatch | null;
  suggestion: SimilarFilamentMatch | null;
}

const EMPTY_FILAMENT_RESULT: SimilarFilamentResult = { exact: null, suggestion: null };

/** The draft fields the filament form has filled in so far, as passed to `useSimilarFilament`. */
export interface SimilarFilamentDraft {
  vendor_id?: number;
  vendor_name?: string;
  name?: string;
  material?: string;
  color_hex?: string;
  multi_color_hexes?: string;
  diameter?: number;
}

interface NormalizedFilamentDraft {
  vendor_id?: number;
  vendor_name?: string;
  name?: string;
  material?: string;
  color_hex?: string;
  multi_color_hexes?: string;
  diameter?: number;
}

/** Trims the text fields and turns blanks into `undefined`, so an all-whitespace field and an
 * absent one produce the same (stable) key. */
function normalizeFilamentDraft(draft: SimilarFilamentDraft): NormalizedFilamentDraft {
  return {
    vendor_id: draft.vendor_id ?? undefined,
    vendor_name: draft.vendor_name?.trim() || undefined,
    name: draft.name?.trim() || undefined,
    material: draft.material?.trim() || undefined,
    color_hex: draft.color_hex || undefined,
    multi_color_hexes: draft.multi_color_hexes || undefined,
    diameter: draft.diameter ?? undefined,
  };
}

/**
 * Debounced client for POST /filament/similar: warns before creating a filament that already
 * exists, possibly under another spelling. Modelled exactly on `useSimilarVendor` above - same
 * 500ms debounce, same silent-on-any-failure behaviour, same stale-request handling.
 *
 * The draft is skipped (no request) unless it has a name of at least two characters - a material
 * alone never matches, so there is nothing worth asking the server about without one.
 *
 * A response is tagged with a stable JSON key of the (trimmed) draft it was fetched for, plus
 * `excludeId`, and only ever returned while that key still matches the current draft - so a hint
 * for one combination of fields never lingers once any of them (or `excludeId`) has changed,
 * regardless of the order in which requests happen to resolve.
 */
export function useSimilarFilament(draft: SimilarFilamentDraft, excludeId?: number): SimilarFilamentResult {
  const normalized = useMemo(
    () => normalizeFilamentDraft(draft),
    [
      draft.vendor_id,
      draft.vendor_name,
      draft.name,
      draft.material,
      draft.color_hex,
      draft.multi_color_hexes,
      draft.diameter,
    ],
  );
  // excludeId is folded into the key (not just the request body) so that changing which filament
  // is excluded - e.g. the edit form loading a different record - hides the old result at once,
  // the same as any other field changing.
  const key = useMemo(() => JSON.stringify({ ...normalized, exclude_id: excludeId }), [normalized, excludeId]);
  const skip = (normalized.name?.length ?? 0) < MIN_NAME_LENGTH;

  const [tagged, setTagged] = useState<{ key: string; result: SimilarFilamentResult }>({
    key: "",
    result: EMPTY_FILAMENT_RESULT,
  });

  useEffect(() => {
    if (skip) {
      setTagged({ key, result: EMPTY_FILAMENT_RESULT });
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => {
      apiFetch(`${getAPIURL()}/filament/similar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...normalized, exclude_id: excludeId }),
        signal: controller.signal,
      })
        .then((response) => (response.ok ? response.json() : null))
        .then((data: SimilarFilamentResult | null) => {
          setTagged({
            key,
            result: data ? { exact: data.exact ?? null, suggestion: data.suggestion ?? null } : EMPTY_FILAMENT_RESULT,
          });
        })
        .catch(() => {
          // Mirrors useSimilarVendor: a superseded request's tag can never win once a newer draft
          // has replaced it (see the render-time check below), so there is nothing to protect
          // here - just stay silent.
          if (!controller.signal.aborted) {
            setTagged({ key, result: EMPTY_FILAMENT_RESULT });
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, skip, normalized, excludeId]);

  // Same idea as useSimilarVendor's tag check: only counts while it still matches the draft
  // currently being asked about, so a stale answer disappears the instant any field changes.
  return tagged.key === key ? tagged.result : EMPTY_FILAMENT_RESULT;
}
