#!/usr/bin/env node
// Validate the copy-paste config blocks in README.md and docs/*.md with the real tools (#303).
//
// The guide's drift tests prove the docs match guide/fragments/; this proves the blocks themselves
// are valid config, including the ones no fragment covers (the Helm values example, the NFC
// compose and nginx/Caddy examples, the quadlet unit). Each fenced block is classified by its
// language tag and content:
//
//   yaml with a top-level `services:`        → docker compose config
//   yaml whose keys are all chart values     → helm template charts/spoolman-ng -f <block>
//   any other yaml                           → must parse
//   ini                                      → must parse; a quadlet unit needs Image= and [Install]
//   nginx                                    → nginx -t, wrapped in http { server { } } as needed
//   caddy                                    → caddy adapt
//
// Usage (from guide/):  node scripts/check-doc-blocks.mjs [--skip-missing]
// Without --skip-missing a tool that is not installed is an error, so CI cannot pass by
// skipping; locally, --skip-missing checks what it can and says what it skipped.

import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";

const repo = fileURLToPath(new URL("../..", import.meta.url));
const skipMissing = process.argv.includes("--skip-missing");

const sources = [
  "README.md",
  ...readdirSync(join(repo, "docs"))
    .filter((f) => f.endsWith(".md"))
    .map((f) => `docs/${f}`),
];
const chartKeys = new Set(Object.keys(parseYaml(readFileSync(join(repo, "charts/spoolman-ng/values.yaml"), "utf8"))));

function blocks(file) {
  const text = readFileSync(join(repo, file), "utf8");
  const found = [];
  // Fences may be indented (inside a list item); the body loses the same indentation.
  for (const match of text.matchAll(/^( *)```([^\n]*)\n([\s\S]*?)^\1```/gm)) {
    const indent = match[1].length;
    const body = match[3]
      .split("\n")
      .map((line) => line.slice(Math.min(indent, line.length - line.trimStart().length)))
      .join("\n");
    const line = text.slice(0, match.index).split("\n").length;
    found.push({ where: `${file}:${line}`, lang: match[2].trim(), body });
  }
  return found;
}

function have(tool) {
  return spawnSync(tool, ["--version"], { stdio: "ignore" }).error === undefined;
}

function run(tool, args, options = {}) {
  const result = spawnSync(tool, args, { encoding: "utf8", ...options });
  if (result.status !== 0) throw new Error((result.stderr || result.stdout || `exit ${result.status}`).trim());
}

const work = mkdtempSync(join(tmpdir(), "doc-blocks-"));
let counter = 0;
function file(name, content) {
  const path = join(work, `${++counter}-${name}`);
  writeFileSync(path, content);
  return path;
}

// nginx -t loads certificates, so the example's paths are pointed at a throwaway pair.
let certPair = null;
function throwawayCert() {
  if (!certPair) {
    const crt = join(work, "example.crt");
    const key = join(work, "example.key");
    execFileSync(
      "openssl",
      [
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=example",
        "-keyout",
        key,
        "-out",
        crt,
      ],
      { stdio: "ignore" },
    );
    certPair = { crt, key };
  }
  return certPair;
}

function checkIni(body) {
  const sections = new Set();
  const keys = new Map();
  let section = null;
  let lastKey = null;
  for (const [index, raw] of body.split("\n").entries()) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || line.startsWith(";")) continue;
    // An indented line continues the previous value (Moonraker's multi-line options).
    if (/^\s/.test(raw) && lastKey !== null) {
      keys.set(lastKey, `${keys.get(lastKey)}\n${line}`);
      continue;
    }
    const header = line.match(/^\[([^\]]+)\]$/);
    if (header) {
      section = header[1];
      sections.add(section);
      lastKey = null;
      continue;
    }
    const pair = line.match(/^([A-Za-z0-9_.-]+)\s*[:=]\s*(.*)$/);
    if (!pair || section === null)
      throw new Error(`line ${index + 1} is neither a [section] nor key = value in a section: ${raw}`);
    lastKey = `${section}.${pair[1]}`;
    keys.set(lastKey, pair[2]);
  }
  if (sections.has("Container")) {
    if (!keys.get("Container.Image")) throw new Error("quadlet unit has no Image= in [Container]");
    if (!sections.has("Install")) throw new Error("quadlet unit has no [Install] section, so it never starts");
  }
}

const checks = {
  compose: {
    tool: "docker",
    check: (body) =>
      run("docker", ["compose", "-f", file("docker-compose.yml", body), "config", "--quiet"], { cwd: work }),
  },
  helm: {
    tool: "helm",
    check: (body) => run("helm", ["template", join(repo, "charts/spoolman-ng"), "-f", file("values.yaml", body)]),
  },
  nginx: {
    tool: "nginx",
    check: (body) => {
      const { crt, key } = throwawayCert();
      let conf = body
        .replace(/^(\s*ssl_certificate_key\s+)\S+;/gm, `$1${key};`)
        .replace(/^(\s*ssl_certificate\s+)\S+;/gm, `$1${crt};`)
        // nginx -t binds the listen sockets: a port below 1024 needs root, which CI runners are
        // not, and a busy port would fail too. Options such as `ssl` are kept.
        .replace(/^(\s*listen\s+)[^;\s]+/gm, "$1127.0.0.1:18443");
      if (!/^\s*server\s*\{/m.test(conf)) conf = `server {\n    listen 127.0.0.1:18080;\n${conf}\n}\n`;
      const config = file(
        "nginx.conf",
        `pid ${work}/nginx.pid;\nerror_log ${work}/nginx-error.log;\nevents {}\nhttp {\n  access_log off;\n${conf}\n}\n`,
      );
      run("nginx", ["-t", "-q", "-p", work, "-c", config]);
    },
  },
  caddy: {
    tool: "caddy",
    check: (body) => run("caddy", ["adapt", "--adapter", "caddyfile", "--config", file("Caddyfile", body)]),
  },
};

function classify({ lang, body }) {
  if (lang === "yaml" || lang === "yml") {
    const doc = parseYaml(body); // throws on invalid YAML, which is the check for the rest
    if (doc && typeof doc === "object" && "services" in doc) return "compose";
    const keys = doc && typeof doc === "object" ? Object.keys(doc) : [];
    if (keys.length > 0 && keys.every((k) => chartKeys.has(k))) return "helm";
    return "yaml";
  }
  if (lang === "ini") return "ini";
  if (lang === "nginx" || lang === "caddy") return lang;
  return null;
}

const failures = [];
const skipped = new Set();
let checked = 0;
try {
  for (const source of sources) {
    for (const block of blocks(source)) {
      let kind;
      try {
        kind = classify(block);
        if (kind === null) continue;
        if (kind === "ini") checkIni(block.body);
        else if (kind !== "yaml") {
          const { tool, check } = checks[kind];
          if (!have(tool)) {
            if (!skipMissing) throw new Error(`${tool} is not installed (pass --skip-missing to check without it)`);
            skipped.add(tool);
            continue;
          }
          check(block.body);
        }
        checked += 1;
        console.log(`ok    ${block.where} (${kind})`);
      } catch (error) {
        failures.push(`${block.where} (${kind ?? block.lang}): ${error.message}`);
        console.log(`FAIL  ${block.where} (${kind ?? block.lang})`);
      }
    }
  }
} finally {
  rmSync(work, { recursive: true, force: true });
}

if (skipped.size) console.log(`\nskipped (not installed): ${[...skipped].join(", ")}`);
if (failures.length) {
  console.error(`\n${failures.length} block(s) failed:\n\n${failures.join("\n\n")}`);
  process.exit(1);
}
console.log(`\n${checked} block(s) valid in ${sources.length} file(s).`);
