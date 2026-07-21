import { INGRESS_BASE_URL, ingressPrefix } from "./constants";
import { expect, test } from "./fixtures";

// End-to-end coverage for Home Assistant ingress support (#211), driven against the REAL
// backend behind a simulated HA ingress gateway (see ingress_gateway.py): requests under
// /api/hassio_ingress/<token>/ reach the app prefix-stripped with X-Ingress-Path set —
// exactly what the Supervisor's ingress proxy does — while prefix-less requests hit the
// same process directly, mirroring an add-on whose host port stays published.
//
// What must hold (the issue's acceptance criteria):
//   * The full UI boots inside the session prefix — assets, config.js, API calls and the
//     live-update websocket all follow the rotating base, across session-token rotations.
//   * No service worker is registered under ingress (a SW scope cannot follow a rotating
//     token path; navigateFallback is already suppressed so nothing else depends on it).
//   * Direct access to the very same server process behaves exactly as today, PWA and
//     service worker included — ingress is purely additive.

const BASE_A = ingressPrefix("e2eSessionTokenA0123456789");
const BASE_B = ingressPrefix("e2eSessionTokenB9876543210");

test.describe("HA ingress panel (#211)", () => {
  test("boots the full UI under the session prefix with every request resolving", async ({ page }) => {
    // Any failing app-shell request under the prefix — asset, locale, config.js, manifest —
    // is a broken panel. API 4xx are excluded (e.g. unset settings legitimately 404; the
    // fixtures already fail the test on any API 5xx); API health is asserted positively below.
    const failedShellRequests: string[] = [];
    let apiOkResponses = 0;
    page.on("response", (r) => {
      const { pathname } = new URL(r.url());
      if (!pathname.startsWith("/api/hassio_ingress/")) return;
      if (pathname.includes("/api/v1/")) {
        if (r.ok()) apiOkResponses += 1;
      } else if (r.status() >= 400) {
        failedShellRequests.push(`${r.status()} ${pathname}`);
      }
    });

    // Deep link straight into the panel: exercises the SPA fallback under ingress too.
    await page.goto(`${INGRESS_BASE_URL}${BASE_A}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();

    // config.js resolved the base from X-Ingress-Path and flagged ingress mode.
    await expect
      .poll(async () => page.evaluate(() => [window.SPOOLMAN_BASE_PATH, window.SPOOLMAN_HA_INGRESS]))
      .toEqual([BASE_A, true]);

    expect(failedShellRequests, "no app-shell request under the ingress prefix may fail").toEqual([]);
    expect(apiOkResponses, "API traffic must flow through the ingress prefix").toBeGreaterThan(0);
  });

  test("serves the manifest scoped to the session prefix", async ({ request }) => {
    const res = await request.get(`${INGRESS_BASE_URL}${BASE_A}/manifest.webmanifest`);
    expect(res.ok()).toBeTruthy();
    const manifest = await res.json();
    expect(manifest.start_url).toBe(`${BASE_A}/`);
    expect(manifest.scope).toBe(`${BASE_A}/`);
    // Per-session content must never be cached across token rotations.
    expect(res.headers()["cache-control"]).toBe("no-store");
  });

  test("all three per-session responses are uncacheable, config.js included", async ({ request }) => {
    // index.html, the manifest and /config.js embed the rotating session base; a cached
    // copy would pin a dead token after rotation. This hits the REAL main.py routes.
    for (const path of ["/", "/manifest.webmanifest", "/config.js"]) {
      const res = await request.get(`${INGRESS_BASE_URL}${BASE_A}${path}`);
      expect(res.ok(), path).toBeTruthy();
      expect(res.headers()["cache-control"], path).toBe("no-store");
    }

    // config.js body is per-request: the session base + ingress flag under the prefix…
    const ingressConfig = await (await request.get(`${INGRESS_BASE_URL}${BASE_A}/config.js`)).text();
    expect(ingressConfig).toContain(`window.SPOOLMAN_BASE_PATH = "${BASE_A}";`);
    expect(ingressConfig).toContain("window.SPOOLMAN_HA_INGRESS = true;");

    // …and on direct access the legacy body (no flag), still uncacheable.
    const directRes = await request.get(`${INGRESS_BASE_URL}/config.js`);
    expect(directRes.headers()["cache-control"]).toBe("no-store");
    const directConfig = await directRes.text();
    expect(directConfig).toContain('window.SPOOLMAN_BASE_PATH = "";');
    expect(directConfig).not.toContain("SPOOLMAN_HA_INGRESS");
  });

  test("registers no service worker under ingress", async ({ page }) => {
    await page.goto(`${INGRESS_BASE_URL}${BASE_A}/`);
    await page.waitForLoadState("load");
    // The app is up and knows it runs under ingress — i.e. we are past the point where
    // index.tsx would have registered the SW (it does so in a "load" listener).
    await expect(page.locator("#root")).not.toBeEmpty();
    await expect.poll(async () => page.evaluate(() => window.SPOOLMAN_HA_INGRESS)).toBe(true);
    // Settle a tick beyond "load" so an (erroneous) registration would have surfaced.
    await page.waitForTimeout(1_000);
    const registrations = await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length);
    expect(registrations, "no SW may be registered under a rotating ingress path").toBe(0);
  });

  test("live updates flow through the ingress-prefixed websocket", async ({ page, request }) => {
    // Seed a spool THROUGH the ingress prefix (proves API writes under the prefix, too).
    const marker = `IngressSpec ${Date.now()}`;
    const filRes = await request.post(`${INGRESS_BASE_URL}${BASE_A}/api/v1/filament`, {
      data: { name: marker, density: 1.24, diameter: 1.75, weight: 1000 },
    });
    expect(filRes.ok()).toBeTruthy();
    const spoolRes = await request.post(`${INGRESS_BASE_URL}${BASE_A}/api/v1/spool`, {
      data: { filament_id: (await filRes.json()).id, initial_weight: 1000 },
    });
    expect(spoolRes.ok()).toBeTruthy();
    const spoolId = (await spoolRes.json()).id as number;

    const wsUrls: string[] = [];
    page.on("websocket", (ws) => wsUrls.push(ws.url()));

    // The show page subscribes to this spool with liveMode "auto".
    await page.goto(`${INGRESS_BASE_URL}${BASE_A}/spool/show/${spoolId}`);
    await expect(page.getByText(marker).first()).toBeVisible();
    await expect
      .poll(() => wsUrls.filter((u) => u.includes(`${BASE_A}/api/v1/`)).length, {
        message: "the live-update websocket must connect under the ingress prefix",
      })
      .toBeGreaterThan(0);

    // A change made via the API must appear WITHOUT a reload: the event travelled
    // through the ingress-prefixed websocket the page opened above.
    const liveComment = `live-through-ingress ${Date.now()}`;
    const patchRes = await request.patch(`${INGRESS_BASE_URL}${BASE_A}/api/v1/spool/${spoolId}`, {
      data: { comment: liveComment },
    });
    expect(patchRes.ok()).toBeTruthy();
    await expect(page.getByText(liveComment)).toBeVisible();
  });

  test("survives a session-token rotation without stale state", async ({ page }) => {
    await page.goto(`${INGRESS_BASE_URL}${BASE_A}/`);
    await expect.poll(async () => page.evaluate(() => window.SPOOLMAN_BASE_PATH)).toBe(BASE_A);

    // HA rotated the session: same panel, new prefix. Everything must re-resolve under
    // the new base (index.html, config.js and the manifest are no-store, so nothing may
    // come out of a cache still pointing at the dead token). Resource timing lists every
    // subresource THIS document fetched — the old page's own (legitimate) BASE_A traffic
    // doesn't pollute it the way a global request listener would.
    await page.goto(`${INGRESS_BASE_URL}${BASE_B}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();
    await expect.poll(async () => page.evaluate(() => window.SPOOLMAN_BASE_PATH)).toBe(BASE_B);
    const staleResources = await page.evaluate(
      (staleBase) =>
        performance
          .getEntriesByType("resource")
          .map((entry) => entry.name)
          .filter((url) => new URL(url).pathname.startsWith(staleBase)),
      BASE_A,
    );
    expect(staleResources, "no request may still use the rotated-out token").toEqual([]);
  });

  test("direct access to the same server keeps today's behavior, PWA included", async ({ page, request }) => {
    // Same process, no ingress prefix — the add-on's published host port. Everything the
    // PWA relies on must behave exactly as an ingress-less deployment (zero loss).
    const manifestRes = await request.get(`${INGRESS_BASE_URL}/manifest.webmanifest`);
    expect((await manifestRes.json()).start_url).toBe("/");

    await page.goto(`${INGRESS_BASE_URL}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();
    const [basePath, ingressFlag] = await page.evaluate(() => [
      window.SPOOLMAN_BASE_PATH,
      window.SPOOLMAN_HA_INGRESS,
    ]);
    expect(basePath).toBe("");
    expect(ingressFlag, "the ingress flag must not leak onto direct access").toBeUndefined();

    // The service worker still registers at the root scope — the PWA stays fully alive.
    await page.waitForFunction(async () => Boolean((await navigator.serviceWorker?.getRegistration())?.active),
      undefined,
      { timeout: 20_000 },
    );
    const scope = await page.evaluate(async () => (await navigator.serviceWorker.getRegistration())?.scope ?? "");
    expect(new URL(scope).pathname).toBe("/");
  });
});
