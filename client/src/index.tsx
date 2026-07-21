import "@ant-design/v5-patch-for-react-19";
import React from "react";
import { createRoot } from "react-dom/client";

import "./utils/authReloadHandler";
import App from "./App";
import "./i18n";
import { getBasePath, isHaIngress } from "./utils/url";

const container = document.getElementById("root") as HTMLElement;
const root = createRoot(container);

root.render(
  <React.StrictMode>
    <React.Suspense fallback="loading">
      <App />
    </React.Suspense>
  </React.StrictMode>,
);

// Under Home Assistant ingress the base path carries a rotating per-session token, so no
// service-worker scope can outlive the session — skip registration there (#211). The direct
// host-port origin of the same server keeps the full PWA.
if (!import.meta.env.DEV && "serviceWorker" in navigator && !isHaIngress()) {
  window.addEventListener("load", () => {
    const base = getBasePath(); // "" at root, "/spoolman" when sub-path hosted
    void navigator.serviceWorker.register(`${base}/sw.js`, { scope: `${base}/` });
  });
}
