import { axiosInstance } from "@refinedev/simple-rest";

const RELOAD_FLAG_KEY = "spoolmanAuthReloadedAt";
const RELOAD_COOLDOWN_MS = 30_000;

/**
 * Reloads the page on 401 so a forward-auth proxy can redirect through its
 * login portal and back. Cooldown bounds reload loops if recovery fails. The
 * PWA service worker's NavigationRoute would otherwise serve the precached
 * index.html and prevent the reload from reaching the proxy, so unregister it.
 */
export async function reloadOnAuthFailure(): Promise<void> {
  let last = 0;
  try {
    last = Number(localStorage.getItem(RELOAD_FLAG_KEY) || "0");
  } catch {
    /* storage unavailable */
  }
  if (Date.now() - last < RELOAD_COOLDOWN_MS) return;
  try {
    localStorage.setItem(RELOAD_FLAG_KEY, String(Date.now()));
  } catch {
    /* storage unavailable */
  }
  if ("serviceWorker" in navigator) {
    try {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map((r) => r.unregister()));
    } catch {
      /* fall through to reload anyway */
    }
  }
  window.location.reload();
}

/**
 * fetch() wrapper mirroring the axios 401 handler for the app's bare-fetch reads
 * (settings, fields, external catalog, /info, autocomplete models). On a 401 to an
 * idempotent GET/HEAD it triggers the debounced auth reload so a forward-auth proxy can
 * redirect through its login portal, then returns the response unchanged so callers are
 * unaffected. Issue #47.
 */
export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const response = await fetch(input, init);
  if (response.status === 401) {
    const method = String(init?.method ?? "get").toLowerCase();
    if (method === "get" || method === "head") void reloadOnAuthFailure();
  }
  return response;
}

/**
 * Recover from a transport that cannot report its own HTTP status — the WebSocket
 * upgrade. A forward-auth proxy that expired the session rejects the upgrade with 401,
 * surfacing as an abnormal close that is indistinguishable from a server restart. Probe
 * the API through apiFetch so a genuine 401 reloads while a network error (server
 * unreachable) is swallowed, matching the axios handler that reacts only to 401 and never
 * to connection failures — otherwise the SPA would reload-loop during an outage. Issue #47.
 */
export async function reloadIfAuthFailed(url: string): Promise<void> {
  try {
    await apiFetch(url, { method: "GET" });
  } catch {
    /* server unreachable — not an auth failure, do not reload */
  }
}

interface AuthError {
  response?: { status?: number };
  config?: { method?: string };
}

/**
 * Axios response-error handler: reload on a 401 for idempotent (GET/HEAD) requests
 * only, so unsaved form data on POST/PUT/PATCH/DELETE is preserved — mutation 401s
 * surface through the Refine notification provider instead. Always re-rejects so
 * callers still see the error.
 */
export function handleAuthResponseError(error: AuthError): Promise<never> {
  if (error?.response?.status === 401) {
    const method = String(error.config?.method ?? "get").toLowerCase();
    if (method === "get" || method === "head") void reloadOnAuthFailure();
  }
  return Promise.reject(error);
}

// Guard against double-registration: in dev, Vite/React fast refresh can
// re-evaluate this module, which would otherwise stack duplicate interceptors
// and fire multiple reloads per 401. The flag lives on the shared axios
// instance (not module scope) so it survives module re-evaluation.
const instance = axiosInstance as typeof axiosInstance & {
  __spoolmanAuthReloadInstalled?: boolean;
};

if (!instance.__spoolmanAuthReloadInstalled) {
  instance.__spoolmanAuthReloadInstalled = true;
  axiosInstance.interceptors.response.use((response) => response, handleAuthResponseError);
}
