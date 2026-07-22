// Shared between playwright.config.ts (webServer definitions) and the specs.
// Two static harness instances serve the built client at the two deploy shapes
// (PWA base-path/SW tests), a third runs the REAL backend (API + client +
// temp SQLite) for whole-app user-journey tests, and a fourth wraps another
// real backend in a simulated Home Assistant ingress gateway (#211).
export const ROOT_BASE_URL = "http://127.0.0.1:30011";
export const SUBPATH_BASE_URL = "http://127.0.0.1:30012";
export const SUBPATH = "/spoolman";
export const APP_BASE_URL = "http://127.0.0.1:30013";
export const INGRESS_BASE_URL = "http://127.0.0.1:30014";

// Build an HA-shaped ingress session prefix, mirroring /api/hassio_ingress/<token>.
// The gateway derives the prefix from the URL itself, so specs "rotate the session
// token" by simply using a different token here.
export const ingressPrefix = (token: string): string => `/api/hassio_ingress/${token}`;

export const DEPLOYMENTS = [
  { name: "root deploy", origin: ROOT_BASE_URL, base: "" },
  { name: "sub-path deploy", origin: SUBPATH_BASE_URL, base: SUBPATH },
] as const;
