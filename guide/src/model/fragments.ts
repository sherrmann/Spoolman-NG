/**
 * Single-source config stanzas. The files in guide/fragments/ are the canonical
 * copies of the snippets embedded in docs/installation.md and README.md — drift
 * tests (src/drift/) fail when either side changes without the other.
 *
 * Placeholders use {{UPPER_SNAKE}}. Rendering throws on unresolved or unused
 * variables so a fragment and its call sites cannot drift apart silently.
 */
const modules = import.meta.glob("../../fragments/*", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const byName: Record<string, string> = {};
for (const [path, content] of Object.entries(modules)) {
  byName[path.split("/").pop() as string] = content;
}

export function fragmentNames(): string[] {
  return Object.keys(byName).sort();
}

export function fragmentPlaceholders(name: string): string[] {
  const raw = byName[name];
  if (raw === undefined) throw new Error(`Unknown fragment: ${name}`);
  return [...raw.matchAll(/\{\{([A-Z0-9_]+)\}\}/g)].map((m) => m[1]);
}

export function renderFragment(name: string, vars: Record<string, string> = {}): string {
  const raw = byName[name];
  if (raw === undefined) throw new Error(`Unknown fragment: ${name}`);
  for (const key of Object.keys(vars)) {
    if (!raw.includes(`{{${key}}}`)) {
      throw new Error(`Fragment ${name}: variable ${key} does not appear in the fragment`);
    }
  }
  return raw.replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, key: string) => {
    const value = vars[key];
    if (value === undefined) throw new Error(`Fragment ${name}: missing value for {{${key}}}`);
    return value;
  });
}
