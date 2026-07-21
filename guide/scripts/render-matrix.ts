import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { buildPlan } from "../src/model/plan";
import { presets } from "../src/model/presets";

/**
 * Writes every preset's artifacts to <outDir>/<preset-id>/<filename> so CI can
 * validate them with the real tools: `docker compose config` on each generated
 * docker-compose.yml and `helm template charts/spoolman-ng -f` on each
 * values.yaml (see the guide-tests job in .github/workflows/ci.yml).
 */
export function renderMatrix(outDir: string): void {
  rmSync(outDir, { recursive: true, force: true });
  let fileCount = 0;
  for (const preset of presets) {
    const plan = buildPlan(preset.config);
    if (plan.artifacts.length === 0) continue;
    const presetDir = join(outDir, preset.id);
    mkdirSync(presetDir, { recursive: true });
    for (const artifact of plan.artifacts) {
      writeFileSync(join(presetDir, artifact.filename), artifact.content);
      fileCount += 1;
    }
  }
  console.log(`render-matrix: wrote ${fileCount} artifacts across ${presets.length} presets to ${outDir}`);
}
