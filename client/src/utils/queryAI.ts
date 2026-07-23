import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// Client bindings for the AI foundation endpoints (#359). The API key is write-only:
// nothing here ever receives it back from the server, only whether one is set.

export type AITriState = "yes" | "no" | "unknown";

export interface AIProbeResult {
  ok: boolean;
  error: string | null;
  latency_ms: number | null;
  models: string[];
  chat: AITriState;
  tools: AITriState;
  vision: AITriState;
  is_ollama: boolean;
  checked_at: string | null;
}

export interface AIStatus {
  configured: boolean;
  base_url: string | null;
  model: string | null;
  vision_model: string | null;
  api_key_set: boolean;
  env_locked: string[];
  features: Record<string, boolean>;
  capabilities: AIProbeResult | null;
}

export interface AIProbeRequest {
  base_url?: string;
  api_key?: string;
  model?: string;
  vision_model?: string;
}

export function useAIStatus() {
  return useQuery<AIStatus>({
    queryKey: ["ai-status"],
    queryFn: async () => {
      const response = await apiFetch(`${getAPIURL()}/ai/status`);
      return response.json();
    },
  });
}

export function useAIProbe() {
  const queryClient = useQueryClient();
  return useMutation<AIProbeResult, Error, AIProbeRequest>({
    mutationFn: async (overrides) => {
      const response = await apiFetch(`${getAPIURL()}/ai/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(overrides),
      });
      if (!response.ok) {
        throw new Error((await response.json()).message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
    onSuccess: () => {
      // The probe result is cached server-side and mirrored into /ai/status.
      queryClient.invalidateQueries({ queryKey: ["ai-status"] });
    },
  });
}

export function useSetAIKey() {
  const queryClient = useQueryClient();
  return useMutation<{ api_key_set: boolean; env_locked: boolean }, Error, string | null>({
    mutationFn: async (apiKey) => {
      const response = await apiFetch(`${getAPIURL()}/ai/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      if (!response.ok) {
        throw new Error((await response.json()).message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-status"] });
    },
  });
}
