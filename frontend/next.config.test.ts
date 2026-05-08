import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);

const {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
} = require("next/constants");

const nextConfigModule = require("./next.config.js");

const resolveConfig = (phase: string) =>
  typeof nextConfigModule === "function"
    ? nextConfigModule(phase, { defaultConfig: {} })
    : nextConfigModule;

describe("next.config", () => {
  it("isolates development output from production output", () => {
    const developmentConfig = resolveConfig(PHASE_DEVELOPMENT_SERVER);
    const productionBuildConfig = resolveConfig(PHASE_PRODUCTION_BUILD);

    expect(developmentConfig.distDir).toBe(".next-dev");
    expect(productionBuildConfig.distDir).toBe(".next");
  });
});
