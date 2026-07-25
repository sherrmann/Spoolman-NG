# Translation status

`en/common.json` is the source of truth. Every other locale here is a translation of it, and
a key missing from a locale falls back to English at runtime.

**None of these translations has been verified by a native speaker.** They are generated and
then machine-reviewed, which catches mechanical damage — wrong meaning, wrong language,
grammar, missing diacritics, terminology drift — but cannot catch "technically correct, reads
like a robot". If a string reads wrong in your language, a one-line fix is a very welcome
pull request; see [Translations](../../../CONTRIBUTING.md#translations).

## Provenance

Two layers, worth telling apart when judging a string:

- **Upstream-inherited** (~7,600 strings across the 30 locales): came from the original
  [Spoolman](https://github.com/Donkie/Spoolman) project's Weblate, contributed by volunteers
  over several years. That platform feeds the original repository, not this fork.
- **Fork-added** (~25,000 strings): generated here, for features this fork added.

## Second-pass review, 2026-07

Every string in every locale (32,646 in total) was reviewed by an independent pass whose
brief was to find defects, not to prefer one phrasing over another. Findings were split into
`error` (applied) and `style` (recorded, not applied — a reviewer allowed to apply
preferences churns correct strings and buries the real defects).

591 corrections were applied. By defect category:

| category | count |
|---|---|
| grammar | 182 |
| terminology | 153 |
| meaning | 138 |
| register | 47 |
| diacritics | 34 |
| untranslated | 19 |
| term-of-art | 11 |
| placeholder | 5 |
| length | 1 |
| wrong language | 1 |

Defect rate by provenance — the useful number, and not the one we expected:

| layer | defects | strings | rate |
|---|---|---|---|
| upstream-inherited | 486 | 7,600 | **6.4%** |
| fork-added | 105 | 25,046 | **0.4%** |

The inherited layer was roughly fifteen times more likely to contain a defect. Some were
severe: Greek had the *description* of a string translated in place of the string itself
(the currency field was labelled "Label for the currency setting"), and a set of dropdown
options rendered as full sentences, breaking the control. Spanish had `"yes": "Si"` — without
the accent that word means "if". Romanian had two values that were the key name
transliterated (`saveAndAdd` → `salveazaSiAdauga`) and one string in Italian.

Read that comparison with its limits in mind: the reviewer and the generator are the same
class of system, so shared blind spots are plausible and the 0.4% is a floor rather than a
clean bill of health. It is evidence that the generated layer is not the weak point here, not
evidence that it is good.

## Automated checks

`npm run check-i18n` (CI) reports per-locale coverage and per-locale advisory signals, and
**fails** the build on:

- a `{{variable}}` or `<tag>` dropped, renamed or mangled relative to the English value;
- a value shaped like a camelCase identifier where the English is real prose — the
  transliterated-key defect above, which no other check could see.

Coverage below 100% is not a failure. Plural coverage is counted per language: Japanese,
Korean, Thai and Chinese correctly have only `_other`; Russian, Polish and Ukrainian use
`_one/_few/_many` and no `_other`; Slovenian has a dual `_two`. Do not "complete" a locale by
adding a plural form its language does not have — i18next would never select it.
