import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/** Read a file relative to the repository root (guide/ lives one level below it). */
export function readRepoFile(relPath: string): string {
  return readFileSync(fileURLToPath(new URL(`../../../${relPath}`, import.meta.url)), "utf-8");
}

/**
 * Return the body of the first fenced code block (``` … ```) whose content
 * contains `anchor`. Throws when no block matches so a moved/renamed snippet
 * fails the drift test loudly instead of silently comparing nothing.
 */
export function extractFencedBlock(markdown: string, anchor: string): string {
  const fences = [...markdown.matchAll(/^```[^\n]*\n([\s\S]*?)^```/gm)];
  for (const match of fences) {
    if (match[1].includes(anchor)) return match[1];
  }
  throw new Error(`No fenced block containing anchor ${JSON.stringify(anchor)}`);
}
