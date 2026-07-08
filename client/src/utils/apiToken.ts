import { create } from "zustand";

// Client-side storage and wiring for the opt-in API bearer token (issue #48). When the server has
// SPOOLMAN_API_TOKEN set, requests answered with 401 + `WWW-Authenticate: Bearer` open a prompt; the
// entered token is stored here and attached to every transport (axios header, apiFetch header, and
// the websocket `?token=` query, since browsers can't set headers on a WS handshake).

const TOKEN_KEY = "spoolmanApiToken";

export function getApiToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setApiToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable */
  }
}

export function clearApiToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

/** Authorization header for a request, or an empty object when no token is stored. */
export function apiAuthHeader(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Append ?token= to a websocket URL when a token is stored. */
export function withWebsocketToken(url: string): string {
  const token = getApiToken();
  if (!token) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}

interface ApiTokenModalState {
  open: boolean;
  /** Open the token prompt — called when the API answers 401 with WWW-Authenticate: Bearer. */
  requireToken: () => void;
  close: () => void;
}

export const useApiTokenModal = create<ApiTokenModalState>((set) => ({
  open: false,
  requireToken: () => set({ open: true }),
  close: () => set({ open: false }),
}));
