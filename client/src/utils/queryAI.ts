import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL, getBasePath } from "./url";

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
  stt_configured: boolean;
  stt_base_url: string | null;
  stt_model: string | null;
  stt_api_key_set: boolean;
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

// Set (or clear, with null) one of the write-only keys via /ai/config. `field` picks which:
// "api_key" for the chat provider, "stt_api_key" for the speech-to-text endpoint (#363).
function useSetKey(field: "api_key" | "stt_api_key") {
  const queryClient = useQueryClient();
  return useMutation<{ api_key_set: boolean; env_locked: boolean; stt_api_key_set: boolean }, Error, string | null>({
    mutationFn: async (value) => {
      const response = await apiFetch(`${getAPIURL()}/ai/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
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

export function useSetAIKey() {
  return useSetKey("api_key");
}

export function useSetSTTKey() {
  return useSetKey("stt_api_key");
}

// --- Voice transcription (#363) ----------------------------------------------------

export function useTranscribe() {
  return useMutation<{ text: string }, Error, Blob>({
    mutationFn: async (audio) => {
      const form = new FormData();
      // Filename hints the STT server at the container; the actual type is on the blob.
      form.append("file", audio, "clip.webm");
      const response = await apiFetch(`${getAPIURL()}/ai/transcribe`, { method: "POST", body: form });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
  });
}

// --- Natural-language search (#362, B2) --------------------------------------------

export interface NlSearchFilter {
  field: string;
  values: string[];
}

export interface NlSearchResult {
  filters: NlSearchFilter[];
  search: string | null;
  color_hex: string | null;
  sort: { field: string; direction: "asc" | "desc" } | null;
}

export function useNlSearch() {
  return useMutation<NlSearchResult, Error, { query: string; locale: string }>({
    mutationFn: async (body) => {
      const response = await apiFetch(`${getAPIURL()}/ai/nl-search`, {
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

// --- Chat assistant (#362, B1) -----------------------------------------------------

// The OpenAI-shape transcript the client round-trips. Assistant turns may carry tool_calls
// and tool turns a tool_call_id; the client holds them opaquely and only replays them.
export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string | null;
  tool_calls?: unknown[];
  tool_call_id?: string;
}

export interface ChatConfirmCard {
  tool_call_id?: string;
  tool: string;
  title: string;
  summary: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  destructive: boolean;
}

export interface ChatUndo {
  tool: string;
  args: Record<string, unknown>;
}

export interface ChatExecutedCard {
  tool: string;
  summary: string;
  undo: ChatUndo | null;
}

// Deep-link filters the server echoes from a spool search, so the UI can offer a
// "view these in the Spools list" link.
export interface ChatSpoolFilters {
  material?: string;
  vendor?: string;
  location?: string;
  lot_nr?: string;
  color_hex?: string;
  query?: string;
  include_archived?: boolean;
}

export type ChatEvent =
  | { event: "tool"; data: { name: string; summary: string; filters?: ChatSpoolFilters } }
  | { event: "confirm"; data: { messages: ChatMessage[]; cards: ChatConfirmCard[] } }
  | { event: "executed"; data: { cards: ChatExecutedCard[] } }
  | { event: "cancelled"; data: Record<string, never> }
  | { event: "message"; data: { content: string } }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: Record<string, never> };

export interface ChatTurnRequest {
  messages: ChatMessage[];
  context?: string | null;
  locale?: string;
  decision?: "confirm" | "cancel";
}

function parseSseBlock(block: string): ChatEvent | null {
  let event = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice("event: ".length);
    else if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (!event) return null;
  try {
    return { event, data: data ? JSON.parse(data) : {} } as ChatEvent;
  } catch {
    return null;
  }
}

/**
 * Stream one chat turn, invoking `onEvent` for each Server-Sent Event as it arrives.
 * Resolves when the stream ends (a `done` event is always the last one). Throws on a
 * non-200 response (gating/config errors) before any event is delivered.
 */
export async function streamChat(
  body: ChatTurnRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiFetch(`${getAPIURL()}/ai/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseBlock(block);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export function useChatAction() {
  return useMutation<{ summary: string; data: Record<string, unknown>; undo: ChatUndo | null }, Error, ChatUndo>({
    mutationFn: async (action) => {
      const response = await apiFetch(`${getAPIURL()}/ai/chat/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
  });
}

/**
 * Build a deep-link into the Spools list with the given categorical filters applied,
 * mirroring the list's URL-hash filter format (double-quoted exact-match values). Used by
 * the chat to offer "view these in the Spools list".
 */
export function spoolListFilterLink(filters: ChatSpoolFilters): string | null {
  const fieldByKey: Record<string, string> = {
    material: "filament.material",
    vendor: "filament.vendor.name",
    location: "location",
    lot_nr: "lot_nr",
  };
  const crudFilters = Object.entries(fieldByKey)
    .filter(([key]) => typeof filters[key as keyof ChatSpoolFilters] === "string")
    .map(([key, field]) => ({
      field,
      operator: "in",
      value: [JSON.stringify(filters[key as keyof ChatSpoolFilters])],
    }));
  if (crudFilters.length === 0) return null;
  const hash = new URLSearchParams({ filters: JSON.stringify(crudFilters) }).toString();
  return `${getBasePath()}/spool#${hash}`;
}
