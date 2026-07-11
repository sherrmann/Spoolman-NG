import { describe, expect, it } from "vitest";

import {
  compareVersions,
  isUpdateAvailable,
  normalizeVersion,
  parseLatestRelease,
} from "./update";

describe("compareVersions", () => {
  it("orders CalVer components numerically, not lexically", () => {
    expect(compareVersions("2026.7.8", "2026.7.7")).toBe(1);
    expect(compareVersions("2026.7.7", "2026.7.8")).toBe(-1);
    expect(compareVersions("2026.7.8", "2026.7.8")).toBe(0);
    // 10 > 9 numerically even though "10" < "9" as strings.
    expect(compareVersions("2026.10.0", "2026.9.0")).toBe(1);
  });

  it("ignores a leading v and zero-pads shorter versions", () => {
    expect(compareVersions("v2026.7.8", "2026.7.8")).toBe(0);
    expect(compareVersions("2026.7", "2026.7.0")).toBe(0);
    expect(compareVersions("2027.0.0", "2026.12.31")).toBe(1);
  });
});

describe("isUpdateAvailable", () => {
  it("is true only when the release tag is strictly newer", () => {
    expect(isUpdateAvailable("2026.7.7", "v2026.7.8")).toBe(true);
    expect(isUpdateAvailable("2026.7.8", "v2026.7.8")).toBe(false);
    expect(isUpdateAvailable("2026.7.8", "v2026.7.7")).toBe(false);
    // A dev build (0.1.0) is always behind a real release.
    expect(isUpdateAvailable("0.1.0", "v2026.7.8")).toBe(true);
  });
});

describe("normalizeVersion", () => {
  it("strips a leading v and surrounding whitespace", () => {
    expect(normalizeVersion("  v2026.7.8 ")).toBe("2026.7.8");
    expect(normalizeVersion("2026.7.8")).toBe("2026.7.8");
  });
});

describe("parseLatestRelease", () => {
  const payload = {
    tag_name: "v2026.7.8",
    html_url: "https://github.com/sherrmann/Spoolman-NG/releases/tag/v2026.7.8",
    body: "release notes",
    assets: [
      { name: "spoolman.zip", browser_download_url: "https://example/spoolman.zip" },
      {
        name: "spoolman-companion-v2026.7.8.apk",
        browser_download_url:
          "https://github.com/sherrmann/Spoolman-NG/releases/download/v2026.7.8/spoolman-companion-v2026.7.8.apk",
      },
    ],
  };

  it("extracts the tag, normalized version and the companion APK asset", () => {
    const release = parseLatestRelease(payload);
    expect(release).not.toBeNull();
    expect(release?.tag).toBe("v2026.7.8");
    expect(release?.version).toBe("2026.7.8");
    expect(release?.apkUrl).toBe(
      "https://github.com/sherrmann/Spoolman-NG/releases/download/v2026.7.8/spoolman-companion-v2026.7.8.apk",
    );
    expect(release?.htmlUrl).toBe(payload.html_url);
    expect(release?.notes).toBe("release notes");
  });

  it("returns a null apkUrl when no APK is attached (e.g. a failed build)", () => {
    const release = parseLatestRelease({ ...payload, assets: [payload.assets[0]] });
    expect(release?.apkUrl).toBeNull();
  });

  it("returns null for a malformed payload", () => {
    expect(parseLatestRelease(null)).toBeNull();
    expect(parseLatestRelease({})).toBeNull();
    expect(parseLatestRelease({ assets: [] })).toBeNull();
  });
});
