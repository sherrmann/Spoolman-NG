// Thin typed client for the handful of Spoolman NG endpoints the shell calls
// natively. The hosted web UI does everything else through its own transport.

import { ForwardAuthError, extractAuthUrl, looksLikeForwardAuth } from "../lib/forwardAuth";
import { apiUrl } from "../lib/serverProfile";

export interface ServerInfo {
  version: string;
  git_commit?: string | null;
  build_date?: string | null;
}

export interface AuthStatus {
  auth_required: boolean;
  accounts_enabled: boolean;
}

/** Mirrors NfcLookupResponse in spoolman/api/v1/nfc.py. */
export interface NfcLookupResult {
  success: boolean;
  spool_id: number | null;
  tag_format: string | null;
  message: string;
}

export interface NfcLookupRequest {
  raw_data_b64?: string;
  nfc_tag_uid?: string;
  auto_create?: boolean;
}

async function request<T>(
  url: string,
  token: string | null,
  init: { method?: string; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), init.timeoutMs ?? 10000);
  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    if (init.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(url, {
      method: init.method ?? "GET",
      headers,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new ApiError(response.status, await safeText(response), response.url);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

async function safeText(response: Response): Promise<string> {
  try {
    return (await response.text()).slice(0, 300);
  } catch {
    return "";
  }
}

export class ApiError extends Error {
  status: number;
  body: string;
  url: string;

  constructor(status: number, body: string, url = "") {
    super(`HTTP ${status}${body ? `: ${body}` : ""}`);
    this.status = status;
    this.body = body;
    this.url = url;
  }
}

/**
 * Validate a base URL as a Spoolman server. /info and /auth/status are public
 * even when auth is enabled; /auth/status is absent on upstream Spoolman, so
 * a failure there degrades to null instead of failing the probe.
 */
export async function probeServer(
  baseUrl: string,
): Promise<{ info: ServerInfo; auth: AuthStatus | null }> {
  let info: ServerInfo;
  try {
    info = await request<ServerInfo>(apiUrl(baseUrl, "/info"), null, { timeoutMs: 8000 });
  } catch (e) {
    // A forward-auth gateway (Authelia, Authentik, …) blocks even the public
    // /info. Surface that as its own error so setup can route the user through
    // an in-WebView portal login instead of showing a dead-end failure.
    if (
      e instanceof ApiError &&
      looksLikeForwardAuth({ status: e.status, body: e.body, finalUrl: e.url, baseUrl })
    ) {
      throw new ForwardAuthError(extractAuthUrl(e.body));
    }
    throw e;
  }
  let auth: AuthStatus | null = null;
  try {
    auth = await request<AuthStatus>(apiUrl(baseUrl, "/auth/status"), null, { timeoutMs: 8000 });
  } catch {
    auth = null;
  }
  return { info, auth };
}

/** POST raw tag memory to the server, exactly like a Klipper NFC daemon. */
export async function nfcLookup(
  baseUrl: string,
  token: string | null,
  body: NfcLookupRequest,
): Promise<NfcLookupResult> {
  return request<NfcLookupResult>(apiUrl(baseUrl, "/nfc/lookup"), token, {
    method: "POST",
    body,
    timeoutMs: 15000,
  });
}
