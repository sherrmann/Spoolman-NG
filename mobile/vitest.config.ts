import { defineConfig } from "vitest/config";

// Unit tests cover only the pure logic modules (src/lib, src/api URL helpers);
// React Native / Expo modules are exercised on-device, not here.
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
