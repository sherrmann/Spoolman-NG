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
 * Silent on any failure - a read-only user's 403, a network error, or a non-OK response all
 * just yield nulls rather than surfacing anything, since this is a soft hint alongside the
 * local exact-match warning, never a blocking check.
 */
export function useSimilarVendor(name: string, excludeId?: number): SimilarVendorResult {
  const [result, setResult] = useState<SimilarVendorResult>(EMPTY_RESULT);

  useEffect(() => {
    const trimmed = name.trim();
    if (trimmed.length < MIN_NAME_LENGTH) {
      setResult(EMPTY_RESULT);
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
          setResult(data ? { exact: data.exact ?? null, suggestion: data.suggestion ?? null } : EMPTY_RESULT);
        })
        .catch(() => {
          // A superseded request is aborted deliberately - let the request that replaced it
          // stand rather than clobbering it back to empty. Any other failure (network error,
          // malformed response) stays silent too, per the module's contract.
          if (!controller.signal.aborted) {
            setResult(EMPTY_RESULT);
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [name, excludeId]);

  return result;
}
