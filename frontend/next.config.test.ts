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

const ENV_KEYS = ["VERCEL", "VERCEL_ENV", "BACKEND_API_URL", "VERCEL_PROXY_SECRET"] as const;

function snapshotEnv(): Record<(typeof ENV_KEYS)[number], string | undefined> {
  return {
    VERCEL: process.env.VERCEL,
    VERCEL_ENV: process.env.VERCEL_ENV,
    BACKEND_API_URL: process.env.BACKEND_API_URL,
    VERCEL_PROXY_SECRET: process.env.VERCEL_PROXY_SECRET,
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

const localPatch = {
  VERCEL: undefined,
  VERCEL_ENV: undefined,
  BACKEND_API_URL: undefined,
  VERCEL_PROXY_SECRET: undefined,
};

describe("next.config", () => {
  it("isolates development output from production output", async () => {
    await withEnv(localPatch, async () => {
      const developmentConfig = resolveConfig(PHASE_DEVELOPMENT_SERVER);
      const productionBuildConfig = resolveConfig(PHASE_PRODUCTION_BUILD);

      expect(developmentConfig.distDir).toBe(".next-dev");
      expect(productionBuildConfig.distDir).toBe(".next");
    });
  });

  it("does not bake a public API URL into the client bundle", async () => {
    await withEnv(localPatch, async () => {
      const config = resolveConfig(PHASE_PRODUCTION_BUILD);
      expect(config.env).toBeUndefined();
      expect(BROWSER_API_PREFIX).toBe("/api/backend");
    });
  });

  it("raises the local rewrite proxy timeout to the Vercel 120s cap", async () => {
    await withEnv(localPatch, async () => {
      const config = resolveConfig(PHASE_DEVELOPMENT_SERVER);
      expect(config.experimental.proxyTimeout).toBe(120_000);
    });
  });

  it("loads a local config with no rewrite table and no public API URL", async () => {
    await withEnv(
      {
        VERCEL: undefined,
        VERCEL_ENV: undefined,
        BACKEND_API_URL: undefined,
        VERCEL_PROXY_SECRET: undefined,
      },
      async () => {
        const config = resolveConfig(PHASE_PRODUCTION_BUILD);
        expect(config.rewrites).toBeUndefined();
        expect(config.env).toBeUndefined();
        expect(LOCAL_BACKEND_ORIGIN).toBe("http://localhost:8000");
      },
    );
  });

  it("loads a Vercel config when the origin is https and the proxy secret is set", async () => {
    await withEnv(
      {
        VERCEL: "1",
        VERCEL_ENV: "production",
        BACKEND_API_URL: "https://api.example.com/",
        VERCEL_PROXY_SECRET: "build-time-secret",
      },
      async () => {
        const config = resolveConfig(PHASE_PRODUCTION_BUILD);
        expect(config.rewrites).toBeUndefined();
      },
    );
  });

  it("throws on a Vercel build when BACKEND_API_URL is missing", async () => {
    const cases = [
      { VERCEL: "1", VERCEL_ENV: undefined, BACKEND_API_URL: undefined, VERCEL_PROXY_SECRET: "build-time-secret" },
      { VERCEL: undefined, VERCEL_ENV: "preview", BACKEND_API_URL: undefined, VERCEL_PROXY_SECRET: "build-time-secret" },
      { VERCEL: "1", VERCEL_ENV: "production", BACKEND_API_URL: "   ", VERCEL_PROXY_SECRET: "build-time-secret" },
    ];

    for (const patch of cases) {
      await withEnv(patch, async () => {
        expect(() => resolveConfig(PHASE_PRODUCTION_BUILD)).toThrow(/BACKEND_API_URL is required/);
        expect(() => resolveConfig(PHASE_PRODUCTION_BUILD)).toThrow(
          /will not fall back to http:\/\/localhost:8000/,
        );
      });
    }
  });

  it("rejects http and a path on a Vercel build without echoing the value", async () => {
    await withEnv(
      {
        VERCEL: "1",
        VERCEL_ENV: "preview",
        BACKEND_API_URL: "http://api.example.com",
        VERCEL_PROXY_SECRET: "build-time-secret",
      },
      async () => {
        expect(() => resolveConfig(PHASE_PRODUCTION_BUILD)).toThrow(
          "BACKEND_API_URL must use https on a Vercel build.",
        );
      },
    );

    await withEnv(
      {
        VERCEL: "1",
        VERCEL_ENV: "preview",
        BACKEND_API_URL: "https://api.example.com/api",
        VERCEL_PROXY_SECRET: "build-time-secret",
      },
      async () => {
        expect(() => resolveConfig(PHASE_PRODUCTION_BUILD)).toThrow(/origin with no path/);
      },
    );
  });

  it("throws on a Vercel build when VERCEL_PROXY_SECRET is missing", async () => {
    await withEnv(
      {
        VERCEL: "1",
        VERCEL_ENV: "production",
        BACKEND_API_URL: "https://api.example.com",
        VERCEL_PROXY_SECRET: undefined,
      },
      async () => {
        expect(() => resolveConfig(PHASE_PRODUCTION_BUILD)).toThrow(/VERCEL_PROXY_SECRET is required/);
      },
    );
  });
});
