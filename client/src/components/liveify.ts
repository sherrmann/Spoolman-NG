import { LiveEvent } from "@refinedev/core";
import { useEffect, useState } from "react";
import { getAPIURL } from "../utils/url";
import liveProvider from "./liveProvider";

const liveProviderInstance = liveProvider(getAPIURL());

/**
 * Backfill `keys` from the previous row when the payload omitted them (#226). Websocket
 * payloads leave the REST-only aggregate fields unset (they are "null in nested/websocket
 * payloads" per the API models and omitted by exclude_none), so a live update would
 * otherwise blank those columns until a manual reload.
 */
export function carryForwardFields<Data extends object>(
  payload: Data,
  previous: Data | undefined,
  keys: (keyof Data)[],
): Data {
  if (!previous) return payload;
  const out = { ...payload };
  for (const key of keys) {
    if (out[key] === undefined || out[key] === null) {
      out[key] = previous[key];
    }
  }
  return out;
}

/**
 * Hook that subscribes to live updates for the items in the dataSource
 * @param dataSource Original dataSource
 * @returns dataSource that is updated with live data. The transform receives the previous
 * row alongside the payload so REST-only fields can be carried forward (#226).
 */
export function useLiveify<Data extends { id: number }>(
  resource: string,
  dataSource: Data[],
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  transformPayload: (payload: any, previous?: Data) => Data,
) {
  // New state that holds the dataSource with updated values from the live provider
  const [updatedDataSource, setUpdatedDataSource] = useState<Data[]>(dataSource);

  // If the original dataSource changes, update the updatedDataSource
  useEffect(() => {
    setUpdatedDataSource(dataSource);
  }, [dataSource]);

  // Subscribe to changes for all items in the dataSource
  useEffect(() => {
    const itemIds = dataSource.map((item) => item.id);

    const subscription = liveProviderInstance?.subscribe({
      channel: `${resource}-list`,
      params: {
        resource: resource,
        ids: itemIds,
        subscriptionType: "useList",
      },
      types: ["update"],
      callback: (event: LiveEvent) => {
        setUpdatedDataSource((prev) =>
          prev.map((item) => {
            return item.id === event.payload.data.id ? transformPayload(event.payload.data, item) : item;
          }),
        );
      },
    });

    // Unsubscribe when the component unmounts
    return () => {
      if (subscription) {
        liveProviderInstance?.unsubscribe(subscription);
      }
    };
  }, [resource, dataSource, transformPayload]);

  return updatedDataSource;
}
