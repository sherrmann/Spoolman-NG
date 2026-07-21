// Thin driver: loads scripts/render-matrix.ts through Vite's SSR module runner
// so the model's `?raw` fragment imports resolve exactly as they do in the app
// and in vitest — no second loader, no drift.
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const outFlag = process.argv.indexOf("--out");
const outDir = outFlag !== -1 && process.argv[outFlag + 1] ? process.argv[outFlag + 1] : ".matrix";

const server = await createServer({
  configFile: fileURLToPath(new URL("../vite.config.ts", import.meta.url)),
  server: { middlewareMode: true },
  logLevel: "error",
});
try {
  const mod = await server.ssrLoadModule("/scripts/render-matrix.ts");
  mod.renderMatrix(outDir);
} finally {
  await server.close();
}
