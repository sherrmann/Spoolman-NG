import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

/** Shape of `GET /api/v1/info`. Update-check fields (#293) are optional so an older
 *  server that predates them still type-checks. */
export interface IInfo {
  version: string;
  debug_mode: boolean;
  automatic_backups: boolean;
  data_dir: string;
  backups_dir: string;
  db_type: string;
  git_commit?: string;
  build_date?: string;
  update_check_enabled?: boolean;
  latest_version?: string | null;
  update_available?: boolean;
  release_url?: string | null;
}

/** Shared query for server info. The `["info"]` key dedupes across every consumer
 *  (version display, update notification, ...) so it's fetched once and cached. */
export const useInfo = () =>
  useQuery<IInfo>({
    queryKey: ["info"],
    queryFn: async () => {
      const response = await apiFetch(getAPIURL() + "/info");
      if (!response.ok) {
        throw new Error("Network response was not ok");
      }
      return response.json();
    },
  });
