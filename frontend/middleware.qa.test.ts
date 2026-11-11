import { readdirSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { prepareProxiedRequest, PROXY_NOT_CONFIGURED } = require("./lib/proxy-request");

const SECRET = "qa-real-secret";
const SPOOFED_SECRET = "spoof";
const ORIGIN = "https://api.example.com";
const env = { BACKEND_API_URL: ORIGIN, VERCEL_PROXY_SECRET: SECRET };

function proxy(pathname: string, init?: { search?: string; headers?: Headers; env?: Record<string, string | undefined> }) {
  return prepareProxiedRequest({
    pathname,
    search: init?.search ?? "",
    headers: init?.headers ?? new Headers(),
    env: init?.env ?? env,
  });
}

function stays(pathname: string, expectedPath: string) {
  const prepared = proxy(pathname);
  expect(prepared.ok).toBe(true);
  expect(prepared.destination.origin).toBe(ORIGIN);
  expect(prepared.destination.pathname).toBe(expectedPath);
  expect(prepared.headers.get("x-sportslab-proxy-secret")).toBe(SECRET);
}

function blocked(pathname: string) {
  const prepared = proxy(pathname, {
    headers: new Headers({ "x-sportslab-proxy-secret": SPOOFED_SECRET }),
  });
  expect(prepared.ok).toBe(false);
  expect(prepared.destination).toBeUndefined();
  expect(prepared.message).toBe(PROXY_NOT_CONFIGURED);
  expect(prepared.message).not.toContain(SECRET);
  expect(prepared.message).not.toContain(SPOOFED_SECRET);
  expect(prepared.message).not.toContain("evil.example");
  expect(prepared.message).not.toContain("api.example.com");
}

describe("QA: the proxy destination stays on the backend origin", () => {
  it("rejects a path that starts with //", () => {
    blocked("/api/backend//evil.example/x");
  });

  it("rejects a path that starts with a backslash", () => {
    blocked("/api/backend/\\evil.example/x");
  });

  it("rejects a path that starts with two backslashes", () => {
    blocked("/api/backend/\\\\evil.example/x");
  });

  it("rejects a path that starts with //\\", () => {
    blocked("/api/backend//\\evil.example/x");
  });

  it("rejects a path that starts with ///", () => {
    blocked("/api/backend///evil.example/x");
  });

  it("keeps an encoded %2F%2F on the backend origin", () => {
    stays("/api/backend/%2F%2Fevil.example/x", "/%2F%2Fevil.example/x");
  });

  it("keeps an encoded %5C on the backend origin", () => {
    stays("/api/backend/%5Cevil.example/x", "/%5Cevil.example/x");
  });

  it("keeps an encoded %2F/ on the backend origin", () => {
    stays("/api/backend/%2F/evil.example/x", "/%2F/evil.example/x");
  });

  it("keeps a normal API path on the backend origin", () => {
    stays("/api/backend/api/nba/events", "/api/nba/events");
  });

  it("keeps the prefix itself on the backend origin", () => {
    stays("/api/backend", "/");
  });

  it("rejects a path outside the prefix", () => {
    blocked("/api/nba/events");
  });

  it("rejects ../ once it is normalized outside the prefix", () => {
    const pathname = new NextRequest("http://localhost:3000/api/backend/../admin").nextUrl.pathname;
    blocked(pathname);
  });
});

describe("QA: browser headers cannot override the proxy", () => {
  it("replaces a mixed-case proxy secret", () => {
    const prepared = proxy("/api/backend/api/health", {
      headers: new Headers({ "X-SportsLab-Proxy-Secret": SPOOFED_SECRET }),
    });
    expect(prepared.headers.get("x-sportslab-proxy-secret")).toBe(SECRET);
    const values: string[] = [];
    prepared.headers.forEach((value: string) => values.push(value));
    expect(values.join("\n")).not.toContain(SPOOFED_SECRET);
  });

  it("replaces a spoofed x-real-ip with the first forwarded address", () => {
    const prepared = proxy("/api/backend/api/health", {
      headers: new Headers({
        "x-real-ip": "9.9.9.9",
        "x-forwarded-for": "6.6.6.6, 7.7.7.7",
      }),
    });
    expect(prepared.headers.get("x-real-ip")).toBe("6.6.6.6");
    expect(prepared.headers.get("x-forwarded-for")).toBe("6.6.6.6");
  });

  it("uses the first address when x-forwarded-for is repeated", () => {
    const headers = new Headers();
    headers.append("x-forwarded-for", "6.6.6.6, 7.7.7.7");
    headers.append("x-forwarded-for", "8.8.8.8");
    headers.set("x-real-ip", "9.9.9.9");
    const prepared = proxy("/api/backend/api/health", { headers });
    expect(prepared.headers.get("x-real-ip")).toBe("6.6.6.6");
    expect(prepared.headers.get("x-forwarded-for")).toBe("6.6.6.6");
    const values: string[] = [];
    prepared.headers.forEach((value: string) => values.push(value));
    const serialized = values.join("\n");
    expect(serialized).not.toContain("8.8.8.8");
    expect(serialized).not.toContain("9.9.9.9");
  });

  it("prefers x-vercel-forwarded-for", () => {
    const prepared = proxy("/api/backend/api/health", {
      headers: new Headers({
        "x-real-ip": "9.9.9.9",
        "x-forwarded-for": "6.6.6.6",
        "x-vercel-forwarded-for": "203.0.113.10",
      }),
    });
    expect(prepared.headers.get("x-real-ip")).toBe("203.0.113.10");
    expect(prepared.headers.get("x-forwarded-for")).toBe("203.0.113.10");
  });

  it("deletes both IP headers when no client IP is known", () => {
    const prepared = proxy("/api/backend/api/health", {
      headers: new Headers({ "x-real-ip": "9.9.9.9" }),
    });
    expect(prepared.headers.has("x-real-ip")).toBe(false);
    expect(prepared.headers.has("x-forwarded-for")).toBe(false);
  });

  it("keeps the query string", () => {
    const prepared = proxy("/api/backend/api/nba/events", { search: "?date=2026-01-14" });
    expect(prepared.destination.href).toBe("https://api.example.com/api/nba/events?date=2026-01-14");
  });
});

describe("QA: a Vercel runtime without a usable proxy config does not forward", () => {
  it.each([
    ["the secret is missing", { VERCEL: "1", VERCEL_ENV: "production", BACKEND_API_URL: ORIGIN, VERCEL_PROXY_SECRET: undefined }],
    ["the secret is blank", { VERCEL: "1", VERCEL_ENV: "preview", BACKEND_API_URL: ORIGIN, VERCEL_PROXY_SECRET: "   " }],
    ["the origin is http", { VERCEL: "1", BACKEND_API_URL: "http://api.internal-host.example.net", VERCEL_PROXY_SECRET: SECRET }],
    ["the origin is missing", { VERCEL: "1", VERCEL_ENV: "production", BACKEND_API_URL: undefined, VERCEL_PROXY_SECRET: SECRET }],
  ])("returns the fixed 500 body when %s", (_label, caseEnv) => {
    const prepared = proxy("/api/backend/api/health", {
      env: caseEnv,
      headers: new Headers({ "x-sportslab-proxy-secret": SPOOFED_SECRET, "x-real-ip": "9.9.9.9" }),
    });
    expect(prepared.ok).toBe(false);
    expect(prepared.status).toBe(500);
    expect(prepared.message).toBe(PROXY_NOT_CONFIGURED);
    expect(prepared.destination).toBeUndefined();
    expect(prepared.message).not.toContain(SECRET);
    expect(prepared.message).not.toContain(SPOOFED_SECRET);
    expect(prepared.message).not.toContain("internal-host");
    expect(prepared.message).not.toContain("api.example.com");
    expect(prepared.message).not.toContain("9.9.9.9");
  });
});

describe("QA: the proxy stays out of the client", () => {
  it("matches only /api/backend/:path*", () => {
    const source = readFileSync(path.join(process.cwd(), "middleware.ts"), "utf8");
    expect(source).toContain('matcher: "/api/backend/:path*"');
  });

  it("does not register a next.config.js rewrite", () => {
    const source = readFileSync(path.join(process.cwd(), "next.config.js"), "utf8");
    expect(source).not.toMatch(/rewrites\s*\(/);
    expect(source).toContain("proxyTimeout: 120_000");
  });

  it("does not let client code read the server-only env or import the proxy", () => {
    const skip = new Set(["lib/proxy-request.js", "lib/backend-origin.js"]);
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir)) {
        const full = path.join(dir, entry);
        if (statSync(full).isDirectory()) {
          walk(full);
          continue;
        }
        files.push(full);
      }
    };
    for (const root of ["app", "components", "contexts", "lib"]) {
      walk(path.join(process.cwd(), root));
    }
    for (const file of files) {
      const relative = path.relative(process.cwd(), file);
      if (skip.has(relative) || relative.includes(".test.") || relative.includes(".qa.test.")) {
        continue;
      }
      const source = readFileSync(file, "utf8");
      expect(source, relative).not.toMatch(/process\.env\.VERCEL_PROXY_SECRET/);
      expect(source, relative).not.toMatch(/process\.env\.BACKEND_API_URL/);
      expect(source, relative).not.toMatch(/proxy-request/);
    }
  });
});
