/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Deployed under https://sherrmann.github.io/Spoolman-NG/install/ (a sub-path of the
// project Pages site), so asset URLs must stay relative.
export default defineConfig({
  base: "./",
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
