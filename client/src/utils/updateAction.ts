import { create } from "zustand";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// Client wiring for the per-install-type update action (#294). The real self-update button
// (native installs) posts to /update; other install types get tailored instructions in the
// modal. A tiny zustand store lets any surface (the version hint, the update toast) open the
// single modal instance mounted in the header — mirroring the apiToken modal store.

export interface UpdateResult {
  status: string;
  target: string | null;
  restart_managed: boolean;
}

/**
 * Trigger the native self-update. Resolves with the server's response (which reports whether
 * the service will restart itself), or rejects with the server's error message. Admin-gated and
 * only valid on native installs — the caller should only reach here when `update_action_available`.
 */
export async function triggerUpdate(tag?: string): Promise<UpdateResult> {
  const response = await apiFetch(`${getAPIURL()}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(tag ? { tag } : {}),
  });
  if (!response.ok) {
    let detail = "Update failed";
    try {
      const body = await response.json();
      detail = body.detail ?? body.message ?? detail;
    } catch {
      /* non-JSON body — keep the fallback */
    }
    throw new Error(detail);
  }
  return response.json();
}

interface UpdateModalState {
  open: boolean;
  show: () => void;
  close: () => void;
}

/** Shared open/close state for the single UpdateModal mounted in the header. */
export const useUpdateModal = create<UpdateModalState>((set) => ({
  open: false,
  show: () => set({ open: true }),
  close: () => set({ open: false }),
}));
