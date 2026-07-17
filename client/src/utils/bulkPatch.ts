import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// Apply a partial change to one resource row via the existing single-resource PATCH endpoint. Bulk
// edit (#73) loops this over each selected id rather than adding a bulk backend endpoint, so the
// /api/v1 surface that integrations (Moonraker, OctoPrint, Home Assistant) depend on is unchanged.
async function patchOne(resource: string, id: number, body: Record<string, unknown>): Promise<void> {
  const res = await apiFetch(`${getAPIURL()}/${resource}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`${resource} ${id}: HTTP ${res.status}`);
  }
}

/**
 * PATCH `body` onto every id of `resource`, tolerating partial failure so one bad row doesn't abort
 * the batch. Returns the count that failed.
 */
export async function bulkPatch(resource: string, ids: number[], body: Record<string, unknown>): Promise<number> {
  const results = await Promise.allSettled(ids.map((id) => patchOne(resource, id, body)));
  return results.filter((r) => r.status === "rejected").length;
}
