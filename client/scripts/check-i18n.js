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

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

// A plural key counts as covered when the locale supplies ANY of its own plural forms, not
// only the English ones. Plural categories are per-language: Japanese and Chinese have a
// single form (_other), Russian and Polish use _one/_few/_many and no _other. Demanding
// English's exact _one/_other set would report those locales as permanently incomplete and,
// worse, invite someone to "fix" the gap by adding an _one form that the language does not
// have and i18next would never select.
function coveredKeyCount(referenceKeys, localeKeys) {
  const pluralBases = new Set(
    [...localeKeys].filter((key) => PLURAL_SUFFIX.test(key)).map((key) => key.replace(PLURAL_SUFFIX, "")),
  );
  return [...referenceKeys].filter(
    (key) => localeKeys.has(key) || (PLURAL_SUFFIX.test(key) && pluralBases.has(key.replace(PLURAL_SUFFIX, ""))),
  ).length;
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
    const translated = coveredKeyCount(referenceKeys, readLocaleKeys(locale));
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

// A value that is just the key name in disguise — "saveAndAdd" -> "salveazaSiAdauga" — is a
// translation that never happened: someone transliterated the identifier instead of the
// sentence. It renders as visible gibberish in the UI, and it is invisible to every other
// check here (the key exists, no placeholders to lose). Enforced, because the shape is
// unambiguous: a single run-together word with an internal capital and no spaces, where the
// English value is real prose. Two of these shipped in ro/common.json for years, inherited
// from upstream, and were only found by a user happening to scroll past them.
const IDENTIFIER_SHAPED = /^[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*$/;

function checkValuesAreNotKeyNames() {
  const reference = flattenEntries(JSON.parse(readFileSync(join(LOCALES_DIR, "en", "common.json"), "utf8")));
  const locales = readdirSync(LOCALES_DIR)
    .filter((folder) => statSync(join(LOCALES_DIR, folder)).isDirectory())
    .sort();

  const problems = [];
  for (const locale of locales) {
    const entries = flattenEntries(JSON.parse(readFileSync(join(LOCALES_DIR, locale, "common.json"), "utf8")));
    for (const [key, value] of entries) {
      if (typeof value !== "string" || !IDENTIFIER_SHAPED.test(value)) continue;
      // An English value that is itself one camelCase word is legitimately untranslatable
      // (an identifier the user must type), so only flag where English is real text.
      const refValue = reference.get(key);
      if (typeof refValue === "string" && IDENTIFIER_SHAPED.test(refValue)) continue;
      problems.push(`  ${locale}/${key}: ${JSON.stringify(value)} looks like the key name, not a translation`);
    }
  }

  if (problems.length > 0) {
    console.error(`❌ Values that look like key names rather than translations (${problems.length}):`);
    problems.forEach((problem) => console.error(problem));
    console.error("⚠️  Translate the English value; do not transliterate the key.");
    process.exit(1);
  }
  console.log("✅ No translated value looks like a transliterated key name.");
}

// Advisory signals that a locale may contain untranslated or machine-mangled text. Not
// enforced — every one of these has legitimate exceptions (proper nouns, identifiers,
// languages that borrow English technical vocabulary) — but a number that jumps between
// runs is worth a look.
function reportSuspiciousValues() {
  const reference = flattenEntries(JSON.parse(readFileSync(join(LOCALES_DIR, "en", "common.json"), "utf8")));
  const locales = readdirSync(LOCALES_DIR)
    .filter((folder) => folder !== "en" && statSync(join(LOCALES_DIR, folder)).isDirectory())
    .sort();

  const rows = [];
  for (const locale of locales) {
    const entries = flattenEntries(JSON.parse(readFileSync(join(LOCALES_DIR, locale, "common.json"), "utf8")));
    let sameAsEnglish = 0;
    let caseMismatch = 0;
    for (const [key, value] of entries) {
      const refValue = reference.get(key);
      if (typeof refValue !== "string" || typeof value !== "string") continue;
      if (value === refValue && /\s/.test(refValue)) sameAsEnglish++;
      const refFirst = refValue.trim()[0];
      const valFirst = value.trim()[0];
      if (refFirst && valFirst && refFirst === refFirst.toUpperCase() && valFirst !== valFirst.toUpperCase()) {
        caseMismatch++;
      }
    }
    rows.push({ locale, sameAsEnglish, caseMismatch });
  }

  console.log("Advisory per-locale signals (untranslated multi-word values / lowercase where English capitalises):");
  for (const { locale, sameAsEnglish, caseMismatch } of rows) {
    console.log(
      `  ${locale.padEnd(8)} same-as-English ${String(sameAsEnglish).padStart(4)}   case-mismatch ${String(caseMismatch).padStart(4)}`,
    );
  }
  console.log();
}

function main() {
  const foundLocales = new Set(getLocaleFolders());
  const declaredLocales = new Set(getDeclaredLanguages());

  reportKeyCoverage();
  reportSuspiciousValues();
  checkValuesAreNotKeyNames();
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
