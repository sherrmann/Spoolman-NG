import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// UK English is the default when neither the browser nor the user picks a supported
// language: fallbackLng ["en-GB", "en"]. A Vietnamese browser (unsupported locale)
// must land on British strings; an American browser keeps US English via `en`.

test.describe("default language resolution", () => {
  test.describe("unsupported browser locale falls back to UK English", () => {
    test.use({ locale: "vi-VN" });

    test("spool list shows British spellings", async ({ page }) => {
      await page.goto(`${APP_BASE_URL}/spool`);
      await expect(page.getByRole("button", { name: "Colour" })).toBeVisible();
    });
  });

  test.describe("American browser locale keeps US English", () => {
    test.use({ locale: "en-US" });

    test("spool list shows US spellings", async ({ page }) => {
      await page.goto(`${APP_BASE_URL}/spool`);
      // Substring match: the icon contributes "bg-colors" to the accessible name, and
      // "Color" is not a substring of "Colour", so this cannot false-positive on UK.
      await expect(page.getByRole("button", { name: "Color" })).toBeVisible();
    });
  });
});
