import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// A printer entity (#75). Managed from Settings; spools reference one via printer_id.
export interface IPrinter {
  id: number;
  registered: string;
  name: string;
  comment?: string;
  spool_count?: number;
  extra?: { [key: string]: string };
}

const PRINTERS_KEY = ["printers"];

/** Fetch all printers. Used by the Settings management tab and the spool-form assignment select. */
export function useGetPrinters() {
  return useQuery<IPrinter[]>({
    queryKey: PRINTERS_KEY,
    queryFn: async () => {
      const response = await apiFetch(`${getAPIURL()}/printer`);
      return response.json();
    },
  });
}

async function mutatePrinter(method: string, path: string, body?: object): Promise<IPrinter> {
  const response = await apiFetch(`${getAPIURL()}/printer${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new Error((await response.json().catch(() => ({}))).message ?? "Request failed");
  }
  return response.json();
}

export function useCreatePrinter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; comment?: string }) => mutatePrinter("POST", "", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PRINTERS_KEY }),
  });
}

export function useUpdatePrinter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; comment?: string }) =>
      mutatePrinter("PATCH", `/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PRINTERS_KEY }),
  });
}

export function useDeletePrinter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => mutatePrinter("DELETE", `/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PRINTERS_KEY }),
  });
}
