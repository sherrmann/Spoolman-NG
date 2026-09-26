import { useEffect, useState } from "react";
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
