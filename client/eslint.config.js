import js from "@eslint/js";
import eslintConfigPrettier from "eslint-config-prettier/flat";
import reactPlugin from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["node_modules/", "dist/", "dev-dist/"]),
  {
    files: ["**/*.{js,mjs,cjs,ts,mts,cts,jsx,tsx}"],
    plugins: { js, reactHooks, reactRefresh },
    extends: ["js/recommended"],
    languageOptions: { globals: globals.browser },
    settings: { react: { version: "detect" } },
  },
  tseslint.configs.recommended,
  reactPlugin.configs.flat.recommended,
  reactPlugin.configs.flat["jsx-runtime"],
  {
    // Bare fetch() skips the Authorization header and 401 handling, silently breaking every
    // write under SPOOLMAN_API_TOKEN / user accounts (#224). Route API calls through apiFetch.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.*", "src/test/**", "src/utils/authReloadHandler.ts"],
    rules: {
      "no-restricted-globals": [
        "error",
        {
          name: "fetch",
          message: "Use apiFetch from utils/authReloadHandler so the API token and 401 handling are attached (#224).",
        },
      ],
    },
  },
  eslintConfigPrettier,
]);
