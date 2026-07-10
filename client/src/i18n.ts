import dayjs from "dayjs";
import i18n from "i18next";
import detector from "i18next-browser-languagedetector";
import Backend from "i18next-http-backend";
import { initReactI18next } from "react-i18next";
import { getBasePath } from "./utils/url";

interface Language {
  name: string;
  fullCode: string;
  djs: () => Promise<ILocale>;
}

/**
 * List of languages to load
 * The key of each object is the folder name in the locales dir.
 * name: Name of the language in the list
 * fullCode: Full language code, used for Ant Design's locale
 * djs: Function to load the dayjs locale, see https://github.com/iamkun/dayjs/tree/dev/src/locale for list of locales
 */
export const languages: { [key: string]: Language } = {
  // en is the American-English source catalog; en-GB carries the British spellings and
  // date formats and is the default when nothing else is configured (see fallbackLng).
  ["en"]: {
    name: "English (US)",
    fullCode: "en-US",
    djs: () => import("dayjs/locale/en"),
  },
  ["en-GB"]: {
    name: "English (UK)",
    fullCode: "en-GB",
    djs: () => import("dayjs/locale/en-gb"),
  },
  ["sv"]: {
    name: "Svenska",
    fullCode: "sv-SE",
    djs: () => import("dayjs/locale/sv"),
  },
  ["de"]: {
    name: "Deutsch",
    fullCode: "de-DE",
    djs: () => import("dayjs/locale/de"),
  },
  ["es"]: {
    name: "Español",
    fullCode: "es-ES",
    djs: () => import("dayjs/locale/es"),
  },
  ["zh"]: {
    name: "简体中文",
    fullCode: "zh-CN",
    djs: () => import("dayjs/locale/zh-cn"),
  },
  ["zh-Hant"]: {
    name: "繁體中文",
    fullCode: "zh-TW",
    djs: () => import("dayjs/locale/zh-hk"),
  },
  ["pl"]: {
    name: "Polski",
    fullCode: "pl-PL",
    djs: () => import("dayjs/locale/pl"),
  },
  ["ru"]: {
    name: "Русский",
    fullCode: "ru-RU",
    djs: () => import("dayjs/locale/ru"),
  },
  ["cs"]: {
    name: "Česky",
    fullCode: "cs-CZ",
    djs: () => import("dayjs/locale/cs"),
  },
  ["nb-NO"]: {
    name: "Norsk bokmål",
    fullCode: "nb-NO",
    djs: () => import("dayjs/locale/nb"),
  },
  ["nl"]: {
    name: "Nederlands",
    fullCode: "nl-NL",
    djs: () => import("dayjs/locale/nl"),
  },
  ["fr"]: {
    name: "Français",
    fullCode: "fr-FR",
    djs: () => import("dayjs/locale/fr"),
  },
  ["hu"]: {
    name: "Magyar",
    fullCode: "hu-HU",
    djs: () => import("dayjs/locale/hu"),
  },
  ["it"]: {
    name: "Italiano",
    fullCode: "it-IT",
    djs: () => import("dayjs/locale/it"),
  },
  ["uk"]: {
    name: "Українська",
    fullCode: "uk-UA",
    djs: () => import("dayjs/locale/uk"),
  },
  ["el"]: {
    name: "Ελληνικά",
    fullCode: "el-GR",
    djs: () => import("dayjs/locale/el"),
  },
  ["da"]: {
    name: "Dansk",
    fullCode: "da-DK",
    djs: () => import("dayjs/locale/da"),
  },
  ["pt"]: {
    name: "Português",
    fullCode: "pt-PT",
    djs: () => import("dayjs/locale/pt"),
  },
  ["fa"]: {
    name: "فارسی",
    fullCode: "fa-IR",
    djs: () => import("dayjs/locale/fa"),
  },
  ["ro"]: {
    name: "Român",
    fullCode: "ro-RO",
    djs: () => import("dayjs/locale/ro"),
  },
  ["ja"]: {
    name: "日本語",
    fullCode: "ja-JP",
    djs: () => import("dayjs/locale/ja"),
  },
  ["pt-BR"]: {
    name: "Português (Brasil)",
    fullCode: "pt-BR",
    djs: () => import("dayjs/locale/pt-br"),
  },
  ["ta"]: {
    name: "தமிழ்",
    fullCode: "ta-IN",
    djs: () => import("dayjs/locale/ta"),
  },
  ["th"]: {
    name: "ไทย",
    fullCode: "th-TH",
    djs: () => import("dayjs/locale/th"),
  },
  ["lt"]: {
    name: "Lietuvių",
    fullCode: "lt-LT",
    djs: () => import("dayjs/locale/lt"),
  },
  ["tr"]: {
    name: "Türkçe",
    fullCode: "tr-TR",
    djs: () => import("dayjs/locale/tr"),
  },
  ["et"]: {
    name: "Eesti",
    fullCode: "et-EE",
    djs: () => import("dayjs/locale/et"),
  },
  // dayjs has no hi-Latn locale; plain English date formatting fits romanized Hindi UIs better than Devanagari
  ["hi-Latn"]: {
    name: "Hinglish",
    fullCode: "hi-IN",
    djs: () => import("dayjs/locale/en"),
  },
  ["ko"]: {
    name: "한국어",
    fullCode: "ko-KR",
    djs: () => import("dayjs/locale/ko"),
  },
  ["sl"]: {
    name: "Slovenščina",
    fullCode: "sl-SI",
    djs: () => import("dayjs/locale/sl"),
  },
};

i18n
  .use(Backend)
  .use(detector)
  .use(initReactI18next)
  .init({
    supportedLngs: Object.keys(languages),
    detection: {
      // An American browser (navigator "en-US") should get English (US): "en-US" itself
      // isn't a supported code and would otherwise fall through to the htmlTag default
      // (en-GB). Mapped 1:1 so a stored explicit choice ("en") is never rewritten; every
      // other English variant (en-AU, en-IN, …) intentionally resolves to British English.
      convertDetectedLanguage: (lng: string) => (lng === "en-US" ? "en" : lng),
    },
    backend: {
      loadPath: getBasePath() + "/locales/{{lng}}/{{ns}}.json",
    },
    ns: "common",
    defaultNS: "common",
    // UK English is the default when neither the browser nor the user has picked a
    // supported language ("unless configured otherwise"): a browser asking for en-US
    // still resolves to en via supportedLngs, and any explicit picker choice is cached
    // by the detector. en backs the chain so a key missing from en-GB can never render
    // as a raw key.
    fallbackLng: ["en-GB", "en"],
  });

i18n.on("languageChanged", function (lng) {
  languages[lng].djs().then((djs) => dayjs.locale(djs.name));
  // Keep the document language honest for assistive tech (and the detector's htmlTag
  // source) once the user or detector picks something else than the static default.
  document.documentElement.lang = languages[lng].fullCode;
});

export default i18n;
