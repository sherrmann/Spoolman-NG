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

/** Locale date + 24h time with seconds, e.g. "08.07.2026 14:30:00" (de) or "07/08/2026 14:30:00" (en). */
export const DATE_TIME_FORMAT = "L HH:mm:ss";

/** Locale date + 24h time without seconds, used in dense table cells. */
export const DATE_TIME_FORMAT_SHORT = "L HH:mm";
