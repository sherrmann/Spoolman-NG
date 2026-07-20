import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../utils/authReloadHandler";
import { getAPIURL } from "../../utils/url";
import { IShop } from "./model";

export const SHOP_QUERY_KEY = ["shop"];

async function fetchShops(): Promise<IShop[]> {
  const response = await apiFetch(`${getAPIURL()}/shop`);
  if (!response.ok) throw new Error("Failed to load shops");
  return response.json();
}

function findByName(shops: IShop[], name: string): IShop | undefined {
  const target = name.trim().toLowerCase();
  return shops.find((s) => s.name.trim().toLowerCase() === target);
}

/**
 * List + inline-create shops (#298) for the shop `AutoComplete` in the mark-ordered dialog and
 * the bulk create-order modal. Kept on plain `apiFetch`/`getAPIURL` (like querySettings.ts)
 * rather than refine's data hooks, since `ensureShop` needs to read-then-maybe-write in one
 * call and refine's `useCreate` doesn't expose that shape cleanly.
 */
export function useShops() {
  const queryClient = useQueryClient();
  const query = useQuery<IShop[]>({ queryKey: SHOP_QUERY_KEY, queryFn: fetchShops });

  /**
   * Resolve a shop name typed into the AutoComplete to an id: an existing shop (case-insensitive
   * match) is reused, otherwise a new one is created. A 409 from a create race (two tabs creating
   * the same shop at once) is tolerated by refetching and matching by name rather than failing.
   */
  const ensureShop = async (name: string): Promise<number> => {
    const trimmed = name.trim();
    const cached = queryClient.getQueryData<IShop[]>(SHOP_QUERY_KEY) ?? query.data ?? (await fetchShops());
    const existing = findByName(cached, trimmed);
    if (existing) return existing.id;

    const response = await apiFetch(`${getAPIURL()}/shop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: trimmed }),
    });

    if (response.status === 409) {
      const refetched = await fetchShops();
      queryClient.setQueryData(SHOP_QUERY_KEY, refetched);
      const match = findByName(refetched, trimmed);
      if (match) return match.id;
      throw new Error(`Shop "${trimmed}" could not be created or found.`);
    }

    if (!response.ok) throw new Error("Failed to create shop");

    const created: IShop = await response.json();
    await queryClient.invalidateQueries({ queryKey: SHOP_QUERY_KEY });
    return created.id;
  };

  return { shops: query.data ?? [], isLoading: query.isLoading, ensureShop };
}
