import { readdirSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";

import { config, middleware } from "./middleware";

const require = createRequire(import.meta.url);
const { PROXY_NOT_CONFIGURED, prepareProxiedRequest } = require("./lib/proxy-request");

const BACKEND = "https://api.example.com";
const SECRET = "qa-real-proxy-secret";
const VERCEL_ENV = {
  VERCEL: "1",
  VERCEL_ENV: "production",
  BACKEND_API_URL: BACKEND,
  VERCEL_PROXY_SECRET: SECRET,
};

const ORIGINAL = {
  VERCEL: process.env.VERCEL,
  VERCEL_ENV: process.env.VERCEL_ENV,
  BACKEND_API_URL: process.env.BACKEND_API_URL,
  VERCEL_PROXY_SECRET: process.env.VERCEL_PROXY_SECRET,
};

function setEnv(patch: Record<string, string | undefined>) {
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
}

afterEach(() => {
  setEnv(ORIGINAL);
});

describe("QA: proxied destination never leaves BACKEND_API_URL", () => {
  // new URL("//host/x", origin) and new URL("\\host/x", origin) switch host.
  // next start redirects these before middleware, but the helper must not
  // depend on that: the secret header would go to the other host.
  it.each([
    "/api/backend//evil.example/x",
    "/api/backend/\\evil.example/x",
    "/api/backend/\\\\evil.example/x",
    "/api/backend//\\evil.example/x",
    "/api/backend///evil.example/x",
  ])("does not forward %s to another host", (pathname) => {
    const prepared = prepareProxiedRequest({
      pathname,
      search: "?a=1",
      headers: new Headers(),
      env: VERCEL_ENV,
    });
    if (prepared.ok) {
      expect(prepared.destination.origin).toBe(BACKEND);
    } else {
      expect(prepared.status).toBeGreaterThanOrEqual(400);
      expect(prepared.message).not.toContain(SECRET);
      expect(prepared.message).not.toContain("evil.example");
    }
  });

  it.each([
    "/api/backend/%2F%2Fevil.example/x",
    "/api/backend/%5Cevil.example/x",
    "/api/backend/%2F/evil.example/x",
    "/api/backend/api/nba/events",
    "/api/backend",
  ])("keeps %s on the backend origin", (pathname) => {
    const prepared = prepareProxiedRequest({
      pathname,
      search: "",
      headers: new Headers(),
      env: VERCEL_ENV,
    });
    expect(prepared.ok).toBe(true);
    expect(prepared.destination.origin).toBe(BACKEND);
  });

  it.each(["/api/backendx/health", "/api/other", "/", "/api/backend/../../x"])(
    "refuses %s outside the prefix without forwarding",
    (pathname) => {
      const prepared = prepareProxiedRequest({
        pathname: new URL(pathname, "http://localhost").pathname,
        search: "",
        headers: new Headers(),
        env: VERCEL_ENV,
      });
      expect(prepared.ok).toBe(false);
      expect(prepared.message).toBe(PROXY_NOT_CONFIGURED);
    },
  );
});

describe("QA: spoofed headers through middleware", () => {
  it("replaces mixed-case spoofed secret, x-real-ip and multi-value x-forwarded-for", () => {
    setEnv(VERCEL_ENV);
    const headers = new Headers();
    headers.append("X-SportsLab-Proxy-Secret", "spoofed-secret");
    headers.append("X-Real-IP", "198.51.100.9");
    headers.append("X-Forwarded-For", "203.0.113.50, 198.51.100.77");
    headers.append("x-forwarded-for", "198.51.100.88");
    const response = middleware(
      new NextRequest("https://app.example.com/api/backend/api/health", { headers }),
    );
    expect(response.headers.get("x-middleware-rewrite")).toBe(`${BACKEND}/api/health`);
    expect(response.headers.get("x-middleware-request-x-sportslab-proxy-secret")).toBe(SECRET);
    expect(response.headers.get("x-middleware-request-x-real-ip")).toBe("203.0.113.50");
    expect(response.headers.get("x-middleware-request-x-forwarded-for")).toBe("203.0.113.50");
    const values = Array.from(response.headers.values()).join("\n");
    expect(values).not.toContain("spoofed-secret");
    expect(values).not.toContain("198.51.100.");
  });

  it("prefers x-vercel-forwarded-for over a spoofed x-forwarded-for", () => {
    setEnv(VERCEL_ENV);
    const response = middleware(
      new NextRequest("https://app.example.com/api/backend/api/health", {
        headers: {
          "x-vercel-forwarded-for": "203.0.113.7",
          "x-forwarded-for": "198.51.100.9",
          "x-real-ip": "198.51.100.9",
        },
      }),
    );
    expect(response.headers.get("x-middleware-request-x-real-ip")).toBe("203.0.113.7");
    expect(response.headers.get("x-middleware-request-x-forwarded-for")).toBe("203.0.113.7");
  });

  it("drops x-real-ip and x-forwarded-for when no client IP is known", () => {
    setEnv(VERCEL_ENV);
    const prepared = prepareProxiedRequest({
      pathname: "/api/backend/api/health",
      headers: new Headers({ "x-real-ip": "198.51.100.9" }),
      env: VERCEL_ENV,
    });
    expect(prepared.ok).toBe(true);
    expect(prepared.headers.get("x-real-ip")).toBeNull();
    expect(prepared.headers.get("x-forwarded-for")).toBeNull();
  });

  it("keeps the query string and the request method path intact", () => {
    setEnv(VERCEL_ENV);
    const response = middleware(
      new NextRequest("https://app.example.com/api/backend/api/nba/events?date=2026-01-14&x=a%2Fb", {
        method: "POST",
      }),
    );
    expect(response.headers.get("x-middleware-rewrite")).toBe(
      `${BACKEND}/api/nba/events?date=2026-01-14&x=a%2Fb`,
    );
  });
});

describe("QA: misconfiguration fails closed", () => {
  it.each([
    { VERCEL_PROXY_SECRET: undefined },
    { VERCEL_PROXY_SECRET: "   " },
    { BACKEND_API_URL: "http://api.example.com" },
    { BACKEND_API_URL: undefined },
  ])("returns the constant 500 body and no rewrite for %o", async (patch) => {
    setEnv({ ...VERCEL_ENV, ...patch });
    const response = middleware(
      new NextRequest("https://app.example.com/api/backend/api/health", {
        headers: { "x-sportslab-proxy-secret": "spoofed-secret" },
      }),
    );
    expect(response.status).toBe(500);
    expect(response.headers.get("x-middleware-rewrite")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBeNull();
    const body = await response.text();
    expect(body).toBe(PROXY_NOT_CONFIGURED);
    const all = body + Array.from(response.headers.values()).join("\n");
    expect(all).not.toContain("spoofed-secret");
    expect(all).not.toContain("api.example.com");
  });
});

describe("QA: proxy scope and secret placement", () => {
  it("matches only /api/backend/:path*", () => {
    expect(config.matcher).toBe("/api/backend/:path*");
  });

  it("next.config.js no longer defines rewrites()", async () => {
    const nextConfig = require("./next.config.js");
    const resolved =
      typeof nextConfig === "function" ? await nextConfig("phase-development-server", {}) : nextConfig;
    expect(resolved.rewrites).toBeUndefined();
  });

  it("client code never reads the server-only proxy variables", () => {
    const roots = ["app", "components", "contexts", "lib"].map((dir) => path.join(__dirname, dir));
    const serverOnly = new Set(["backend-origin.js", "proxy-request.js", "proxy-request.d.ts"]);
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const full = path.join(dir, name);
        if (statSync(full).isDirectory()) {
          walk(full);
          continue;
        }
        if (!/\.(ts|tsx|js|jsx)$/.test(name) || /\.test\.(ts|tsx)$/.test(name)) continue;
        if (serverOnly.has(name)) continue;
        const text = readFileSync(full, "utf8");
        // Comments may name the variables; code may not read or import them.
        if (
          /process\.env\.(VERCEL_PROXY_SECRET|BACKEND_API_URL)|["']x-sportslab-proxy-secret["']|from\s+["'][^"']*proxy-request["']|require\(["'][^"']*proxy-request["']\)/.test(
            text,
          )
        ) {
          offenders.push(path.relative(__dirname, full));
        }
      }
    };
    roots.forEach(walk);
    expect(offenders).toEqual([]);
  });
});
