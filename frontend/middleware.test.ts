import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";

import { middleware } from "./middleware";

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

describe("middleware proxy", () => {
  it("rewrites to the backend and replaces x-real-ip", () => {
    setEnv({
      VERCEL: undefined,
      VERCEL_ENV: undefined,
      BACKEND_API_URL: "http://127.0.0.1:3999",
      VERCEL_PROXY_SECRET: "middleware-test-secret",
    });
    const request = new NextRequest("http://localhost:3000/api/backend/api/health?date=2026-01-14", {
      headers: {
        "x-real-ip": "198.51.100.9",
        "x-forwarded-for": "203.0.113.50",
        "x-sportslab-proxy-secret": "browser-sent-secret",
      },
    });
    const response = middleware(request);
    expect(response.headers.get("x-middleware-rewrite")).toBe(
      "http://127.0.0.1:3999/api/health?date=2026-01-14",
    );
    expect(response.headers.get("x-middleware-request-x-real-ip")).toBe("203.0.113.50");
    expect(response.headers.get("x-middleware-request-x-forwarded-for")).toBe("203.0.113.50");
    expect(response.headers.get("x-middleware-request-x-sportslab-proxy-secret")).toBe(
      "middleware-test-secret",
    );
    expect(response.headers.get("x-middleware-override-headers")).toContain("x-real-ip");
    const joined = Array.from(response.headers.entries())
      .map(([, value]) => value)
      .join("\n");
    expect(joined).not.toContain("browser-sent-secret");
    expect(joined).not.toContain("198.51.100.9");
  });

  it("returns 500 and does not rewrite when a Vercel runtime has no secret", async () => {
    setEnv({
      VERCEL: "1",
      VERCEL_ENV: "production",
      BACKEND_API_URL: "https://api.example.com",
      VERCEL_PROXY_SECRET: undefined,
    });
    const request = new NextRequest("http://localhost:3000/api/backend/api/health", {
      headers: { "x-sportslab-proxy-secret": "browser-sent-secret", "x-real-ip": "198.51.100.9" },
    });
    const response = middleware(request);
    expect(response.status).toBe(500);
    expect(response.headers.get("x-middleware-rewrite")).toBeNull();
    const body = await response.text();
    expect(body).toBe("The API proxy is not configured.");
    expect(body).not.toContain("browser-sent-secret");
    expect(body).not.toContain("api.example.com");
  });
});
