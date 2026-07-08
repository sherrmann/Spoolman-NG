import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// Client access to a spool's persisted usage/adjustment log (#50).
export interface SpoolUsageEvent {
  id: number;
  spool_id: number;
  time: string;
  event_type: string;
  delta: number;
  measured_weight?: number;
  comment?: string;
}

export function useGetSpoolUsageEvents(spoolId: number | undefined, limit = 50) {
  return useQuery<SpoolUsageEvent[]>({
    queryKey: ["spool", spoolId, "events"],
    enabled: spoolId !== undefined,
    queryFn: async () => {
      const response = await apiFetch(`${getAPIURL()}/spool/${spoolId}/events?limit=${limit}`);
      if (!response.ok) {
        throw new Error("Network response was not ok");
      }
      return response.json();
    },
  });
}
