import dayjs from "dayjs";
import i18n from "i18next";
import detector from "i18next-browser-languagedetector";
import Backend from "i18next-http-backend";
import { initReactI18next } from "react-i18next";
import { getBasePath } from "./utils/url";
import type { Locale } from "antd/es/locale";
// @ant-design/pro-provider (pulled in by @refinedev/antd's layout) statically imports
// antd's zh_CN and dayjs's zh-cn as its built-in defaults, so both are always part of
// the entry chunk and a dynamic import() of them can never be split out (rolldown's
// INEFFECTIVE_DYNAMIC_IMPORT warning, #170). Import them statically here too — zero
// size cost — so the zh loaders below don't issue pointless dynamic imports.
import zhCN from "antd/es/locale/zh_CN";
import dayjsZhCn from "dayjs/locale/zh-cn";

interface Language {
  name: string;
  fullCode: string;
  djs: () => Promise<ILocale>;
  antd: () => Promise<Locale>;
}

/**
 * List of languages to load
 * The key of each object is the folder name in the locales dir.
 * name: Name of the language in the list
 * fullCode: Full language code, set as the document language (html lang attribute)
 * djs: Function to load the dayjs locale, see https://github.com/iamkun/dayjs/tree/dev/src/locale for list of locales
 * antd: Function to load the Ant Design locale, resolves to the Locale object itself
 */
export const languages: { [key: string]: Language } = {
  // en is the American-English source catalog; en-GB carries the British spellings and
  // date formats and is the default when nothing else is configured (see fallbackLng).
  ["en"]: {
    name: "English (US)",
    fullCode: "en-US",
    djs: () => import("dayjs/locale/en"),
    antd: () => import("antd/es/locale/en_US").then((m) => m.default),
  },
  ["en-GB"]: {
    name: "English (UK)",
    fullCode: "en-GB",
    djs: () => import("dayjs/locale/en-gb"),
    antd: () => import("antd/es/locale/en_GB").then((m) => m.default),
  },
  ["sv"]: {
    name: "Svenska",
    fullCode: "sv-SE",
    djs: () => import("dayjs/locale/sv"),
    antd: () => import("antd/es/locale/sv_SE").then((m) => m.default),
  },
  ["de"]: {
    name: "Deutsch",
    fullCode: "de-DE",
    djs: () => import("dayjs/locale/de"),
    antd: () => import("antd/es/locale/de_DE").then((m) => m.default),
  },
  ["es"]: {
    name: "Español",
    fullCode: "es-ES",
    djs: () => import("dayjs/locale/es"),
    antd: () => import("antd/es/locale/es_ES").then((m) => m.default),
  },
  ["zh"]: {
    name: "简体中文",
    fullCode: "zh-CN",
    djs: () => Promise.resolve(dayjsZhCn),
    antd: () => Promise.resolve(zhCN),
  },
  ["zh-Hant"]: {
    name: "繁體中文",
    fullCode: "zh-TW",
    djs: () => import("dayjs/locale/zh-hk"),
    antd: () => import("antd/es/locale/zh_TW").then((m) => m.default),
  },
  ["pl"]: {
    name: "Polski",
    fullCode: "pl-PL",
    djs: () => import("dayjs/locale/pl"),
    antd: () => import("antd/es/locale/pl_PL").then((m) => m.default),
  },
  ["ru"]: {
    name: "Русский",
    fullCode: "ru-RU",
    djs: () => import("dayjs/locale/ru"),
    antd: () => import("antd/es/locale/ru_RU").then((m) => m.default),
  },
  ["cs"]: {
    name: "Česky",
    fullCode: "cs-CZ",
    djs: () => import("dayjs/locale/cs"),
    antd: () => import("antd/es/locale/cs_CZ").then((m) => m.default),
  },
  ["nb-NO"]: {
    name: "Norsk bokmål",
    fullCode: "nb-NO",
    djs: () => import("dayjs/locale/nb"),
    antd: () => import("antd/es/locale/nb_NO").then((m) => m.default),
  },
  ["nl"]: {
    name: "Nederlands",
    fullCode: "nl-NL",
    djs: () => import("dayjs/locale/nl"),
    antd: () => import("antd/es/locale/nl_NL").then((m) => m.default),
  },
  ["fr"]: {
    name: "Français",
    fullCode: "fr-FR",
    djs: () => import("dayjs/locale/fr"),
    antd: () => import("antd/es/locale/fr_FR").then((m) => m.default),
  },
  ["hu"]: {
    name: "Magyar",
    fullCode: "hu-HU",
    djs: () => import("dayjs/locale/hu"),
    antd: () => import("antd/es/locale/hu_HU").then((m) => m.default),
  },
  ["it"]: {
    name: "Italiano",
    fullCode: "it-IT",
    djs: () => import("dayjs/locale/it"),
    antd: () => import("antd/es/locale/it_IT").then((m) => m.default),
  },
  ["uk"]: {
    name: "Українська",
    fullCode: "uk-UA",
    djs: () => import("dayjs/locale/uk"),
    antd: () => import("antd/es/locale/uk_UA").then((m) => m.default),
  },
  ["el"]: {
    name: "Ελληνικά",
    fullCode: "el-GR",
    djs: () => import("dayjs/locale/el"),
    antd: () => import("antd/es/locale/el_GR").then((m) => m.default),
  },
  ["da"]: {
    name: "Dansk",
    fullCode: "da-DK",
    djs: () => import("dayjs/locale/da"),
    antd: () => import("antd/es/locale/da_DK").then((m) => m.default),
  },
  ["pt"]: {
    name: "Português",
    fullCode: "pt-PT",
    djs: () => import("dayjs/locale/pt"),
    antd: () => import("antd/es/locale/pt_PT").then((m) => m.default),
  },
  ["fa"]: {
    name: "فارسی",
    fullCode: "fa-IR",
    djs: () => import("dayjs/locale/fa"),
    antd: () => import("antd/es/locale/fa_IR").then((m) => m.default),
  },
  ["ro"]: {
    name: "Român",
    fullCode: "ro-RO",
    djs: () => import("dayjs/locale/ro"),
    antd: () => import("antd/es/locale/ro_RO").then((m) => m.default),
  },
  ["ja"]: {
    name: "日本語",
    fullCode: "ja-JP",
    djs: () => import("dayjs/locale/ja"),
    antd: () => import("antd/es/locale/ja_JP").then((m) => m.default),
  },
  ["pt-BR"]: {
    name: "Português (Brasil)",
    fullCode: "pt-BR",
    djs: () => import("dayjs/locale/pt-br"),
    antd: () => import("antd/es/locale/pt_BR").then((m) => m.default),
  },
  ["ta"]: {
    name: "தமிழ்",
    fullCode: "ta-IN",
    djs: () => import("dayjs/locale/ta"),
    antd: () => import("antd/es/locale/ta_IN").then((m) => m.default),
  },
  ["th"]: {
    name: "ไทย",
    fullCode: "th-TH",
    djs: () => import("dayjs/locale/th"),
    antd: () => import("antd/es/locale/th_TH").then((m) => m.default),
  },
  ["lt"]: {
    name: "Lietuvių",
    fullCode: "lt-LT",
    djs: () => import("dayjs/locale/lt"),
    antd: () => import("antd/es/locale/lt_LT").then((m) => m.default),
  },
  ["tr"]: {
    name: "Türkçe",
    fullCode: "tr-TR",
    djs: () => import("dayjs/locale/tr"),
    antd: () => import("antd/es/locale/tr_TR").then((m) => m.default),
  },
  ["et"]: {
    name: "Eesti",
    fullCode: "et-EE",
    djs: () => import("dayjs/locale/et"),
    antd: () => import("antd/es/locale/et_EE").then((m) => m.default),
  },
  // dayjs has no hi-Latn locale; plain English date formatting fits romanized Hindi UIs better than Devanagari
  ["hi-Latn"]: {
    name: "Hinglish",
    fullCode: "hi-IN",
    djs: () => import("dayjs/locale/en"),
    antd: () => import("antd/es/locale/hi_IN").then((m) => m.default),
  },
  ["ko"]: {
    name: "한국어",
    fullCode: "ko-KR",
    djs: () => import("dayjs/locale/ko"),
    antd: () => import("antd/es/locale/ko_KR").then((m) => m.default),
  },
  ["sl"]: {
    name: "Slovenščina",
    fullCode: "sl-SI",
    djs: () => import("dayjs/locale/sl"),
    antd: () => import("antd/es/locale/sl_SI").then((m) => m.default),
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
