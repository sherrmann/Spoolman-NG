import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { expectedContent, SHARED_FILES, targetPath } from "../../scripts/sync-shared.mjs";

// The vendored copies in src/shared/ must stay byte-identical to their
// client/ sources. `npm install` regenerates them (prepare script); this test
// catches a checked-in copy that was hand-edited or left stale.
describe("shared module sync", () => {
  for (const file of SHARED_FILES as Array<{ source: string; target: string }>) {
    it(`${file.target} matches ${file.source}`, () => {
      const actual = readFileSync(targetPath(file), "utf-8");
      expect(actual).toBe(expectedContent(file));
      expect(actual).toContain("AUTO-GENERATED");
    });
  }
});
