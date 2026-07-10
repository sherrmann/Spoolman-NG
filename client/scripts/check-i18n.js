#!/usr/bin/env node

import { readdirSync, readFileSync, statSync } from "fs";
import { dirname, join } from "path";
import process from "process";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const LOCALES_DIR = join(__dirname, "../public/locales");
const I18N_FILE = join(__dirname, "../src/i18n.ts");

const minLocaleFileSize = 1024 * 10; // Minimum 10kB for a locale file to be considered
function getLocaleFolders() {
  return readdirSync(LOCALES_DIR).filter((folder) => {
    const folderPath = join(LOCALES_DIR, folder);
    const commonFilePath = join(folderPath, "common.json");
    return (
      statSync(folderPath).isDirectory() &&
      statSync(commonFilePath).isFile() &&
      statSync(commonFilePath).size >= minLocaleFileSize
    );
  });
}

function getDeclaredLanguages() {
  const i18nContent = readFileSync(I18N_FILE, "utf8");
  const languageMatches = [...i18nContent.matchAll(/\["(.*?)"\]:/g)];
  return languageMatches.map((match) => match[1]);
}

function flattenKeys(obj, prefix = "") {
  const keys = new Set();
  for (const [key, value] of Object.entries(obj)) {
    if (value !== null && typeof value === "object") {
      for (const nested of flattenKeys(value, `${prefix}${key}.`)) {
        keys.add(nested);
      }
    } else {
      keys.add(`${prefix}${key}`);
    }
  }
  return keys;
}

function readLocaleKeys(locale) {
  return flattenKeys(JSON.parse(readFileSync(join(LOCALES_DIR, locale, "common.json"), "utf8")));
}

// Advisory only: translations are allowed to lag behind English, but the gap
// should be visible in every CI run so regressions don't go unnoticed.
function reportKeyCoverage() {
  const referenceKeys = readLocaleKeys("en");
  const locales = readdirSync(LOCALES_DIR)
    .filter((folder) => folder !== "en" && statSync(join(LOCALES_DIR, folder)).isDirectory())
    .sort();

  console.log(`\nKey coverage vs en/common.json (${referenceKeys.size} keys):`);
  for (const locale of locales) {
    const keys = readLocaleKeys(locale);
    const translated = [...referenceKeys].filter((key) => keys.has(key)).length;
    const pct = Math.floor((translated / referenceKeys.size) * 100);
    console.log(`  ${locale.padEnd(8)} ${String(pct).padStart(3)}% (${translated}/${referenceKeys.size})`);
  }
  console.log();
}

// Placeholder integrity (enforced, unlike coverage): a translation that drops or mangles an
// interpolation variable ({{count}}) or a <component> tag renders broken UI at runtime for
// exactly one language — the kind of regression nobody notices until a user reports it.
// Compares the multiset of {{var}} names and <tag> names of every translated key against the
// English value and fails CI on any mismatch.
function extractPlaceholders(value) {
  const tokens = [];
  for (const match of String(value).matchAll(/\{\{\s*([\w.]+)(?:\s*,[^}]*)?\s*\}\}/g)) {
    tokens.push(`{{${match[1]}}}`);
  }
  for (const match of String(value).matchAll(/<\/?\s*([\w-]+)\s*\/?>/g)) {
    tokens.push(`<${match[1]}>`);
  }
  return tokens.sort();
}

function flattenEntries(obj, prefix = "") {
  const entries = new Map();
  for (const [key, value] of Object.entries(obj)) {
    if (value !== null && typeof value === "object") {
      for (const [nestedKey, nestedValue] of flattenEntries(value, `${prefix}${key}.`)) {
        entries.set(nestedKey, nestedValue);
      }
    } else {
      entries.set(`${prefix}${key}`, value);
    }
  }
  return entries;
}

function checkPlaceholderIntegrity() {
  const reference = flattenEntries(JSON.parse(readFileSync(join(LOCALES_DIR, "en", "common.json"), "utf8")));
  const locales = readdirSync(LOCALES_DIR)
    .filter((folder) => folder !== "en" && statSync(join(LOCALES_DIR, folder)).isDirectory())
    .sort();

  const problems = [];
  for (const locale of locales) {
    const entries = flattenEntries(JSON.parse(readFileSync(join(LOCALES_DIR, locale, "common.json"), "utf8")));
    for (const [key, value] of entries) {
      // Plural forms map onto the English _other/_one values; compare against whichever
      // exists so locale-specific categories (_few/_many/_two) are still validated.
      const refValue =
        reference.get(key) ??
        reference.get(key.replace(/_(zero|one|two|few|many)$/, "_other")) ??
        reference.get(key.replace(/_(zero|two|few|many|other)$/, "_one"));
      if (refValue === undefined) continue; // key only exists in the locale — coverage's business, not ours
      const expected = extractPlaceholders(refValue).join(" ");
      const actual = extractPlaceholders(value).join(" ");
      if (expected !== actual) {
        problems.push(`  ${locale}/${key}: expected [${expected || "none"}] but found [${actual || "none"}]`);
      }
    }
  }

  if (problems.length > 0) {
    console.error(`❌ Placeholder mismatches against en/common.json (${problems.length}):`);
    problems.forEach((problem) => console.error(problem));
    console.error("⚠️  Translations must keep every {{variable}} and <tag> from the English value.");
    process.exit(1);
  }
  console.log("✅ All translated values keep their {{variable}} and <tag> placeholders.");
}

function main() {
  const foundLocales = new Set(getLocaleFolders());
  const declaredLocales = new Set(getDeclaredLanguages());

  reportKeyCoverage();
  checkPlaceholderIntegrity();

  const missingLocales = [...foundLocales].filter((locale) => !declaredLocales.has(locale));

  if (missingLocales.length > 0) {
    console.error("❌ The following locales are missing from src/i18n.ts:");
    missingLocales.forEach((locale) => console.error(`  - ${locale}`));
    console.error("⚠️  Please add them to the `languages` object in i18n.ts.");
    console.log("Template:");
    for (const locale of missingLocales) {
      console.log(`["${locale}"]: {
  name: "",
  fullCode: "",
  djs: () => import("dayjs/locale/${locale.toLowerCase()}"),
},`);
    }
    process.exit(1);
  }

  console.log("✅ All locales are properly declared in i18n.ts.");
  process.exit(0);
}

main();
