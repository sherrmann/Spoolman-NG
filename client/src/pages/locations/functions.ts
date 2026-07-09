import { GetListResponse } from "@refinedev/core";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useGetSetting } from "../../utils/querySettings";
import { getAPIURL } from "../../utils/url";
import { ISpool } from "../spools/model";
import { ILocation } from "./model";

export const EMPTYLOC = "";

/** Fetch a set of locations by id (for the label print flow), mirroring useGetSpoolsByIds. */
export function useGetLocationsByIds(ids: number[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: ["location", id],
      queryFn: async () => {
        const res = await fetch(`${getAPIURL()}/locations/${id}`);
        return (await res.json()) as ILocation;
      },
    })),
  });
}

/**
 * Look up a Location entity (#103) by its exact name. The registry is keyed by name (the board deals
 * in location strings), so this bridges a board column to its entity row. The backend name filter is
 * a partial case-insensitive match, so we pick the exact-name row from the results.
 */
export async function getLocationByName(name: string): Promise<ILocation | null> {
  const response = await fetch(`${getAPIURL()}/locations?${new URLSearchParams({ name })}`);
  if (!response.ok) {
    return null;
  }
  const data: ILocation[] = await response.json();
  return data.find((loc) => loc.name === name) ?? null;
}

/**
 * Get the Location entity for a board column's name, creating an empty registry row on first use so
 * custom-field values have somewhere to live. Board columns are strings; their entity row is created
 * lazily the first time someone edits its custom fields.
 */
export async function getOrCreateLocationByName(name: string): Promise<ILocation> {
  const existing = await getLocationByName(name);
  if (existing) {
    return existing;
  }
  const response = await fetch(`${getAPIURL()}/locations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    throw new Error("Failed to create location");
  }
  return response.json();
}

/** Replace a location's custom-field values (#103). extra values are JSON-encoded strings. */
export async function updateLocationExtra(id: number, extra: { [key: string]: string }): Promise<ILocation> {
  const response = await fetch(`${getAPIURL()}/locations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extra }),
  });
  if (!response.ok) {
    throw new Error("Failed to update location");
  }
  return response.json();
}

interface LocationRename {
  old: string;
  new: string;
}

export function useRenameSpoolLocation() {
  const queryClient = useQueryClient();
  const queryKey = ["default", "spool"];
  const queryKeyList = ["default", "spool", "list"];

  return useMutation<string, unknown, LocationRename, undefined>({
    mutationFn: async (value) => {
      const response = await fetch(getAPIURL() + "/location/" + value.old, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: value.new,
        }),
      });
      if (!response.ok) {
        throw new Error("Network response was not ok");
      }
      return await response.text();
    },
    onMutate: async (value) => {
      await queryClient.cancelQueries({
        queryKey: queryKeyList,
      });

      // Optimistically update all spools with matching location to the new one
      queryClient.setQueriesData<GetListResponse<ISpool>>({ queryKey: queryKeyList }, (old) => {
        if (old) {
          return {
            data: old.data.map((spool) => {
              if (spool.location === value.old) {
                return { ...spool, location: value.new };
              }
              return spool;
            }),
            total: old.total,
          };
        }
        return old;
      });
    },
    onError: (_error, value) => {
      // Mutation failed, reset spools with matching location to the old one
      queryClient.setQueriesData<GetListResponse<ISpool>>({ queryKey: queryKeyList }, (old) => {
        if (old) {
          return {
            data: old.data.map((spool) => {
              if (spool.location === value.new) {
                return { ...spool, location: value.old };
              }
              return spool;
            }),
            total: old.total,
          };
        }
        return old;
      });
    },
    onSuccess: () => {
      // Mutation succeeded, refetch
      queryClient.invalidateQueries({
        queryKey: queryKey,
      });
    },
  });
}

export function useLocations(): string[] | null {
  const query = useGetSetting("locations");

  return useMemo(() => {
    if (!query.data) return null;

    try {
      let data = (JSON.parse(query.data.value) ?? []) as string[];
      data = data.filter((location) => location != null && location.length > 0);
      return data;
    } catch {
      console.warn("Failed to parse locations", query.data.value);
      return null;
    }
  }, [query.data]);
}

export function useLocationsSpoolOrders(): Record<string, number[]> {
  const query = useGetSetting("locations_spoolorders");

  return useMemo(() => {
    if (!query.data) return {};

    try {
      return (JSON.parse(query.data.value) ?? {}) as Record<string, number[]>;
    } catch {
      console.warn("Failed to parse locations spool orders", query.data.value);
      return {};
    }
  }, [query.data]);
}
