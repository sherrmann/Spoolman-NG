import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import localizedFormat from "dayjs/plugin/localizedFormat";

// Locale-aware date/time display formats (#87). The `L` token renders the date in the active dayjs
// locale's order — DD.MM.YYYY for German, MM/DD/YYYY for US English, YYYY-MM-DD for many others —
// which i18n.ts keeps in sync with the UI language on every language change. The time portion stays
// an explicit 24-hour HH:mm(:ss) to match the app's long-standing convention (all existing pickers
// use use12Hours: false), so switching UI language only changes the date order, never the clock.
//
// localizedFormat enables the L/LT/LTS tokens; customParseFormat lets the antd DatePickers parse a
// localized string back when the user types one. Both extends are idempotent.
dayjs.extend(localizedFormat);
dayjs.extend(customParseFormat);

/** Locale date only, no time, e.g. "08.07.2026" (de) or "07/08/2026" (en). */
export const DATE_FORMAT = "L";

/** Locale date + 24h time with seconds, e.g. "08.07.2026 14:30:00" (de) or "07/08/2026 14:30:00" (en). */
export const DATE_TIME_FORMAT = "L HH:mm:ss";

/** Locale date + 24h time without seconds, used in dense table cells. */
export const DATE_TIME_FORMAT_SHORT = "L HH:mm";

/**
 * Locale date with the month spelled out, e.g. "8. Juli 2026" (de) or "July 8, 2026" (en).
 *
 * The numeric `L` form is right for dense tables, where the column header already says what the
 * number is and every row shares the same order. It is the wrong form for the AI chat's
 * confirm-cards (#378): a single date sits alone in a card the user reads once, while deciding
 * whether to destroy something, and "07/08/2026" is genuinely ambiguous between two continents.
 * Spelling the month out removes that ambiguity without giving up locale awareness — dayjs's
 * `LL` token still orders and translates the parts per the active locale.
 */
export const DATE_FORMAT_LONG = "LL";

/** Long date + 24h time without seconds, for a card date whose clock is meaningful. */
export const DATE_TIME_FORMAT_LONG = "LL HH:mm";
