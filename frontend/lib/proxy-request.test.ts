import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const {
  PROXY_NOT_CONFIGURED,
  PROXY_SECRET_HEADER,
  assertProxySecret,
  prepareProxiedRequest,
} = require("./proxy-request");

const SECRET = "env-proxy-secret";
const BROWSER_SECRET = "browser-sent-secret";
const SPOOFED_IP = "198.51.100.9";
const CLIENT_IP = "203.0.113.50";

function headers(init: Record<string, string>) {
  return new Headers(init);
}

describe("proxy request headers", () => {
  it("sets x-sportslab-proxy-secret from VERCEL_PROXY_SECRET", () => {
    const prepared = prepareProxiedRequest({
      pathname: "/api/backend/api/health",
      headers: headers({}),
      env: { BACKEND_API_URL: "https://api.example.com", VERCEL_PROXY_SECRET: SECRET },
    });
    expect(prepared.ok).toBe(true);
    expect(prepared.headers.get(PROXY_SECRET_HEADER)).toBe(SECRET);
    expect(prepared.destination.toString()).toBe("https://api.example.com/api/health");
  });

  it("replaces a browser-sent proxy secret and never forwards it", () => {
    const prepared = prepareProxiedRequest({
      pathname: "/api/backend/api/nba/events",
      search: "?date=2026-01-14",
      headers: headers({ [PROXY_SECRET_HEADER]: BROWSER_SECRET }),
      env: { BACKEND_API_URL: "https://api.example.com", VERCEL_PROXY_SECRET: SECRET },
    });
    expect(prepared.headers.get(PROXY_SECRET_HEADER)).toBe(SECRET);
    expect(prepared.headers.get(PROXY_SECRET_HEADER)).not.toBe(BROWSER_SECRET);
    const serialized = [...prepared.headers.entries()].map(([key, value]) => `${key}: ${value}`).join("\n");
    expect(serialized).not.toContain(BROWSER_SECRET);
  });

  it("replaces a browser-sent x-real-ip with the client IP Vercel provides", () => {
    const prepared = prepareProxiedRequest({
      pathname: "/api/backend/api/health",
      headers: headers({
        "x-real-ip": SPOOFED_IP,
        "x-forwarded-for": `${CLIENT_IP}, 10.0.0.1`,
      }),
      env: { BACKEND_API_URL: "https://api.example.com", VERCEL_PROXY_SECRET: SECRET },
    });
    expect(prepared.headers.get("x-real-ip")).toBe(CLIENT_IP);
    expect(prepared.headers.get("x-real-ip")).not.toBe(SPOOFED_IP);
    expect(prepared.headers.get("x-forwarded-for")).toBe(CLIENT_IP);
    const serialized = [...prepared.headers.entries()].map(([, value]) => value).join("\n");
    expect(serialized).not.toContain(SPOOFED_IP);
  });

  it("prefers x-vercel-forwarded-for over a client-supplied x-forwarded-for", () => {
    const prepared = prepareProxiedRequest({
      pathname: "/api/backend/api/health",
      headers: headers({
        "x-real-ip": SPOOFED_IP,
        "x-forwarded-for": "198.51.100.8",
        "x-vercel-forwarded-for": CLIENT_IP,
      }),
      env: { VERCEL: "1", BACKEND_API_URL: "https://api.example.com", VERCEL_PROXY_SECRET: SECRET },
    });
    expect(prepared.headers.get("x-real-ip")).toBe(CLIENT_IP);
    expect(prepared.headers.get("x-forwarded-for")).toBe(CLIENT_IP);
  });

  it("returns 500 without the secret when Vercel has no VERCEL_PROXY_SECRET", () => {
    const prepared = prepareProxiedRequest({
      pathname: "/api/backend/api/health",
      headers: headers({ [PROXY_SECRET_HEADER]: BROWSER_SECRET, "x-real-ip": SPOOFED_IP }),
      env: { VERCEL: "1", VERCEL_ENV: "preview", BACKEND_API_URL: "https://api.example.com" },
    });
    expect(prepared.ok).toBe(false);
    expect(prepared.status).toBe(500);
    expect(prepared.message).toBe(PROXY_NOT_CONFIGURED);
    expect(prepared.message).not.toContain(BROWSER_SECRET);
    expect(prepared.message).not.toContain(SECRET);
    expect(prepared.message).not.toContain("api.example.com");
    expect(() =>
      assertProxySecret({
        VERCEL: "1",
        BACKEND_API_URL: "https://api.example.com",
        VERCEL_PROXY_SECRET: "   ",
      }),
    ).toThrow(/VERCEL_PROXY_SECRET is required/);
  });

  it("forwards a local request without the proxy secret when the env var is unset", () => {
    const prepared = prepareProxiedRequest({
      pathname: "/api/backend/api/wnba/events",
      headers: headers({
        [PROXY_SECRET_HEADER]: BROWSER_SECRET,
        "x-real-ip": SPOOFED_IP,
        "x-forwarded-for": CLIENT_IP,
      }),
      env: { BACKEND_API_URL: undefined, VERCEL_PROXY_SECRET: undefined },
    });
    expect(prepared.ok).toBe(true);
    expect(prepared.destination.toString()).toBe("http://localhost:8000/api/wnba/events");
    expect(prepared.headers.has(PROXY_SECRET_HEADER)).toBe(false);
    expect(prepared.headers.get("x-real-ip")).toBe(CLIENT_IP);
    const serialized = [...prepared.headers.entries()].map(([, value]) => value).join("\n");
    expect(serialized).not.toContain(BROWSER_SECRET);
  });
});
