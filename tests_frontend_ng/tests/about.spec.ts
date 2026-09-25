import { expect, test } from "@playwright/test";

/**
 * The version and project links, since upstream's footer went.
 *
 * The footer took a strip at the bottom of every page and pointed its "Report an issue" link at
 * upstream's tracker, where this fork's problems do not belong. It is gone; the Help page carries
 * the same information (the phone layout's More sheet does too -- see mobile/mobile.spec.ts).
 */

test("no page carries the old footer", async ({ page }) => {
  for (const path of ["/", "/home", "/settings"]) {
    await page.goto(path, { waitUntil: "networkidle" });
    await expect(page.locator("header.topbar")).toBeVisible();
    await expect(page.locator("footer"), path).toHaveCount(0);
  }
});

test("the Help page shows the version and links to this fork", async ({ page, request }) => {
  const info = (await (await request.get("/api/v1/info")).json()) as { version: string };
  await page.goto("/help", { waitUntil: "networkidle" });

  const about = page.getByRole("region", { name: "About" });
  await expect(about).toContainText(`Spoolman NG v${info.version}`);
  await expect(about.getByRole("link", { name: "Report an issue" })).toHaveAttribute(
    "href",
    "https://github.com/sherrmann/Spoolman-NG/issues",
  );
  await expect(about.getByRole("link", { name: "Documentation" })).toHaveAttribute(
    "href",
    /^https:\/\/github\.com\/sherrmann\/Spoolman-NG/,
  );
});
