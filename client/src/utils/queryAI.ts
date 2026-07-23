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
  stt_base_url: string | null;
  stt_model: string | null;
  stt_api_key_set: boolean;
  stt_configured: boolean;
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

export interface SpoolIntakeExtraction {
  vendor: string | null;
  name: string | null;
  material: string | null;
  color_hex: string | null;
  weight_g: number | null;
  spool_weight_g: number | null;
  diameter_mm: number | null;
  extruder_temp_c: number | null;
  bed_temp_c: number | null;
  lot_nr: string | null;
  article_number: string | null;
  confidence: string | null;
}

export interface SpoolIntakeMatch {
  kind: "library" | "catalog";
  filament_id?: number;
  external_id?: string;
  vendor: string | null;
  name: string | null;
  material: string | null;
  weight_g?: number | null;
  active_spool_count?: number;
  remaining_weight_g?: number;
  diameter_mm?: number | null;
  match_percent: number;
}

export interface SpoolIntakeResult {
  extraction: SpoolIntakeExtraction;
  matches: { library: SpoolIntakeMatch[]; catalog: SpoolIntakeMatch[] };
}

export function useSpoolIntakeExtract() {
  return useMutation<SpoolIntakeResult, Error, { image_base64: string; mime: string }>({
    mutationFn: async (body) => {
      const response = await apiFetch(`${getAPIURL()}/ai/spool-intake/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
  });
}

export interface AIChatEvent {
  tool: string;
  detail: string | null;
}

export interface AIChatPending {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
}

export interface AIChatResponse {
  /** Opaque wire transcript; hold it and send it back verbatim on the next turn. */
  messages: unknown[];
  reply: string | null;
  events: AIChatEvent[];
  pending: AIChatPending | null;
  stopped_reason: string | null;
}

export interface AIChatRequest {
  messages: unknown[];
  context?: { page?: string; locale?: string };
  resolve?: { id: string; approved: boolean };
}

export function useAIChat() {
  return useMutation<AIChatResponse, Error, AIChatRequest>({
    mutationFn: async (body) => {
      const response = await apiFetch(`${getAPIURL()}/ai/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
  });
}

export interface AISearchFilters {
  search?: string;
  materials?: string[];
  vendors?: string[];
  locations?: string[];
  lot_numbers?: string[];
  article_numbers?: string[];
  color_hex?: string;
  archived?: boolean;
}

export interface AISearchResult {
  filters: AISearchFilters;
  dropped: string[];
}

export function useAISearch() {
  return useMutation<AISearchResult, Error, { entity: "spool" | "filament"; query: string }>({
    mutationFn: async (body) => {
      const response = await apiFetch(`${getAPIURL()}/ai/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
  });
}

export interface AIKeyUpdate {
  /** Only fields present are applied server-side; null clears the stored key. */
  api_key?: string | null;
  stt_api_key?: string | null;
}

export interface AIKeyResult {
  api_key_set: boolean;
  env_locked: boolean;
  stt_api_key_set: boolean;
  stt_env_locked: boolean;
}

export function useSetAIKey() {
  const queryClient = useQueryClient();
  return useMutation<AIKeyResult, Error, AIKeyUpdate>({
    mutationFn: async (update) => {
      const response = await apiFetch(`${getAPIURL()}/ai/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
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

export function useTranscribe() {
  return useMutation<{ text: string }, Error, { audio_base64: string; mime: string; language?: string }>({
    mutationFn: async (body) => {
      const response = await apiFetch(`${getAPIURL()}/ai/transcribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
  });
}
