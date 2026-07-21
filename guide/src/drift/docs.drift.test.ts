import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { renderFragment } from "../model/fragments";
import { DOCS_DEFAULTS } from "../model/fragments.test";
import { buildCompose } from "../model/artifacts/compose";
import { defaultConfig } from "../model/config";
import { extractFencedBlock, readRepoFile } from "./repoFiles";

/**
 * Single-source guard: guide/fragments/* are the canonical snippets and
 * docs/installation.md (plus README.md where noted) embeds the same content as
 * fenced blocks. If either side changes without the other, these tests fail —
 * update both together.
 */
const installationMd = readRepoFile("docs/installation.md");
const readmeMd = readRepoFile("README.md");

/** fragment name → [markdown source, anchor substring that locates its fenced block] */
const DOC_ANCHORS: Record<string, Array<[string, string, string]>> = {
  "moonraker-update-manager.ini": [
    ["docs/installation.md", installationMd, "[update_manager Spoolman]"],
    ["README.md", readmeMd, "[update_manager Spoolman]"],
  ],
  "moonraker-spoolman.ini": [["docs/installation.md", installationMd, "[spoolman]"]],
  "caddy.Caddyfile": [["docs/installation.md", installationMd, "reverse_proxy localhost:7912"]],
  "nginx-location.conf": [["docs/installation.md", installationMd, "proxy_set_header Upgrade"]],
  "native-install.sh": [
    ["docs/installation.md", installationMd, "releases/latest/download/spoolman.zip"],
    ["README.md", readmeMd, "releases/latest/download/spoolman.zip"],
  ],
  "native-update.sh": [["docs/installation.md", installationMd, "scripts/update.sh --tag"]],
  "kiauh-install.sh": [["docs/installation.md", installationMd, "install-extension.sh"]],
  "release-info-fix.sh": [["docs/installation.md", installationMd, "release_info.json"]],
};

describe("fragments match their fenced blocks in the docs", () => {
  it("every fragment has at least one documented anchor", () => {
    expect(Object.keys(DOC_ANCHORS).sort()).toEqual(Object.keys(DOCS_DEFAULTS).sort());
  });

  for (const [fragment, anchors] of Object.entries(DOC_ANCHORS)) {
    for (const [sourceName, sourceText, anchor] of anchors) {
      it(`${fragment} ↔ ${sourceName}`, () => {
        const fromDocs = extractFencedBlock(sourceText, anchor);
        const fromFragment = renderFragment(fragment, DOCS_DEFAULTS[fragment]);
        expect(fromFragment.trimEnd()).toBe(fromDocs.trimEnd());
      });
    }
  }
});

describe("compose generator matches the documented examples (semantically)", () => {
  it("quick-start compose block in docs/installation.md", () => {
    const docs = parse(extractFencedBlock(installationMd, "./data:/home/app/.local/share/spoolman"));
    const generated = parse(
      buildCompose({ ...defaultConfig, extras: { ...defaultConfig.extras, tz: "Europe/Stockholm" } }),
    );
    expect(generated.services.spoolman.image).toBe(docs.services.spoolman.image);
    expect(generated.services.spoolman.volumes).toEqual(docs.services.spoolman.volumes);
    expect(generated.services.spoolman.ports).toEqual(docs.services.spoolman.ports);
    expect(generated.services.spoolman.environment).toEqual(docs.services.spoolman.environment);
  });

  it("traefik sub-path example in docs/installation.md", () => {
    const docs = parse(extractFencedBlock(installationMd, "PathPrefix"));
    const generated = parse(buildCompose({ ...defaultConfig, proxy: "traefik", subPath: "/spoolman" }));
    expect(generated.services.spoolman.labels).toEqual(docs.services.spoolman.labels);
    expect(generated.services.spoolman.image).toBe(docs.services.spoolman.image);
    for (const entry of docs.services.spoolman.environment) {
      expect(generated.services.spoolman.environment).toContain(entry);
    }
  });
});
