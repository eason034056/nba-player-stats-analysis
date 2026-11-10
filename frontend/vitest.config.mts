import path from "node:path";
import { defineConfig } from "vitest/config";

// Local-date assertions in the suite were written for a US Central clock
// (commence times just after UTC midnight fall on the previous calendar day).
// Pin it here so `vitest` matches `npm test` on a UTC machine.
process.env.TZ = "America/Chicago";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
