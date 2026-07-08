import { CrudFilter, CrudSort } from "@refinedev/core";
import { useEffect, useState } from "react";
import { isLocalStorageAvailable } from "./support";
interface Pagination {
  currentPage: number;
  pageSize: number;
}

export interface TableState {
  sorters: CrudSort[];
  filters: CrudFilter[];
  pagination: Pagination;
  showColumns?: string[];
}

/**
 * Read a persisted table-state property, preferring the URL hash (shared links) over
 * localStorage, and return both the raw string and a cleanup function that clears
 * whichever source it came from. `showColumns` has no hash form, so it always falls
 * through to localStorage.
 */
function readSaved(tableId: string, key: string): { raw: string | null; clear: () => void } {
  if (hasHashProperty(key)) {
    return { raw: getHashProperty(key), clear: () => removeURLHash(key) };
  }
  if (isLocalStorageAvailable) {
    return {
      raw: localStorage.getItem(`${tableId}-${key}`),
      clear: () => localStorage.removeItem(`${tableId}-${key}`),
    };
  }
  return { raw: null, clear: () => {} };
}

/**
 * JSON.parse the persisted value, falling back to `fallback` (and clearing the poisoned
 * source) when it is corrupt. A hand-edited/truncated URL hash or localStorage value must
 * never throw out of here — an unhandled exception white-screens the whole list page. #44.
 */
function parseSaved<T>(saved: { raw: string | null; clear: () => void }, fallback: T): T {
  if (!saved.raw) return fallback;
  try {
    return JSON.parse(saved.raw) as T;
  } catch {
    saved.clear();
    return fallback;
  }
}

export function useInitialTableState(tableId: string): TableState {
  const [initialState] = useState(() => {
    const sorters = parseSaved<CrudSort[]>(readSaved(tableId, "sorters"), [{ field: "id", order: "asc" }]);
    const filters = parseSaved<CrudFilter[]>(readSaved(tableId, "filters"), []);
    // Default matches the Pagination shape the list pages read (`currentPage`); the old
    // `{ page: 1, … }` default had no currentPage and only worked because the dataProvider
    // falls back to page 1 when it is undefined.
    const pagination = parseSaved<Pagination>(readSaved(tableId, "pagination"), { currentPage: 1, pageSize: 20 });
    const showColumns = parseSaved<string[] | undefined>(readSaved(tableId, "showColumns"), undefined);
    return { sorters, filters, pagination, showColumns };
  });
  return initialState;
}

export function useStoreInitialState(tableId: string, state: TableState) {
  useEffect(() => {
    if (state.sorters.length > 0 && JSON.stringify(state.sorters) != JSON.stringify([{ field: "id", order: "asc" }])) {
      if (isLocalStorageAvailable) {
        localStorage.setItem(`${tableId}-sorters`, JSON.stringify(state.sorters));
      }
      setURLHash(`sorters`, JSON.stringify(state.sorters));
    } else {
      localStorage.removeItem(`${tableId}-sorters`);
      removeURLHash("sorters");
    }
  }, [tableId, state.sorters]);

  useEffect(() => {
    const filters = state.filters.filter((f) => f.value.length != 0);
    if (filters.length > 0) {
      if (isLocalStorageAvailable) {
        localStorage.setItem(`${tableId}-filters`, JSON.stringify(filters));
        setURLHash("filters", JSON.stringify(filters));
      }
    } else {
      localStorage.removeItem(`${tableId}-filters`);
      removeURLHash(`filters`);
    }
  }, [tableId, state.filters]);

  useEffect(() => {
    if (JSON.stringify(state.pagination) != JSON.stringify({ current: 1, pageSize: 20 })) {
      if (isLocalStorageAvailable) {
        localStorage.setItem(`${tableId}-pagination`, JSON.stringify(state.pagination));
      }
      setURLHash(`pagination`, JSON.stringify(state.pagination));
    } else {
      localStorage.removeItem(`${tableId}-pagination`);
      removeURLHash(`pagination`);
    }
  }, [tableId, state.pagination]);

  useEffect(() => {
    if (isLocalStorageAvailable) {
      if (state.showColumns === undefined) {
        localStorage.removeItem(`${tableId}-showColumns`);
      } else {
        localStorage.setItem(`${tableId}-showColumns`, JSON.stringify(state.showColumns));
      }
    }
  }, [tableId, state.showColumns]);
}

export function useSavedState<T>(id: string, defaultValue: T) {
  const [state, setState] = useState<T>(() => {
    const savedState = isLocalStorageAvailable ? localStorage.getItem(`savedStates-${id}`) : null;
    if (!savedState) return defaultValue;
    try {
      return JSON.parse(savedState) as T;
    } catch {
      // Heal storage poisoned by older builds: an undefined state used to be written
      // as JSON.stringify(undefined) === undefined, which localStorage coerced to the
      // string "undefined" and then threw on the next JSON.parse.
      return defaultValue;
    }
  });

  useEffect(() => {
    if (!isLocalStorageAvailable) return;
    // JSON.stringify(undefined) returns undefined, which localStorage.setItem stores as
    // the literal string "undefined" — poisoning the key so the next read throws. Remove
    // the key instead (mirrors how table showColumns is persisted above).
    if (state === undefined) {
      localStorage.removeItem(`savedStates-${id}`);
    } else {
      localStorage.setItem(`savedStates-${id}`, JSON.stringify(state));
    }
  }, [id, state]);

  return [state, setState] as const;
}

function setURLHash(Id: string, value: string) {
  const params = new URLSearchParams(window.location.hash.substring(1));
  if (!params.has(Id)) {
    params.append(Id, value);
  }
  params.set(Id, value);
  window.location.hash = params.toString();
}
function removeURLHash(Id: string) {
  const params = new URLSearchParams(window.location.hash.substring(1));
  if (params.has(Id)) {
    params.delete(Id);
  }
  window.location.hash = params.toString();
}

function getHashProperty(Id: string) {
  const hash = new URLSearchParams(window.location.hash.substring(1));
  return hash.get(Id);
}

function hasHashProperty(property: string): boolean {
  const hash = new URLSearchParams(window.location.hash.substring(1));
  return hash.has(property);
}
