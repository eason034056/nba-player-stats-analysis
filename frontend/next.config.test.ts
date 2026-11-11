import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);

const {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
} = require("next/constants");

const nextConfigModule = require("./next.config.js");
const { BROWSER_API_PREFIX } = require("./lib/browser-api-prefix");
const { LOCAL_BACKEND_ORIGIN } = require("./lib/backend-origin");

const resolveConfig = (phase: string) =>
  typeof nextConfigModule === "function"
    ? nextConfigModule(phase, { defaultConfig: {} })
    : nextConfigModule;

const ENV_KEYS = ["VERCEL", "VERCEL_ENV", "BACKEND_API_URL"] as const;

function snapshotEnv(): Record<(typeof ENV_KEYS)[number], string | undefined> {
  return {
    VERCEL: process.env.VERCEL,
    VERCEL_ENV: process.env.VERCEL_ENV,
    BACKEND_API_URL: process.env.BACKEND_API_URL,
  };
}

function restoreEnv(saved: Record<(typeof ENV_KEYS)[number], string | undefined>) {
  for (const key of ENV_KEYS) {
    const value = saved[key];
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
}

async function withEnv<T>(
  patch: Record<string, string | undefined>,
  run: () => Promise<T>,
): Promise<T> {
  const saved = snapshotEnv();
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
  try {
    return await run();
  } finally {
    restoreEnv(saved);
  }
}

async function rewritesFor(phase: string) {
  const config = resolveConfig(phase);
  return config.rewrites();
}

describe("next.config", () => {
  it("isolates development output from production output", () => {
    const developmentConfig = resolveConfig(PHASE_DEVELOPMENT_SERVER);
    const productionBuildConfig = resolveConfig(PHASE_PRODUCTION_BUILD);

    expect(developmentConfig.distDir).toBe(".next-dev");
    expect(productionBuildConfig.distDir).toBe(".next");
  });

  it("does not bake a public API URL into the client bundle", () => {
    const config = resolveConfig(PHASE_PRODUCTION_BUILD);
    expect(config.env).toBeUndefined();
    expect(BROWSER_API_PREFIX).toBe("/api/backend");
  });

  it("raises the local rewrite proxy timeout to the Vercel 120s cap", () => {
    const config = resolveConfig(PHASE_DEVELOPMENT_SERVER);
    expect(config.experimental.proxyTimeout).toBe(120_000);
  });

  it("defaults the rewrite to localhost when no Vercel env is set", async () => {
    await withEnv(
      { VERCEL: undefined, VERCEL_ENV: undefined, BACKEND_API_URL: undefined },
      async () => {
        const development = await rewritesFor(PHASE_DEVELOPMENT_SERVER);
        const production = await rewritesFor(PHASE_PRODUCTION_BUILD);
        const expected = [
          {
            source: "/api/backend/:path*",
            destination: `${LOCAL_BACKEND_ORIGIN}/:path*`,
          },
        ];
        expect(development).toEqual(expected);
        expect(production).toEqual(expected);
      },
    );
  });

  it("builds the rewrite destination from BACKEND_API_URL", async () => {
    await withEnv(
      {
        VERCEL: "1",
        VERCEL_ENV: "production",
        BACKEND_API_URL: "https://api.example.com/",
      },
      async () => {
        const rewrites = await rewritesFor(PHASE_PRODUCTION_BUILD);
        expect(rewrites).toEqual([
          {
            source: `${BROWSER_API_PREFIX}/:path*`,
            destination: "https://api.example.com/:path*",
          },
        ]);
      },
    );
  });

  it("throws on a Vercel build when BACKEND_API_URL is missing", async () => {
    const cases = [
      { VERCEL: "1", VERCEL_ENV: undefined, BACKEND_API_URL: undefined },
      { VERCEL: undefined, VERCEL_ENV: "preview", BACKEND_API_URL: undefined },
      { VERCEL: "1", VERCEL_ENV: "production", BACKEND_API_URL: "   " },
    ];

    for (const patch of cases) {
      await withEnv(patch, async () => {
        await expect(rewritesFor(PHASE_PRODUCTION_BUILD)).rejects.toThrow(
          /BACKEND_API_URL is required/,
        );
        await expect(rewritesFor(PHASE_PRODUCTION_BUILD)).rejects.toThrow(
          /will not fall back to http:\/\/localhost:8000/,
        );
      });
    }
  });

  it("rejects a backend URL that is not an origin", async () => {
    await withEnv(
      {
        VERCEL: "1",
        VERCEL_ENV: "preview",
        BACKEND_API_URL: "https://api.example.com/api",
      },
      async () => {
        await expect(rewritesFor(PHASE_PRODUCTION_BUILD)).rejects.toThrow(
          /origin with no path/,
        );
      },
    );
  });
});
